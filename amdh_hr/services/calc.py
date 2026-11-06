"""محرك الاحتساب: الخدمة + قِدَم كتب الشكر (بالأشهر) + العلاوة والترفيع."""

from __future__ import annotations

import uuid
from datetime import date

from ..errors import validation
from ..util import add_months, as_date, jdump, months_between, now_iso, stamp
from . import audit, employees as E, rules

PROMOTION_DEFAULT = 48
INCREMENT_DEFAULT = 12


def _service_breakdown(hire: date, as_of: date) -> dict:
    days = max(0, (as_of - hire).days)
    months_total = months_between(hire, as_of)
    years, months = divmod(months_total, 12)
    anchor = add_months(hire, months_total)
    remainder = max(0, (as_of - anchor).days) if anchor else 0
    return {"days": days, "months_total": months_total, "years": years, "months": months,
            "days_remainder": remainder}


def _credit_from_effect(effect: dict | None, fallback_days: float) -> tuple[int, int, str]:
    """يعيد (أشهر، سقف سنوي، دورة السقف)."""
    if effect:
        months = int(effect.get("months") or 0)
        if months <= 0 and effect.get("days"):
            months = max(1, round(float(effect["days"]) / 30))
        return months, int(effect.get("cap_months") or 0), \
            str(effect.get("cap_period") or "calendar_year")
    if fallback_days:
        return max(1, round(float(fallback_days) / 30)), 0, "calendar_year"
    return 0, 0, "calendar_year"


def _letters(db, employee: dict, as_of: str, package: dict | None) -> dict:
    rows = db.query(
        "SELECT l.letter_id, l.issuer, l.issuer_type, l.letter_no, l.letter_date, l.subject, "
        "l.status, r.effect_days, r.effect_state FROM appreciation_letter_recipients r "
        "JOIN appreciation_letters l ON l.letter_id=r.letter_id "
        "WHERE r.employee_id=? AND l.deleted_at IS NULL AND l.letter_date<=? "
        "ORDER BY l.letter_date", (employee["employee_id"], as_of))
    detail: list[dict] = []
    credits: list[dict] = []
    warnings: list[str] = []
    drafts = 0
    for row in rows:
        if row["status"] != "approved":
            drafts += 1
            continue
        effect = rules.letter_effect(db, package, employee, row["issuer_type"],
                                     row["letter_date"])
        months, cap_months, cap_period = _credit_from_effect(
            effect, float(row["effect_days"] or 0))
        if not effect and not row["effect_days"]:
            warnings.append(f"كتاب {row['letter_no']} بلا قاعدة أثر مطابقة — لم يُحتسب.")
        credits.append({"letter_id": row["letter_id"], "issuer": row["issuer"],
                        "issuer_type": row["issuer_type"], "letter_no": row["letter_no"],
                        "date": row["letter_date"], "months": months,
                        "cap_months": cap_months, "cap_period": cap_period,
                        "subject": row["subject"], "state": "computed" if effect else "needs_review"})
        detail.append({"letter_id": row["letter_id"], "issuer": row["issuer"],
                       "issuer_type": row["issuer_type"], "letter_no": row["letter_no"],
                       "letter_date": row["letter_date"], "subject": row["subject"],
                       "months": months, "days": months * 30,
                       "state": "computed" if effect else "needs_review"})

    # سقف السنوات الميلادية لكتب الوزير/المخوّل (3 أشهر)، ورئيس الوزراء/الجمهورية بلا سقف.
    used: dict[tuple[str, str], int] = {}
    for credit in credits:
        if credit["cap_months"] <= 0 or credit["months"] <= 0:
            continue
        year = str(credit["date"])[:4]
        key = (year, credit["cap_period"])
        allowed = max(0, credit["cap_months"] - used.get(key, 0))
        if credit["months"] > allowed:
            excess = credit["months"] - allowed
            credit["months"] = allowed
            credit["state"] = "capped"
            warnings.append(
                f"كتاب {credit['letter_no']} تجاوز سقف {credit['cap_months']} أشهر "
                f"لسنة {year}؛ لم يُحتسب {excess} شهراً.")
        used[key] = used.get(key, 0) + credit["months"]

    total = sum(credit["months"] for credit in credits)
    if drafts:
        warnings.append(f"{drafts} كتاب شكر غير معتمد لم يُحتسب في النتيجة.")
    return {"months": total, "days": total * 30, "count": len(detail), "detail": detail,
            "credits": credits, "allocations": [], "warnings": warnings}


