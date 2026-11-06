"""كتب الشكر: أنماط الاستهداف الخمسة، المعاينة، المستفيدون، وأثر القواعد."""

from __future__ import annotations

import uuid

from ..errors import conflict, forbidden, not_found, validation
from ..util import as_date, jdump, jload, now_iso, today_iso
from . import audit, employees as E, rules

TARGET_MODES = {
    "all": "جميع الموظفين",
    "females": "الإناث فقط",
    "unit": "مؤسسة واحدة",
    "titles": "عناوين وظيفية محددة",
    "specific": "أشخاص محددون",
}
ISSUER_TYPES = {
    "president": "رئيس الجمهورية",
    "prime_minister": "رئيس الوزراء",
    "minister": "الوزير المختص",
    "authority_head": "رئيس جهة غير مرتبطة بوزارة",
    "undersecretary": "الوكيل",
    "governor": "المحافظ",
    "director_general": "المدير العام",
    "other": "أخرى",
}
ISSUER_ALIASES = {"ministry": "minister", "directorate": "director_general",
                  "unit": "authority_head", "committee": "other"}
BROAD_MODES = {"all", "females", "unit", "titles"}

_CANDIDATE_SQL = (
    "SELECT e.employee_id, e.emp_no, e.full_name, e.gender, e.grade, e.stage, e.category, "
    "e.hire_date, e.end_date, e.unit_id, e.job_title_id, e.assigned_user_id, "
    "h.name AS unit_name, t.name AS title_name, t.code AS title_code "
    "FROM employees e LEFT JOIN health_units h ON h.unit_id=e.unit_id "
    "LEFT JOIN job_titles t ON t.title_id=e.job_title_id "
    "WHERE e.deleted_at IS NULL"
)


def _scope(user: dict) -> tuple[str, tuple]:
    permissions = user.get("permissions") or []
    if "manage_units" in permissions:
        return "", ()
    if user.get("role") == "unit_manager":
        return " AND e.unit_id=?", (user.get("unit_id") or "",)
    return " AND e.assigned_user_id=?", (user.get("user_id") or "",)


def _candidates(db, user: dict, reference_date: str) -> list[dict]:
    clause, args = _scope(user)
    rows = db.query(_CANDIDATE_SQL + " AND e.hire_date<=? AND (e.end_date IS NULL OR "
                    "e.end_date='' OR e.end_date>=?)" + clause + " ORDER BY e.full_name",
                    (reference_date, reference_date, *args))
    for row in rows:
        row["gender_label"] = E.GENDERS.get(row["gender"], row["gender"])
    return rows


def _params(data: dict) -> dict:
    params = data.get("target_params") or {}
    if isinstance(params, str):
        params = jload(params)
    return params


def preview(db, user: dict, data: dict) -> dict:
    mode = str(data.get("target_mode") or "")
    if mode not in TARGET_MODES:
        raise validation("نمط الاستهداف غير معروف.")
    reference = str(data.get("reference_date") or data.get("letter_date") or today_iso())[:10]
    if as_date(reference) is None:
        raise validation("التاريخ المرجعي غير صالح.")
    candidates = _candidates(db, user, reference)
    params = _params(data)
    selected: list[dict] = []
    excluded: list[dict] = []

    if mode in {"all", "females"} and user.get("role") not in {"center_admin", "unit_manager"}:
        raise forbidden("الاستهداف الواسع متاح لمدير المؤسسة أو مدير المركز فقط.")
    if mode == "unit" and user.get("role") not in {"center_admin", "unit_manager"}:
        raise forbidden("استهداف مؤسسة متاح لمدير المؤسسة أو مدير المركز فقط.")

    if mode == "all":
        selected = candidates
    elif mode == "females":
        for row in candidates:
            if row["gender"] == "female":
                selected.append(row)
            else:
                excluded.append({"employee_id": row["employee_id"], "full_name": row["full_name"],
                                 "reason": "ليس أنثى"})
    elif mode == "unit":
        unit_id = str(params.get("unit_id") or "")
        if user.get("role") == "unit_manager":
            unit_id = user.get("unit_id") or ""
        if not unit_id:
            raise validation("اختر المؤسسة.")
        for row in candidates:
            if row["unit_id"] == unit_id:
                selected.append(row)
            else:
                excluded.append({"employee_id": row["employee_id"], "full_name": row["full_name"],
                                 "reason": "خارج المؤسسة المحددة"})
    elif mode == "titles":
        title_ids = {str(item) for item in (params.get("title_ids") or [])}
        if not title_ids:
            raise validation("اختر عنواناً وظيفياً واحداً على الأقل.")
        for row in candidates:
            if str(row["job_title_id"] or "") in title_ids:
                selected.append(row)
            else:
                excluded.append({"employee_id": row["employee_id"], "full_name": row["full_name"],
                                 "reason": "عنوان وظيفي غير مشمول"})
    else:
        ids = [str(item) for item in (params.get("employee_ids") or [])]
        if not ids:
            raise validation("اختر موظفاً واحداً على الأقل.")
        visible = {row["employee_id"]: row for row in candidates}
        for employee_id in ids:
            if employee_id in visible:
                selected.append(visible[employee_id])
            else:
                excluded.append({"employee_id": employee_id, "full_name": "—",
                                 "reason": "غير موجود أو خارج نطاقك"})

    return {"mode": mode, "mode_label": TARGET_MODES[mode], "reference_date": reference,
            "count": len(selected), "excluded": excluded,
            "employees": [{"employee_id": row["employee_id"], "emp_no": row["emp_no"],
                           "full_name": row["full_name"], "unit_name": row["unit_name"],
                           "unit_id": row["unit_id"],
                           "title_name": row["title_name"], "gender": row["gender"]}
                          for row in selected]}


