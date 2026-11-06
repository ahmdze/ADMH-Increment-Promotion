"""الموظفون: الملف الوظيفي، العنوان التاريخي، التوزيع، والاستيراد/التصدير."""

from __future__ import annotations

import uuid
from pathlib import Path

from ..errors import conflict, forbidden, not_found, validation
from ..exporters import excel as X
from ..util import now_iso, today_iso
from . import audit

STATUSES = {
    "active": "على الملاك",
    "suspended": "موقوف",
    "ended": "منتهي",
    "retired": "متقاعد",
}
GENDERS = {"male": "ذكر", "female": "أنثى"}

_QUERY = (
    "SELECT e.*, h.name AS unit_name, h.code AS unit_code, "
    "t.name AS title_name, t.code AS title_code, "
    "u.username AS assigned_username, u.display_name AS assigned_name "
    "FROM employees e "
    "LEFT JOIN health_units h ON h.unit_id = e.unit_id "
    "LEFT JOIN job_titles t ON t.title_id = e.job_title_id "
    "LEFT JOIN users u ON u.user_id = e.assigned_user_id "
)


# ---------------------------------------------------------------------------
# النطاق
# ---------------------------------------------------------------------------
def scope_sql(user: dict) -> tuple[str, tuple]:
    """شرط SQL يقيّد الموظفين المرئيين للمستخدم."""
    permissions = user.get("permissions") or []
    if "manage_units" in permissions:
        return "", ()
    if user.get("role") == "unit_manager":
        return " AND e.unit_id=?", (user.get("unit_id") or "",)
    return " AND e.assigned_user_id=?", (user.get("user_id") or "",)


def _visible(db, user: dict, employee_id: str) -> dict:
    clause, args = scope_sql(user)
    row = db.one(_QUERY + "WHERE e.employee_id=? AND e.deleted_at IS NULL" + clause,
                 (employee_id, *args))
    if not row:
        raise not_found("الموظف غير موجود أو خارج نطاقك.")
    return row


# ---------------------------------------------------------------------------
# قراءة
# ---------------------------------------------------------------------------
def list_employees(db, user: dict, search: str = "", unit_id: str = "",
                   limit: int = 1000) -> list[dict]:
    clause, args = scope_sql(user)
    where = ["e.deleted_at IS NULL"]
    params: list = list(args)
    if search.strip():
        where.append("(e.full_name LIKE ? OR e.emp_no LIKE ?)")
        like = f"%{search.strip()}%"
        params.extend([like, like])
    if unit_id:
        where.append("e.unit_id=?")
        params.append(unit_id)
    sql = (_QUERY + "WHERE " + " AND ".join(where) + clause +
           " ORDER BY e.full_name LIMIT ?")
    params.append(int(limit))
    rows = db.query(sql, tuple(params))
    for row in rows:
        row["status_label"] = STATUSES.get(row["status"], row["status"])
        row["gender_label"] = GENDERS.get(row["gender"], row["gender"])
    return rows


def get_employee(db, user: dict, employee_id: str) -> dict:
    row = _visible(db, user, employee_id)
    row["history"] = history(db, user, employee_id)
    row["documents"] = db.query(
        "SELECT d.*, l.link_id, l.purpose FROM document_links l "
        "JOIN documents d ON d.document_id = l.document_id "
        "WHERE l.entity_type='employee' AND l.entity_id=? ORDER BY d.uploaded_at DESC",
        (employee_id,))
    return row


def history(db, user: dict, employee_id: str) -> list[dict]:
    _visible(db, user, employee_id)
    return db.query(
        "SELECT * FROM employee_history WHERE employee_id=? ORDER BY effective_date DESC, "
        "created_at DESC", (employee_id,))


def stats(db, user: dict) -> dict:
    clause, args = scope_sql(user)
    row = db.one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN e.status='active' THEN 1 ELSE 0 END) AS active, "
        "SUM(CASE WHEN e.assigned_user_id IS NULL OR e.assigned_user_id='' THEN 1 ELSE 0 END) "
        "AS unassigned FROM employees e WHERE e.deleted_at IS NULL" + clause, args)
    return {key: int(value or 0) for key, value in (row or {}).items()}