def _apply_credit(credits: list[dict], promo_due: date, inc_due: date,
                  promo_required: int, inc_required: int,
                  track_order=("promotion", "increment")
                  ) -> tuple[dict, dict, list[dict], list[str]]:
    """يوزّع أشهر القِدَم على الاستحقاق الأقرب أولاً، ويرحّل الفائض للدورة التالية."""
    state = {"promotion": promo_due, "increment": inc_due}
    future = {"promotion": add_months(promo_due, promo_required),
              "increment": add_months(inc_due, inc_required)}
    required = {"promotion": promo_required, "increment": inc_required}
    allocations: list[dict] = []
    warnings: list[str] = []
    guard = 0
    for credit in credits:
        remaining = int(credit["months"])
        if remaining <= 0:
            continue
        issue = as_date(credit["date"])
        if issue is None:
            continue
        guard = 0
        while remaining > 0 and guard < 100:
            guard += 1
            candidates: list[tuple[str, date, str]] = []
            for track in track_order:
                if state[track] > issue:
                    candidates.append((track, state[track], "current"))
                elif future[track] > issue:
                    candidates.append((track, future[track], "future"))
            if not candidates:
                track = min(track_order, key=lambda item: future[item])
                allocations.append({"letter_no": credit["letter_no"], "track": track,
                                    "months": 0, "date": credit["date"],
                                    "due": future[track].isoformat(), "state": "rollover"})
                future[track] = add_months(future[track], required[track])
                continue
            candidates.sort(key=lambda item: item[1])
            progressed = False
            for track, due, kind in candidates:
                if remaining <= 0:
                    break
                gap = months_between(issue, due)
                if gap <= 0:
                    continue
                shift = min(remaining, gap)
                new_due = add_months(due, -shift)
                if new_due < issue:
                    new_due = issue
                if kind == "current":
                    state[track] = new_due
                else:
                    future[track] = new_due
                remaining -= shift
                allocations.append({"letter_no": credit["letter_no"], "track": track,
                                    "months": shift, "date": credit["date"],
                                    "due": new_due.isoformat(), "state": "applied"})
                progressed = True
            if not progressed:
                track, _due, kind = candidates[0]
                if kind == "current":
                    future[track] = add_months(state[track], required[track])
                else:
                    future[track] = add_months(future[track], required[track])
                allocations.append({"letter_no": credit["letter_no"], "track": track,
                                    "months": 0, "date": credit["date"],
                                    "due": future[track].isoformat(), "state": "rollover"})
    if guard >= 100:
        warnings.append("تعذّر توزيع كامل القِدَم؛ راجع تواريخ الكتب والدرجة/المرحلة.")
    return state, future, allocations, warnings