def create(db, user: dict, data: dict, ip: str = "") -> dict:
    mode = str(data.get("target_mode") or "")
    if mode not in TARGET_MODES:
        raise validation("نمط الاستهداف غير معروف.")
    issuer = str(data.get("issuer") or "").strip()
    issuer_type = str(data.get("issuer_type") or "other")
    issuer_type = ISSUER_ALIASES.get(issuer_type, issuer_type)
    letter_no = str(data.get("letter_no") or "").strip()
    letter_date = str(data.get("letter_date") or today_iso())[:10]
    if not issuer or not letter_no:
        raise validation("الجهة المانحة ورقم الكتاب مطلوبان.")
    if issuer_type not in ISSUER_TYPES:
        issuer_type = "other"
    if as_date(letter_date) is None:
        raise validation("تاريخ الكتاب غير صالح.")
    reference = str(data.get("reference_date") or letter_date)[:10]
    preview_data = preview(db, user, {**data, "reference_date": reference})
    if not preview_data["count"]:
        raise validation("لا يوجد موظفون مطابقون لهذا الاستهداف.")

    unit_id = str(data.get("unit_id") or "")
    if user.get("role") in {"unit_manager", "unit_editor"}:
        unit_id = user.get("unit_id") or ""
    if not unit_id:
        unit_ids = {item.get("unit_id") for item in preview_data["employees"]}
        if len(unit_ids) == 1:
            unit_id = next(iter(unit_ids)) or ""
    letter_id = uuid.uuid4().hex
    package = rules.active_package(db, letter_date)
    stamp = now_iso()
    recipients: list[tuple] = []
    package_id = package["package_id"] if package else None
    for item in preview_data["employees"]:
        employee = db.one(_CANDIDATE_SQL + " AND e.employee_id=?", (item["employee_id"],))
        effect = rules.letter_effect(db, package, employee, issuer_type, letter_date) \
            if employee else None
        days = float(effect["days"]) if effect else 0.0
        state = "computed" if effect else "needs_review"
        recipients.append((letter_id, item["employee_id"], 1, days, state,
                           effect["rule_name"] if effect else "لا توجد قاعدة أثر مطابقة"))
    with db.write() as conn:
        conn.execute(
            "INSERT INTO appreciation_letters(letter_id, unit_id, issuer, issuer_type, letter_no, "
            "letter_date, received_date, subject, target_mode, target_params, reference_date, "
            "status, notes, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'draft',?,?,?,?)",
            (letter_id, unit_id or None, issuer, issuer_type, letter_no, letter_date,
             str(data.get("received_date") or "")[:10] or None,
             str(data.get("subject") or "").strip(), mode,
             jdump(_params(data)), reference, str(data.get("notes") or "").strip(),
             user.get("username", ""), stamp, stamp))
        conn.executemany(
            "INSERT INTO appreciation_letter_recipients(letter_id, employee_id, eligible, "
            "effect_days, effect_state, note) VALUES (?,?,?,?,?,?)", recipients)
        audit.log(db, user, "إضافة كتاب شكر", "appreciation_letters", letter_id,
                  f"{issuer} / {letter_no} — {len(recipients)} مستفيد", ip=ip, conn=conn)
        db.set_meta("last_letter_package", package_id or "", conn)
    return {"letter_id": letter_id, "count": len(recipients),
            "package_id": package_id, "needs_review": sum(1 for item in recipients
                                                          if item[4] == "needs_review")}