def assignment_summary(db, unit_id: str) -> list[dict]:
    return db.query(
        "SELECT u.user_id, u.username, u.display_name, "
        "COUNT(e.employee_id) AS employees FROM users u "
        "LEFT JOIN employees e ON e.assigned_user_id=u.user_id AND e.deleted_at IS NULL "
        "WHERE u.unit_id=? GROUP BY u.user_id ORDER BY u.username", (unit_id,))


# ---------------------------------------------------------------------------
# عناوين وظيفية
# ---------------------------------------------------------------------------
def list_titles(db, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM job_titles"
    if active_only:
        sql += " WHERE active=1"
    return db.query(sql + " ORDER BY name")


def create_title(db, data: dict, user: dict | None = None, ip: str = "") -> dict:
    code = str(data.get("code") or "").strip().upper()
    name = str(data.get("name") or "").strip()
    if not code or not name:
        raise validation("رمز العنوان واسمه مطلوبان.")
    if db.one("SELECT 1 FROM job_titles WHERE code=? OR name=?", (code, name)):
        raise conflict("يوجد عنوان وظيفي بالرمز أو الاسم نفسه.")
    title_id = uuid.uuid4().hex
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "INSERT INTO job_titles(title_id, code, name, grade, active, created_at, updated_at) "
            "VALUES (?,?,?,?,1,?,?)",
            (title_id, code, name, str(data.get("grade") or "").strip(), stamp, stamp))
        audit.log(db, user, "إضافة عنوان وظيفي", "job_titles", title_id, f"{name} ({code})",
                  ip=ip, conn=conn)
    return db.one("SELECT * FROM job_titles WHERE title_id=?", (title_id,))  # type: ignore


def update_title(db, title_id: str, data: dict, user: dict | None = None,
                 ip: str = "") -> dict:
    current = db.one("SELECT * FROM job_titles WHERE title_id=?", (title_id,))
    if not current:
        raise not_found("العنوان الوظيفي غير موجود.")
    code = str(data.get("code", current["code"]) or "").strip().upper()
    name = str(data.get("name", current["name"]) or "").strip()
    if db.one("SELECT 1 FROM job_titles WHERE (code=? OR name=?) AND title_id<>?",
              (code, name, title_id)):
        raise conflict("يوجد عنوان آخر بالرمز أو الاسم نفسه.")
    with db.write() as conn:
        conn.execute("UPDATE job_titles SET code=?, name=?, grade=?, active=?, updated_at=? "
                     "WHERE title_id=?", (code, name, str(data.get("grade") or "").strip(),
                                          1 if data.get("active", True) else 0,
                                          now_iso(), title_id))
        audit.log(db, user, "تعديل عنوان وظيفي", "job_titles", title_id, name, ip=ip, conn=conn)
    return db.one("SELECT * FROM job_titles WHERE title_id=?", (title_id,))  # type: ignore


# ---------------------------------------------------------------------------
# كتابة
# ---------------------------------------------------------------------------
def _clean_date(value, label: str, required: bool = False) -> str:
    text = X.normalize_date(value)
    if not text:
        if required:
            raise validation(f"{label} مطلوب.")
        return ""
    if len(text) < 10:
        raise validation(f"{label} غير صالح ({text}).")
    return text[:10]


def _unit_for(db, user: dict, data: dict) -> str:
    unit_id = str(data.get("unit_id") or "").strip()
    if user.get("role") in {"unit_manager", "unit_editor"}:
        if not user.get("unit_id"):
            raise validation("حسابك غير مرتبط بمؤسسة.")
        return user["unit_id"]
    if not unit_id:
        raise validation("اختر المؤسسة.")
    if not db.one("SELECT 1 FROM health_units WHERE unit_id=? AND deleted_at IS NULL", (unit_id,)):
        raise validation("المؤسسة غير موجودة.")
    return unit_id


def _title(db, title_id: str) -> str:
    title_id = str(title_id or "").strip()
    if not title_id or not db.one("SELECT 1 FROM job_titles WHERE title_id=?", (title_id,)):
        raise validation("اختر عنواناً وظيفياً صحيحاً.")
    return title_id


def _gender(value) -> str:
    text = str(value or "").strip().lower()
    if text in {"male", "ذكر", "m"}:
        return "male"
    if text in {"female", "أنثى", "انثى", "f"}:
        return "female"
    raise validation("الجنس مطلوب (ذكر/أنثى).")