def calculate(db, user: dict, employee_id: str, as_of: str = "", ip: str = "",
              persist: bool = True, tie_policy: str = "promotion") -> dict:
    employee = E.get_employee(db, user, employee_id)
    target = as_date(as_of) if as_of else date.today()
    if target is None:
        raise validation("تاريخ الاحتساب غير صالح.")
    hire = as_date(employee["hire_date"])
    if hire is None:
        raise validation("الموظف بلا تاريخ مباشرة صالح.")
    if employee.get("end_date") and as_date(employee["end_date"]) and \
            target > as_date(employee["end_date"]):
        target = as_date(employee["end_date"])
    as_of_text = target.isoformat()

    package = rules.active_package(db, as_of_text)
    service = _service_breakdown(hire, target)
    letters = _letters(db, employee, as_of_text, package)
    warnings: list[str] = list(letters["warnings"])

    grade_start = as_date(employee.get("last_grade_date")) or hire
    stage_start = as_date(employee.get("last_stage_date")) or hire
    if not employee.get("last_grade_date"):
        warnings.append("تاريخ الدرجة الحالية غير مسجل — استُخدم تاريخ المباشرة.")
    if not employee.get("last_stage_date"):
        warnings.append("تاريخ المرحلة الحالية غير مسجل — استُخدم تاريخ المباشرة.")

    promotion: dict = {"state": "needs_rules", "eligible_date": "", "required_months": 0,
                       "credit_months": 0, "rule": None, "eligible": False}
    increment: dict = {"state": "needs_rules", "eligible_date": "", "next_date": "",
                       "required_months": 0, "credit_months": 0, "rule": None,
                       "eligible": False}

    if package is None:
        warnings.append("لا توجد حزمة قواعد منشورة ونافذة في هذا التاريخ — النتيجة استرشادية "
                        "بلا أهلية.")
    else:
        promo_rule = rules.promotion_rule(db, package, employee)
        inc_rule = rules.increment_rule(db, package, employee)
        promo_required = int((promo_rule or {}).get("required_months") or PROMOTION_DEFAULT)
        inc_required = int((inc_rule or {}).get("required_months") or INCREMENT_DEFAULT)
        if not promo_rule:
            warnings.append("لا توجد قاعدة ترفيع مطابقة؛ استُخدمت المدة الافتراضية 48 شهراً.")
        if not inc_rule:
            warnings.append("لا توجد قاعدة علاوة مطابقة؛ استُخدمت المدة الافتراضية 12 شهراً.")

        promo_due = add_months(grade_start, promo_required)
        inc_due = add_months(stage_start, inc_required)
        tie = promo_due == inc_due
        state, future, allocations, alloc_warnings = _apply_credit(
            letters["credits"], promo_due, inc_due, promo_required, inc_required,
            ("increment", "promotion") if tie and tie_policy == "increment"
            else ("promotion", "increment"))
        warnings.extend(alloc_warnings)
        promo_due, inc_due = state["promotion"], state["increment"]
        letters["allocations"] = allocations
        if tie:
            warnings.append("تاريخا استحقاق العلاوة والترفيع متساويان؛ طُبّق القِدَم على "
                            + ("العلاوة" if tie_policy == "increment" else "الترفيع")
                            + " أولاً، ويمكن للمدير تغيير الاختيار.")

        promo_credit = sum(item["months"] for item in allocations if item["track"] == "promotion")
        inc_credit = sum(item["months"] for item in allocations if item["track"] == "increment")
        promotion = {
            "state": "computed", "eligible": promo_due <= target,
            "eligible_date": promo_due.isoformat(), "required_months": promo_required,
            "credit_months": promo_credit, "rule": promo_rule, "tie": tie,
            "target_grade": (promo_rule or {}).get("to_grade", ""),
            "target_stage": (promo_rule or {}).get("to_stage", ""),
        }
        next_inc = future["increment"] if inc_due <= target else inc_due
        guard_next = 0
        while next_inc <= target and guard_next < 120:
            next_inc = add_months(next_inc, inc_required)
            guard_next += 1
        increment = {
            "state": "computed", "eligible": inc_due <= target,
            "eligible_date": inc_due.isoformat(),
            "next_date": next_inc.isoformat(),
            "required_months": inc_required, "credit_months": inc_credit,
            "rule": inc_rule, "tie": tie,
            "max_stage": (inc_rule or {}).get("max_stage", ""),
        }
        if increment["max_stage"] and \
                str(employee.get("stage") or "") >= increment["max_stage"]:
            increment["at_max_stage"] = True

    if not employee.get("job_title_id"):
        warnings.append("الموظف بلا عنوان وظيفي — قد تتأثر قواعد الأقدمية.")
    if not str(employee.get("grade") or ""):
        warnings.append("درجة الموظف غير محددة.")
    if not str(employee.get("stage") or ""):
        warnings.append("مرحلة الموظف غير محددة.")

    total_months = service["months_total"] + int(letters["months"])
    years, months = divmod(total_months, 12)
    result = {
        "engine_version": rules.ENGINE_VERSION,
        "state": "estimated" if package else "needs_rules",
        "as_of": as_of_text,
        "employee": {
            "employee_id": employee["employee_id"], "emp_no": employee["emp_no"],
            "full_name": employee["full_name"], "unit_name": employee.get("unit_name"),
            "title_name": employee.get("title_name"), "grade": employee.get("grade"),
            "stage": employee.get("stage"), "hire_date": employee["hire_date"],
            "last_grade_date": employee.get("last_grade_date") or employee["hire_date"],
            "last_stage_date": employee.get("last_stage_date") or employee["hire_date"],
            "status": employee.get("status"),
        },
        "package": rules.package_json(package),
        "service": service,
        "letters": letters,
        "seniority": {"days": service["days"] + int(letters["months"]) * 30,
                      "months": total_months, "years": years, "remaining_months": months},
        "promotion": promotion,
        "increment": increment,
        "tie_policy": tie_policy,
        "warnings": warnings,
    }
    run_id = uuid.uuid4().hex
    if persist:
        with db.write() as conn:
            conn.execute("INSERT INTO calc_runs(run_id, employee_id, as_of, package_id, result, "
                         "created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                         (run_id, employee_id, as_of_text,
                          package["package_id"] if package else None, jdump(result),
                          user.get("username", ""), now_iso()))
            audit.log(db, user, "احتساب استرشادي", "employees", employee_id,
                      f"بتاريخ {as_of_text} — {result['state']}", ip=ip, conn=conn)
        result["run_id"] = run_id
    return result