def list_letters(db, user: dict, limit: int = 500) -> list[dict]:
    permissions = user.get("permissions") or []
    where = ["l.deleted_at IS NULL"]
    args: list = []
    if "manage_units" not in permissions:
        where.append("l.unit_id=?")
        args.append(user.get("unit_id") or "")
    rows = db.query(
        "SELECT l.*, h.name AS unit_name, "
        "(SELECT COUNT(*) FROM appreciation_letter_recipients r WHERE r.letter_id=l.letter_id) "
        "AS recipients_count FROM appreciation_letters l "
        "LEFT JOIN health_units h ON h.unit_id=l.unit_id WHERE " + " AND ".join(where) +
        " ORDER BY l.letter_date DESC, l.created_at DESC LIMIT ?", (*args, limit))
    for row in rows:
        row["mode_label"] = TARGET_MODES.get(row["target_mode"], row["target_mode"])
        row["status_label"] = {"draft": "مسودة", "approved": "معتمد",
                               "cancelled": "ملغى"}.get(row["status"], row["status"])
    return rows


def get_letter(db, user: dict, letter_id: str) -> dict:
    letter = db.one("SELECT * FROM appreciation_letters WHERE letter_id=? AND deleted_at IS NULL",
                    (letter_id,))
    if not letter:
        raise not_found("كتاب الشكر غير موجود.")
    if "manage_units" not in (user.get("permissions") or []):
        if letter["unit_id"] != (user.get("unit_id") or ""):
            raise forbidden("الكتاب خارج نطاق مؤسستك.")
    letter["mode_label"] = TARGET_MODES.get(letter["target_mode"], letter["target_mode"])
    letter["status_label"] = {"draft": "مسودة", "approved": "معتمد",
                              "cancelled": "ملغى"}.get(letter["status"], letter["status"])
    letter["recipients"] = db.query(
        "SELECT r.*, e.emp_no, e.full_name, h.name AS unit_name, t.name AS title_name "
        "FROM appreciation_letter_recipients r JOIN employees e ON e.employee_id=r.employee_id "
        "LEFT JOIN health_units h ON h.unit_id=e.unit_id "
        "LEFT JOIN job_titles t ON t.title_id=e.job_title_id "
        "WHERE r.letter_id=? ORDER BY e.full_name", (letter_id,))
    letter["documents"] = db.query(
        "SELECT d.*, l.link_id, l.purpose FROM document_links l "
        "JOIN documents d ON d.document_id=l.document_id "
        "WHERE l.entity_type='letter' AND l.entity_id=? ORDER BY d.uploaded_at DESC",
        (letter_id,))
    return letter


def approve(db, user: dict, letter_id: str, ip: str = "") -> dict:
    letter = get_letter(db, user, letter_id)
    if letter["status"] == "approved":
        return letter
    package = rules.active_package(db, letter["letter_date"])
    stamp = now_iso()
    with db.write() as conn:
        for recipient in letter["recipients"]:
            employee = db.one(_CANDIDATE_SQL + " AND e.employee_id=?",
                              (recipient["employee_id"],))
            effect = rules.letter_effect(db, package, employee, letter["issuer_type"],
                                         letter["letter_date"]) if employee else None
            conn.execute(
                "UPDATE appreciation_letter_recipients SET eligible=1, effect_days=?, "
                "effect_state=?, note=? WHERE letter_id=? AND employee_id=?",
                (float(effect["days"]) if effect else 0.0,
                 "computed" if effect else "needs_review",
                 effect["rule_name"] if effect else "لا توجد قاعدة أثر مطابقة",
                 letter_id, recipient["employee_id"]))
        conn.execute("UPDATE appreciation_letters SET status='approved', updated_at=? "
                     "WHERE letter_id=?", (stamp, letter_id))
        audit.log(db, user, "اعتماد كتاب شكر", "appreciation_letters", letter_id,
                  letter["letter_no"], ip=ip, conn=conn)
    return get_letter(db, user, letter_id)


def delete_letter(db, user: dict, letter_id: str, ip: str = "") -> dict:
    letter = get_letter(db, user, letter_id)
    if letter["status"] == "approved":
        raise conflict("لا يُحذف كتاب معتمد؛ يمكن إلغاؤه بمعاملة موثقة.")
    with db.write() as conn:
        conn.execute("UPDATE appreciation_letters SET deleted_at=? WHERE letter_id=?",
                     (now_iso(), letter_id))
        audit.log(db, user, "حذف كتاب شكر", "appreciation_letters", letter_id,
                  letter["letter_no"], ip=ip, conn=conn)
    return {"deleted": letter_id}
