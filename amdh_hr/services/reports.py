"""التقارير: الموظفون، الكتب، الأوامر، الوثائق الناقصة، الاستحقاقات القريبة، التدقيق."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ..errors import validation
from ..util import as_date, jload, today_iso
from . import audit, calc, employees as E

REPORT_TYPES = {
    "employees": "سجل الموظفين",
    "employee_history": "السجل الوظيفي التاريخي",
    "letters": "كتب الشكر",
    "letter_recipients": "المستفيدون من كتب الشكر",
    "letters_documents": "مرفقات كتب الشكر",
    "orders": "الأوامر",
    "orders_documents": "مرفقات الأوامر",
    "letters_missing": "كتب الشكر بلا مرفقات",
    "orders_missing": "أوامر بلا مرفقات",
    "upcoming": "الاستحقاقات القريبة",
    "rule_changes": "أثر تغيير القواعد",
    "rule_diff": "فروقات القواعد (موسّعة)",
    "rule_usage": "استخدام إصدارات القواعد",
    "sync": "حزم المزامنة والتعارضات",
    "backups": "سلامة النسخ الاحتياطية",
    "audit": "سجل التدقيق",
}


def _unit_clause(user: dict, column: str = "l.unit_id") -> tuple[str, tuple]:
    permissions = user.get("permissions") or []
    if "manage_units" in permissions:
        return "", ()
    if user.get("role") == "unit_manager":
        return f" AND {column}=?", (user.get("unit_id") or "",)
    return f" AND {column}=?", (user.get("unit_id") or "",)


def run(db, user: dict, report_type: str, filters: dict | None = None) -> dict:
    filters = filters or {}
    if report_type not in REPORT_TYPES:
        raise validation("نوع التقرير غير معروف.")
    title = REPORT_TYPES[report_type]
    if report_type == "employees":
        rows = E.list_employees(db, user, filters.get("search", ""),
                                filters.get("unit_id", ""), limit=100000)
        data = [[row["emp_no"], row["full_name"], row.get("title_name") or "—",
                 f"{row.get('grade') or '—'} / {row.get('stage') or '—'}",
                 row.get("unit_name") or "—", row.get("status_label") or "—",
                 row.get("assigned_username") or "—"] for row in rows]
        return {"title": title, "headers": ["الرقم", "الاسم", "العنوان", "الدرجة/المرحلة",
                                            "المؤسسة", "الحالة", "المسؤول"],
                "rows": data, "note": f"{len(data)} موظف"}
    if report_type in {"letters", "letters_missing"}:
        where = ["l.deleted_at IS NULL"]
        args: list = []
        clause, clause_args = _unit_clause(user)
        where.append(clause.replace(" AND ", "", 1) or "1=1")
        args.extend(clause_args)
        if filters.get("unit_id") and "manage_units" in (user.get("permissions") or []):
            where.append("l.unit_id=?")
            args.append(filters["unit_id"])
        if filters.get("from"):
            where.append("l.letter_date>=?")
            args.append(filters["from"])
        if filters.get("to"):
            where.append("l.letter_date<=?")
            args.append(filters["to"])
        if filters.get("status"):
            where.append("l.status=?")
            args.append(filters["status"])
        if report_type == "letters_missing":
            where.append("NOT EXISTS (SELECT 1 FROM document_links d WHERE "
                         "d.entity_type='letter' AND d.entity_id=l.letter_id)")
        rows = db.query(
            "SELECT l.*, h.name AS unit_name, "
            "(SELECT COUNT(*) FROM appreciation_letter_recipients r WHERE r.letter_id=l.letter_id) "
            "AS recipients_count FROM appreciation_letters l "
            "LEFT JOIN health_units h ON h.unit_id=l.unit_id WHERE " + " AND ".join(where) +
            " ORDER BY l.letter_date DESC", tuple(args))
        data = [[row["letter_date"], row["letter_no"], row["issuer"], row.get("unit_name") or "—",
                 row["recipients_count"],
                 {"draft": "مسودة", "approved": "معتمد"}.get(row["status"], row["status"])]
                for row in rows]
        return {"title": title, "headers": ["التاريخ", "الرقم", "الجهة", "المؤسسة",
                                            "المستفيدون", "الحالة"],
                "rows": data, "note": f"{len(data)} كتاب"}
    if report_type in {"orders", "orders_missing"}:
        where = ["o.deleted_at IS NULL"]
        args = []
        clause, clause_args = _unit_clause(user, "o.unit_id")
        where.append(clause.replace(" AND ", "", 1) or "1=1")
        args.extend(clause_args)
        if filters.get("from"):
            where.append("o.order_date>=?")
            args.append(filters["from"])
        if filters.get("to"):
            where.append("o.order_date<=?")
            args.append(filters["to"])
        if filters.get("type"):
            where.append("o.order_type=?")
            args.append(filters["type"])
        if report_type == "orders_missing":
            where.append("NOT EXISTS (SELECT 1 FROM document_links d WHERE "
                         "d.entity_type='order' AND d.entity_id=o.order_id)")
        rows = db.query(
            "SELECT o.*, h.name AS unit_name, (SELECT COUNT(*) FROM hr_order_recipients r "
            "WHERE r.order_id=o.order_id) AS recipients_count FROM hr_orders o "
            "LEFT JOIN health_units h ON h.unit_id=o.unit_id WHERE " + " AND ".join(where) +
            " ORDER BY o.order_date DESC", tuple(args))
        labels = {"promotion": "ترفيع", "increment": "علاوة", "other": "أخرى"}
        data = [[row["order_date"], row["order_no"], labels.get(row["order_type"]),
                 row.get("unit_name") or "—", row["recipients_count"],
                 {"draft": "مسودة", "approved": "معتمد"}.get(row["status"], row["status"])]
                for row in rows]
        return {"title": title, "headers": ["التاريخ", "الرقم", "النوع", "المؤسسة",
                                            "المستفيدون", "الحالة"],
                "rows": data, "note": f"{len(data)} أمر"}
    if report_type == "upcoming":
        days = int(filters.get("days") or 90)
        as_of = filters.get("as_of") or today_iso()
        start = as_date(as_of) or date.today()
        end = start + timedelta(days=days)
        people = E.list_employees(db, user, limit=1000)
        data = []
        for person in people:
            result = calc.calculate(db, user, person["employee_id"], as_of, persist=False)
            promotion = result["promotion"]
            increment = result["increment"]
            promotion_date = promotion.get("eligible_date") if promotion["state"] == "computed" else ""
            next_increment = increment.get("next_date") if increment["state"] == "computed" else ""
            hit = False
            if promotion_date and start <= (as_date(promotion_date) or start) <= end:
                hit = True
            if next_increment and start <= (as_date(next_increment) or start) <= end:
                hit = True
            if hit:
                data.append([person["emp_no"], person["full_name"],
                             person.get("unit_name") or "—",
                             f"{person.get('grade') or '—'} / {person.get('stage') or '—'}",
                             promotion_date or "—", next_increment or "—"])
        return {"title": title, "headers": ["الرقم", "الاسم", "المؤسسة", "الدرجة/المرحلة",
                                            "استحقاق الترفيع", "العلاوة القادمة"],
                "rows": data, "note": f"{len(data)} موظف خلال {days} يوماً من {as_of}"}
    if report_type == "employee_history":
        clause, args = _unit_clause(user, "e.unit_id")
        where = ["e.deleted_at IS NULL"]
        if filters.get("employee_id"):
            where.append("h.employee_id=?")
            args = (*args, filters["employee_id"])
        if filters.get("search"):
            where.append("(e.full_name LIKE ? OR e.emp_no LIKE ?)")
            like = f"%{filters['search']}%"
            args = (*args, like, like)
        rows = db.query(
            "SELECT h.*, e.emp_no, e.full_name, u.name AS unit_name FROM employee_history h "
            "JOIN employees e ON e.employee_id=h.employee_id "
            "LEFT JOIN health_units u ON u.unit_id=e.unit_id WHERE " +
            " AND ".join(where) + clause + " ORDER BY h.effective_date DESC, h.created_at DESC "
            "LIMIT 5000", args)
        labels = {"تعيين": "تعيين", "hire": "تعيين", "transfer": "نقل", "title": "عنوان",
                  "grade": "درجة", "stage": "مرحلة", "end": "انتهاء", "archive": "أرشفة",
                  "promotion": "ترفيع", "increment": "علاوة"}
        data = [[row["effective_date"], row["emp_no"], row["full_name"],
                 labels.get(row["event_type"], row["event_type"]), row["old_value"] or "—",
                 row["new_value"] or "—", row["order_no"] or "—", row["note"] or "—"]
                for row in rows]
        return {"title": title,
                "headers": ["التاريخ", "الرقم", "الاسم", "الحدث", "السابق", "الجديد",
                            "الأمر", "ملاحظة"],
                "rows": data, "note": f"{len(data)} حدث وظيفي"}
    if report_type == "letter_recipients":
        clause, args = _unit_clause(user, "l.unit_id")
        where = ["l.deleted_at IS NULL"]
        if filters.get("status"):
            where.append("l.status=?")
            args = (*args, filters["status"])
        if filters.get("search"):
            where.append("(e.full_name LIKE ? OR e.emp_no LIKE ? OR l.letter_no LIKE ?)")
            like = f"%{filters['search']}%"
            args = (*args, like, like, like)
        rows = db.query(
            "SELECT l.letter_no, l.letter_date, l.issuer, l.issuer_type, l.status, "
            "e.emp_no, e.full_name, u.name AS unit_name, r.eligible, r.effect_days, "
            "r.effect_state, r.note FROM appreciation_letter_recipients r "
            "JOIN appreciation_letters l ON l.letter_id=r.letter_id "
            "JOIN employees e ON e.employee_id=r.employee_id "
            "LEFT JOIN health_units u ON u.unit_id=e.unit_id WHERE " +
            " AND ".join(where) + clause + " ORDER BY l.letter_date DESC, e.full_name LIMIT 5000",
            args)
        from .letters import ISSUER_TYPES
        data = [[row["letter_no"], row["letter_date"], ISSUER_TYPES.get(
                    row["issuer_type"], row["issuer_type"]), row["emp_no"], row["full_name"],
                 row.get("unit_name") or "—",
                 "نعم" if row["eligible"] else "لا", row["effect_days"] or 0,
                 row["effect_state"] or "—", row["note"] or "—"] for row in rows]
        return {"title": title,
                "headers": ["الكتاب", "التاريخ", "الجهة", "الرقم", "الاسم", "المؤسسة",
                            "مستحق", "أيام", "الحالة", "ملاحظة"],
                "rows": data, "note": f"{len(data)} مستفيد"}
    if report_type in {"letters_documents", "orders_documents"}:
        is_letter = report_type == "letters_documents"
        table = "appreciation_letters" if is_letter else "hr_orders"
        key = "letter_id" if is_letter else "order_id"
        entity = "letter" if is_letter else "order"
        clause, args = _unit_clause(user, f"t.unit_id")
        rows = db.query(
            f"SELECT t.*, u.name AS unit_name, (SELECT COUNT(*) FROM document_links d "
            f"WHERE d.entity_type='{entity}' AND d.entity_id=t.{key}) AS attachments "
            f"FROM {table} t LEFT JOIN health_units u ON u.unit_id=t.unit_id "
            f"WHERE t.deleted_at IS NULL" + clause + " ORDER BY t.created_at DESC LIMIT 5000",
            args)
        data = [[row.get("letter_no") or row.get("order_no"), row.get("letter_date")
                 or row.get("order_date"), row.get("subject") or row.get("order_type") or "—",
                 row.get("unit_name") or "—", row["attachments"],
                 "مكتمل" if row["attachments"] else "ناقص"] for row in rows]
        return {"title": title, "headers": ["الرقم", "التاريخ", "الموضوع", "المؤسسة",
                                            "المرفقات", "الحالة"],
                "rows": data, "note": f"{len(data)} سجل"}
    if report_type == "rule_changes":
        packages = db.query(
            "SELECT * FROM rule_packages WHERE status='published' "
            "ORDER BY effective_from DESC, version DESC LIMIT 2")
        if len(packages) < 2:
            return {"title": title, "headers": ["الحزمة", "القاعدة", "التغيير"],
                    "rows": [], "note": "لا يوجد إصداران منشوران للمقارنة"}
        def rows_map(package_id):
            result = {}
            for row in db.query("SELECT * FROM rule_rows WHERE package_id=?", (package_id,)):
                scope = jload(row["scope"])
                key = (row["rule_type"], row["name"], str(scope))
                result[key] = jload(row["params"])
            return result
        old, new = rows_map(packages[1]["package_id"]), rows_map(packages[0]["package_id"])
        data = []
        for key in sorted(set(old) | set(new)):
            if key not in new:
                data.append([packages[0]["code"], key[1], "محذوفة", str(old[key]), "—"])
            elif key not in old:
                data.append([packages[0]["code"], key[1], "مضافة", "—", str(new[key])])
            elif old[key] != new[key]:
                data.append([packages[0]["code"], key[1], "معدّلة", str(old[key]), str(new[key])])
        return {"title": title,
                "headers": ["الحزمة", "القاعدة", "التغيير", "السابق", "الجديد"],
                "rows": data,
                "note": f"مقارنة {packages[1]['code']} v{packages[1]['version']} ← "
                        f"{packages[0]['code']} v{packages[0]['version']}"}
    if report_type == "rule_diff":
        old_id, new_id = filters.get("old_package"), filters.get("new_package")
        if old_id and new_id:
            old_pkg = db.one("SELECT * FROM rule_packages WHERE package_id=?", (old_id,))
            new_pkg = db.one("SELECT * FROM rule_packages WHERE package_id=?", (new_id,))
        else:
            published = db.query(
                "SELECT * FROM rule_packages WHERE status='published' "
                "ORDER BY effective_from DESC, version DESC LIMIT 2")
            new_pkg = published[0] if published else None
            old_pkg = published[1] if len(published) > 1 else None
        if not old_pkg or not new_pkg:
            return {"title": title, "headers": ["القاعدة", "النطاق", "الحالة", "قبل", "بعد"],
                    "rows": [], "note": "اختر إصدارين منشورين للمقارنة"}
        def detailed(package_id):
            result = {}
            for row in db.query("SELECT * FROM rule_rows WHERE package_id=?", (package_id,)):
                result[(row["rule_type"], row["name"], str(jload(row["scope"])))] = row
            return result
        old_rows, new_rows = detailed(old_pkg["package_id"]), detailed(new_pkg["package_id"])
        labels = {"promotion": "ترفيع", "increment": "علاوة", "letter_effect": "أثر كتاب"}
        data = []
        for key in sorted(set(old_rows) | set(new_rows)):
            old = old_rows.get(key)
            new = new_rows.get(key)
            if old is None:
                state, before, after = "مضافة", "—", str(jload(new["params"]))
            elif new is None:
                state, before, after = "محذوفة", str(jload(old["params"])), "—"
            elif old["params"] != new["params"] or old["active"] != new["active"]:
                state, before, after = "معدّلة", str(jload(old["params"])), str(jload(new["params"]))
            else:
                state, before, after = "دون تغيير", str(jload(old["params"])), str(jload(new["params"]))
            data.append([labels.get(key[0], key[0]), key[1], key[2], state, before, after])
        return {"title": title,
                "headers": ["النوع", "القاعدة", "النطاق", "الحالة", "قبل", "بعد"],
                "rows": data,
                "note": f"{old_pkg['code']} v{old_pkg['version']} "
                        f"({old_pkg['effective_from']}) ← {new_pkg['code']} v{new_pkg['version']} "
                        f"({new_pkg['effective_from']}) — {len(data)} قاعدة"}
    if report_type == "rule_usage":
        rows = db.query(
            "SELECT p.*, (SELECT COUNT(*) FROM calc_runs c WHERE c.package_id=p.package_id) "
            "AS calc_count FROM rule_packages p ORDER BY p.created_at DESC LIMIT 200")
        data = [[row["code"], row["version"], row["status"], row["effective_from"],
                 row.get("published_at") or "—", row["calc_count"]] for row in rows]
        return {"title": title, "headers": ["الحزمة", "الإصدار", "الحالة", "النفاذ",
                                            "النشر", "عمليات الاحتساب"],
                "rows": data, "note": f"{len(data)} إصدار"}
    if report_type == "sync":
        clause, args = _unit_clause(user, "p.source_unit_id")
        rows = db.query("SELECT p.* FROM sync_packages p WHERE 1=1" + clause +
                        " ORDER BY p.created_at DESC LIMIT 500", args)
        labels = {"institution_data": "بيانات مؤسسة", "center_rules": "حزم قواعد",
                  "center_results": "نتائج اعتماد"}
        status = {"exported": "مصدّرة", "imported": "مستوردة", "rejected": "مرفوضة"}
        data = [[row["created_at"], labels.get(row["direction"], row["direction"]),
                 row["source_unit_name"] or "—", status.get(row["status"], row["status"]),
                 row.get("imported_at") or "—", row.get("note") or "—"] for row in rows]
        return {"title": title, "headers": ["التاريخ", "الاتجاه", "المؤسسة", "الحالة",
                                            "الاستيراد", "ملاحظة"],
                "rows": data, "note": f"{len(data)} حزمة"}
    if report_type == "backups":
        if "manage_units" not in (user.get("permissions") or []):
            return {"title": title, "headers": ["التاريخ", "الحالة"], "rows": [],
                    "note": "تقرير النسخ متاح لمدير المركز فقط"}
        rows = db.query("SELECT * FROM backup_jobs ORDER BY ts DESC LIMIT 200")
        data = []
        for row in rows:
            exists = Path(row["path"]).exists() if row.get("path") else False
            data.append([row["ts"], row.get("kind") or "—",
                         f"{round(int(row.get('size') or 0) / 1024, 1)} KB",
                         (row.get("sha256") or "")[:12],
                         "سليمة" if row["ok"] and exists else "مفقودة/تالفة",
                         row.get("note") or "—"])
        return {"title": title, "headers": ["التاريخ", "النوع", "الحجم", "البصمة",
                                            "الحالة", "ملاحظة"],
                "rows": data, "note": f"{len(data)} نسخة"}
    # audit
    rows = audit.recent(db, int(filters.get("limit") or 500))
    if "manage_units" not in (user.get("permissions") or []):
        usernames = {row["username"] for row in db.query(
            "SELECT username FROM users WHERE unit_id=?", (user.get("unit_id") or "",))}
        rows = [row for row in rows if row["username"] in usernames]
    data = [[row["ts"], row["username"], row["action"], row["entity"],
             row["details"]] for row in rows]
    return {"title": title, "headers": ["الوقت", "المستخدم", "الإجراء", "الكيان", "التفاصيل"],
            "rows": data, "note": f"{len(data)} حدث"}