def _status(value) -> str:
    text = str(value or "").strip()
    if text in STATUSES:
        return text
    for code, label in STATUSES.items():
        if text == label:
            return code
    raise validation("الحالة غير معروفة.")


def _assignee(db, unit_id: str, user_id: str) -> str:
    user_id = str(user_id or "").strip()
    if not user_id:
        return ""
    row = db.one("SELECT user_id, unit_id, role, active FROM users WHERE user_id=?", (user_id,))
    if not row or not row["active"]:
        raise validation("المستخدم المسؤول غير موجود أو معطّل.")
    if row["unit_id"] != unit_id:
        raise validation("المستخدم المسؤول لا يتبع المؤسسة نفسها.")
    if row["role"] not in {"unit_editor", "center_editor"}:
        raise validation("التوزيع يكون على مدخلي البيانات فقط.")
    return user_id


def _unique_emp_no(db, unit_id: str, emp_no: str, current_id: str = "") -> None:
    row = db.one("SELECT employee_id FROM employees WHERE lower(emp_no)=lower(?) "
                 "AND unit_id=? AND deleted_at IS NULL AND employee_id<>?",
                 (emp_no, unit_id, current_id))
    if row:
        raise conflict("الرقم الوظيفي مستخدم مسبقاً في هذه المؤسسة.")


def create_employee(db, user: dict, data: dict, ip: str = "") -> dict:
    unit_id = _unit_for(db, user, data)
    emp_no = str(data.get("emp_no") or "").strip()
    full_name = str(data.get("full_name") or "").strip()
    if not emp_no:
        raise validation("الرقم الوظيفي مطلوب.")
    if not full_name:
        raise validation("اسم الموظف مطلوب.")
    _unique_emp_no(db, unit_id, emp_no)
    hire_date = _clean_date(data.get("hire_date"), "تاريخ المباشرة", required=True)
    if hire_date > today_iso():
        raise validation("تاريخ المباشرة لا يكون في المستقبل.")
    end_date = _clean_date(data.get("end_date"), "تاريخ انتهاء الخدمة")
    if end_date and end_date < hire_date:
        raise validation("تاريخ الانتهاء قبل تاريخ المباشرة.")
    assigned = ""
    if user.get("role") in {"unit_editor", "center_editor"}:
        assigned = user.get("user_id") or ""
    elif data.get("assigned_user_id"):
        assigned = _assignee(db, unit_id, data.get("assigned_user_id"))
    last_grade = _clean_date(data.get("last_grade_date") or hire_date, "تاريخ الدرجة الحالية")
    last_stage = _clean_date(data.get("last_stage_date") or hire_date, "تاريخ المرحلة الحالية")
    if last_grade < hire_date:
        last_grade = hire_date
    if last_stage < hire_date:
        last_stage = hire_date

    employee_id = uuid.uuid4().hex
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "INSERT INTO employees(employee_id, emp_no, full_name, unit_id, job_title_id, grade, "
            "stage, category, hire_date, end_date, gender, status, notes, assigned_user_id, "
            "last_grade_date, last_stage_date, version, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (employee_id, emp_no, full_name, unit_id, _title(db, data.get("job_title_id")),
             str(data.get("grade") or "").strip(), str(data.get("stage") or "").strip(),
             str(data.get("category") or "").strip(), hire_date, end_date or None,
             _gender(data.get("gender")), _status(data.get("status") or "active"),
             str(data.get("notes") or "").strip(), assigned or None, last_grade, last_stage,
             stamp, stamp))
        conn.execute(
            "INSERT INTO employee_history(history_id, employee_id, event_type, effective_date, "
            "old_value, new_value, order_no, note, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, employee_id, "تعيين", hire_date, "", f"{full_name} / {emp_no}",
             str(data.get("order_no") or "").strip(), "إدخال الموظف", user.get("username", ""),
             stamp))
        audit.log(db, user, "إضافة موظف", "employees", employee_id, f"{full_name} ({emp_no})",
                  ip=ip, conn=conn)
    return get_employee(db, user, employee_id)