def summary_text(result: dict) -> str:
    """ملخص عربي للعرض والطباعة."""
    employee = result["employee"]
    service = result["service"]
    letters = result["letters"]
    lines = [
        f"الموظف: {employee['full_name']} — الرقم {employee['emp_no']}",
        f"المؤسسة: {employee.get('unit_name') or '—'} · العنوان: {employee.get('title_name') or '—'}",
        f"الدرجة/المرحلة: {employee.get('grade') or '—'} / {employee.get('stage') or '—'}",
        f"تاريخ المباشرة: {employee['hire_date']} · تاريخ الاحتساب: {result['as_of']}",
        f"الخدمة: {service['years']} سنة و{service['months']} شهراً و{service['days_remainder']} يوماً",
        f"أثر كتب الشكر: {letters['months']} شهراً ({letters['count']} سجل)",
        f"مجموع القدم: {result['seniority']['months']} شهراً",
    ]
    promotion = result["promotion"]
    if promotion["state"] == "computed":
        state = "مستوفٍ" if promotion["eligible"] else "غير مستوفٍ"
        lines.append(f"الترفيع: {state} — تاريخ الاستحقاق {promotion['eligible_date']} "
                     f"(مطلوب {promotion['required_months']} شهراً، خُصم "
                     f"{promotion['credit_months']} شهراً)")
    else:
        lines.append("الترفيع: لا توجد قاعدة مطابقة.")
    increment = result["increment"]
    if increment["state"] == "computed":
        lines.append(f"العلاوة: الاستحقاق {increment['eligible_date']} — "
                     f"القادم {increment['next_date']} (خُصم "
                     f"{increment['credit_months']} شهراً)")
    else:
        lines.append("العلاوة: لا توجد قاعدة مطابقة.")
    package = result.get("package") or {}
    if package:
        lines.append(f"حزمة القواعد: {package['code']} إصدار {package['version']} "
                     f"(نافذة من {package['effective_from']})")
    else:
        lines.append("حزمة القواعد: غير محددة")
    for warning in result["warnings"]:
        lines.append(f"تنبيه: {warning}")
    return "\n".join(lines)


def latest_runs(db, employee_id: str, limit: int = 10) -> list[dict]:
    return db.query("SELECT run_id, as_of, package_id, created_at, created_by, result "
                    "FROM calc_runs WHERE employee_id=? ORDER BY created_at DESC LIMIT ?",
                    (employee_id, limit))


def export_pdf(db, user: dict, employee_id: str, as_of: str, paths,
               tie_policy: str = "promotion", ip: str = "") -> dict:
    """يحفظ نتيجة الاحتساب كملف PDF مباشر."""
    from ..exporters import pdf as PDF
    result = calculate(db, user, employee_id, as_of, ip=ip, persist=False,
                       tie_policy=tie_policy)
    employee = result["employee"]
    promotion = result["promotion"]
    increment = result["increment"]
    letters = result["letters"]
    service = result["service"]
    center = db.one("SELECT name FROM health_units WHERE is_center=1 AND deleted_at IS NULL")
    rows = [
        ["الموظف", f"{employee['full_name']} — {employee['emp_no']}"],
        ["المؤسسة / العنوان", f"{employee.get('unit_name') or '—'} / "
                              f"{employee.get('title_name') or '—'}"],
        ["الدرجة / المرحلة", f"{employee.get('grade') or '—'} / "
                             f"{employee.get('stage') or '—'}"],
        ["تاريخ المباشرة", employee["hire_date"]],
        ["تاريخ الدرجة / المرحلة", f"{employee['last_grade_date']} / "
                                    f"{employee['last_stage_date']}"],
        ["الخدمة", f"{service['years']} سنة و{service['months']} شهراً و"
                   f"{service['days_remainder']} يوماً"],
        ["أثر كتب الشكر", f"{letters['months']} شهراً ({letters['count']} سجل)"],
        ["مجموع القدم", f"{result['seniority']['months']} شهراً"],
    ]
    if promotion.get("state") == "computed":
        rows.append(["الترفيع", ("مستوفٍ" if promotion.get("eligible") else "غير مستوفٍ")
                     + f" — الاستحقاق {promotion.get('eligible_date')} "
                       f"(مطلوب {promotion.get('required_months')} شهراً، "
                       f"خصم {promotion.get('credit_months', 0)})"])
    else:
        rows.append(["الترفيع", "لا توجد قاعدة مطابقة"])
    if increment.get("state") == "computed":
        rows.append(["العلاوة", f"الاستحقاق {increment.get('eligible_date')} — "
                                f"القادم {increment.get('next_date')} "
                                f"(خصم {increment.get('credit_months', 0)} شهراً)"])
    else:
        rows.append(["العلاوة", "لا توجد قاعدة مطابقة"])
    rows.append(["حزمة القواعد", (result.get("package") or {}).get("code", "—")])
    for warning in result["warnings"]:
        rows.append(["تنبيه", warning])
    path = paths.exports_dir / f"احتساب_{employee['emp_no']}_{stamp()}.pdf"
    PDF.export_report(path, "نتيجة الاحتساب", ["البند", "القيمة"], rows,
                      f"{employee['full_name']} — بتاريخ {result['as_of']}",
                      center["name"] if center else "")
    return {"path": str(path), "result": result}