def update_employee(db, user: dict, employee_id: str, data: dict, ip: str = "") -> dict:
    current = _visible(db, user, employee_id)
    expected = int(data.get("version") or current["version"])
    if expected != int(current["version"]):
        raise conflict("عُدّل السجل من مستخدم آخر. أعد تحميله ثم حاول مجدداً.")
    unit_id = _unit_for(db, user, {"unit_id": data.get("unit_id") or current["unit_id"]})
    if unit_id != current["unit_id"] and "assign_employees" not in (user.get("permissions") or []):
        raise forbidden("نقل الموظف بين المؤسسات يتطلب صلاحية التوزيع/النقل.")
    emp_no = str(data.get("emp_no", current["emp_no"]) or "").strip()
    full_name = str(data.get("full_name", current["full_name"]) or "").strip()
    if not emp_no or not full_name:
        raise validation("الرقم الوظيفي والاسم مطلوبان.")
    _unique_emp_no(db, unit_id, emp_no, employee_id)
    hire_date = _clean_date(data.get("hire_date", current["hire_date"]), "تاريخ المباشرة",
                            required=True)
    end_date = _clean_date(data.get("end_date", current["end_date"] or ""),
                           "تاريخ انتهاء الخدمة")
    if end_date and end_date < hire_date:
        raise validation("تاريخ الانتهاء قبل تاريخ المباشرة.")
    title_id = _title(db, data.get("job_title_id") or current["job_title_id"])
    grade = str(data.get("grade", current["grade"]) or "").strip()
    stage = str(data.get("stage", current["stage"]) or "").strip()
    status = _status(data.get("status", current["status"]))
    assigned = current["assigned_user_id"] or ""
    if "assign_employees" in (user.get("permissions") or []) and "assigned_user_id" in data:
        assigned = _assignee(db, unit_id, data.get("assigned_user_id") or "")
    effective = str(data.get("history_date") or today_iso())[:10]
    last_grade = _clean_date(
        data.get("last_grade_date")
        or (effective if grade != current["grade"]
            else (current.get("last_grade_date") or hire_date)),
        "تاريخ الدرجة الحالية")
    last_stage = _clean_date(
        data.get("last_stage_date")
        or (effective if stage != current["stage"]
            else (current.get("last_stage_date") or hire_date)),
        "تاريخ المرحلة الحالية")
    if last_grade < hire_date:
        last_grade = hire_date
    if last_stage < hire_date:
        last_stage = hire_date

    changes = [
        ("transfer" if unit_id != current["unit_id"] else "", "unit", current["unit_id"],
         unit_id, "نقل مؤسسة"),
        ("title", "job_title_id", current["job_title_id"], title_id, "تغيير عنوان وظيفي"),
        ("grade", "grade", current["grade"], grade, "تغيير درجة"),
        ("stage", "stage", current["stage"], stage, "تغيير مرحلة"),
        ("end", "end_date", current["end_date"] or "", end_date, "تغيير حالة الخدمة"),
    ]
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "UPDATE employees SET emp_no=?, full_name=?, unit_id=?, job_title_id=?, grade=?, "
            "stage=?, category=?, hire_date=?, end_date=?, gender=?, status=?, notes=?, "
            "assigned_user_id=?, last_grade_date=?, last_stage_date=?, version=version+1, "
            "updated_at=? WHERE employee_id=?",
            (emp_no, full_name, unit_id, title_id, grade,
             stage, str(data.get("category", current["category"]) or "").strip(),
             hire_date, end_date or None, _gender(data.get("gender", current["gender"])),
             status, str(data.get("notes", current["notes"]) or "").strip(), assigned or None,
             last_grade, last_stage, stamp, employee_id))
        for event_type, _key, old, new, label in changes:
            if event_type and str(old or "") != str(new or ""):
                conn.execute(
                    "INSERT INTO employee_history(history_id, employee_id, event_type, "
                    "effective_date, old_value, new_value, order_no, note, created_by, "
                    "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, employee_id, event_type, effective, str(old or ""),
                     str(new or ""), str(data.get("order_no") or "").strip(), label,
                     user.get("username", ""), stamp))
        audit.log(db, user, "تعديل موظف", "employees", employee_id,
                  f"{full_name} ({emp_no})", ip=ip, conn=conn)
    return get_employee(db, user, employee_id)


def archive_employee(db, user: dict, employee_id: str, reason: str = "",
                     ip: str = "") -> dict:
    current = _visible(db, user, employee_id)
    with db.write() as conn:
        conn.execute("UPDATE employees SET deleted_at=?, updated_at=? WHERE employee_id=?",
                     (now_iso(), now_iso(), employee_id))
        conn.execute(
            "INSERT INTO employee_history(history_id, employee_id, event_type, effective_date, "
            "old_value, new_value, order_no, note, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, employee_id, "archive", today_iso(), "", reason or "أرشفة",
             "", "", user.get("username", ""), now_iso()))
        audit.log(db, user, "أرشفة موظف", "employees", employee_id,
                  f"{current['full_name']} — {reason}", ip=ip, conn=conn)
    return {"archived": current["full_name"]}


# ---------------------------------------------------------------------------
# التوزيع
# ---------------------------------------------------------------------------
def assign_employees(db, user: dict, employee_ids: list[str], target_user_id: str,
                     ip: str = "") -> dict:
    if not employee_ids:
        raise validation("اختر موظفاً واحداً على الأقل.")
    target = db.one("SELECT * FROM users WHERE user_id=?", (target_user_id,))
    if not target or not target["active"]:
        raise validation("المستخدم الهدف غير موجود أو معطّل.")
    if target["role"] not in {"unit_editor", "center_editor"}:
        raise validation("التوزيع يكون على مدخلي البيانات فقط.")
    assigned = 0
    with db.write() as conn:
        for employee_id in employee_ids:
            row = db.one("SELECT employee_id, unit_id, full_name FROM employees "
                         "WHERE employee_id=? AND deleted_at IS NULL", (employee_id,))
            if not row:
                continue
            if target["unit_id"] != row["unit_id"]:
                raise validation(f"الموظف {row['full_name']} لا يتبع مؤسسة المستخدم الهدف.")
            conn.execute("UPDATE employees SET assigned_user_id=?, updated_at=? "
                         "WHERE employee_id=?", (target_user_id, now_iso(), employee_id))
            assigned += 1
        audit.log(db, user, "توزيع موظفين", "users", target_user_id,
                  f"{assigned} موظف إلى {target['username']}", ip=ip, conn=conn)
    return {"assigned": assigned, "target": target["username"]}


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def export_excel(db, user: dict, path: str | Path) -> Path:
    employees = list_employees(db, user, limit=100000)
    return X.export_employees(path, employees)


def template_excel(path: str | Path) -> Path:
    return X.employee_template(path)


def import_excel(db, user: dict, path: str | Path, *, update_existing: bool = True,
                 assigned_user_id: str = "", ip: str = "") -> dict:
    headers, raw_rows = X.read_table(path)
    mapping = X.guess_mapping(headers)
    if not mapping.get("emp_no") or not mapping.get("full_name"):
        raise validation("الملف لا يحوي عمودي «الرقم الوظيفي» و«الاسم».")
    units = {row["name"]: row["unit_id"] for row in
             db.query("SELECT unit_id, name FROM health_units WHERE deleted_at IS NULL")}
    units.update({row["code"].upper(): row["unit_id"] for row in
                  db.query("SELECT unit_id, code FROM health_units WHERE deleted_at IS NULL")})
    titles = {row["name"]: row["title_id"] for row in db.query("SELECT title_id, name FROM job_titles")}
    titles.update({row["code"].upper(): row["title_id"] for row in
                   db.query("SELECT title_id, code FROM job_titles")})
    usernames = {row["username"].lower(): row["user_id"] for row in
                 db.query("SELECT user_id, username FROM users")}
    result = {"added": 0, "updated": 0, "skipped": 0, "errors": []}
    default_unit = user.get("unit_id") or ""
    stamp = now_iso()
    with db.write() as conn:
        for index, raw in enumerate(raw_rows, start=2):
            try:
                emp_no = X.row_value(raw, mapping, "emp_no")
                full_name = X.row_value(raw, mapping, "full_name")
                if not emp_no or not full_name:
                    raise ValueError("الرقم الوظيفي أو الاسم فارغ")
                unit_text = X.row_value(raw, mapping, "unit")
                unit_id = default_unit or units.get(unit_text) or units.get(unit_text.upper())
                if not unit_id:
                    raise ValueError(f"المؤسسة غير معروفة: {unit_text or '—'}")
                title_text = X.row_value(raw, mapping, "job_title")
                title_id = titles.get(title_text) or titles.get(title_text.upper())
                if not title_id:
                    raise ValueError(f"العنوان الوظيفي غير معروف: {title_text or '—'}")
                hire_date = X.normalize_date(X.row_value(raw, mapping, "hire_date"))
                if not hire_date:
                    raise ValueError("تاريخ المباشرة مطلوب")
                last_grade = X.normalize_date(
                    X.row_value(raw, mapping, "last_grade_date")) or hire_date
                last_stage = X.normalize_date(
                    X.row_value(raw, mapping, "last_stage_date")) or hire_date
                gender_text = X.row_value(raw, mapping, "gender")
                gender = "female" if gender_text in {"أنثى", "انثى", "female", "f"} else "male"
                status_text = X.row_value(raw, mapping, "status") or "على الملاك"
                status = status_text if status_text in STATUSES else next(
                    (code for code, label in STATUSES.items() if label == status_text), "active")
                assigned = assigned_user_id
                assigned_text = X.row_value(raw, mapping, "assigned")
                if assigned_text:
                    assigned = usernames.get(assigned_text.lower(), assigned)
                existing = conn.execute(
                    "SELECT employee_id, version FROM employees WHERE lower(emp_no)=lower(?) "
                    "AND unit_id=? AND deleted_at IS NULL", (emp_no, unit_id)).fetchone()
                if existing and not update_existing:
                    result["skipped"] += 1
                    continue
                if existing:
                    conn.execute(
                        "UPDATE employees SET full_name=?, job_title_id=?, grade=?, stage=?, "
                        "category=?, hire_date=?, end_date=?, gender=?, status=?, notes=?, "
                        "assigned_user_id=COALESCE(NULLIF(?,''), assigned_user_id), "
                        "last_grade_date=?, last_stage_date=?, version=version+1, updated_at=? "
                        "WHERE employee_id=?",
                        (full_name, title_id, X.row_value(raw, mapping, "grade"),
                         X.row_value(raw, mapping, "stage"),
                         X.row_value(raw, mapping, "category"), hire_date,
                         X.normalize_date(X.row_value(raw, mapping, "end_date")) or None,
                         gender, status, X.row_value(raw, mapping, "notes"), assigned,
                         last_grade, last_stage, stamp, existing["employee_id"]))
                    result["updated"] += 1
                else:
                    employee_id = uuid.uuid4().hex
                    conn.execute(
                        "INSERT INTO employees(employee_id, emp_no, full_name, unit_id, "
                        "job_title_id, grade, stage, category, hire_date, end_date, gender, "
                        "status, notes, assigned_user_id, last_grade_date, last_stage_date, "
                        "version, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                        (employee_id, emp_no, full_name, unit_id, title_id,
                         X.row_value(raw, mapping, "grade"), X.row_value(raw, mapping, "stage"),
                         X.row_value(raw, mapping, "category"), hire_date,
                         X.normalize_date(X.row_value(raw, mapping, "end_date")) or None,
                         gender, status, X.row_value(raw, mapping, "notes"),
                         (assigned or (user.get("user_id") if user.get("role") in
                                       {"unit_editor", "center_editor"} else "")) or None,
                         last_grade, last_stage, stamp, stamp))
                    conn.execute(
                        "INSERT INTO employee_history(history_id, employee_id, event_type, "
                        "effective_date, old_value, new_value, order_no, note, created_by, "
                        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, employee_id, "تعيين", hire_date, "",
                         f"{full_name} / {emp_no}", "", "استيراد Excel",
                         user.get("username", ""), stamp))
                    result["added"] += 1
            except Exception as exc:  # noqa: BLE001 - تُجمع أخطاء الصفوف
                result["skipped"] += 1
                result["errors"].append(f"صف {index}: {exc}")
        audit.log(db, user, "استيراد موظفين", "employees", "",
                  f"أُضيف {result['added']}، حُدّث {result['updated']}، "
                  f"تُخطي {result['skipped']}", ip=ip, conn=conn)
    return result
