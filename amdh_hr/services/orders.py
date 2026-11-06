"""أوامر الترفيع والعلاوة (فردية وجماعية) وربط المستفيدين."""

from __future__ import annotations

import uuid

from ..errors import conflict, forbidden, not_found, validation
from ..util import as_date, now_iso, today_iso
from . import audit, employees as E

ORDER_TYPES = {"promotion": "ترفيع", "increment": "علاوة", "other": "أخرى"}
STATUS_LABELS = {"draft": "مسودة", "approved": "معتمد", "cancelled": "ملغى"}
APPLY_MODES = {"auto": "تلقائي (التالي)", "fixed": "قيم محددة"}


def list_orders(db, user: dict, limit: int = 500) -> list[dict]:
    permissions = user.get("permissions") or []
    where = ["o.deleted_at IS NULL"]
    args: list = []
    if "manage_units" not in permissions:
        where.append("o.unit_id=?")
        args.append(user.get("unit_id") or "")
    rows = db.query(
        "SELECT o.*, h.name AS unit_name, "
        "(SELECT COUNT(*) FROM hr_order_recipients r WHERE r.order_id=o.order_id) "
        "AS recipients_count FROM hr_orders o LEFT JOIN health_units h ON h.unit_id=o.unit_id "
        "WHERE " + " AND ".join(where) + " ORDER BY o.order_date DESC, o.created_at DESC LIMIT ?",
        (*args, limit))
    for row in rows:
        row["type_label"] = ORDER_TYPES.get(row["order_type"], row["order_type"])
        row["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
    return rows


def get_order(db, user: dict, order_id: str) -> dict:
    order = db.one("SELECT * FROM hr_orders WHERE order_id=? AND deleted_at IS NULL", (order_id,))
    if not order:
        raise not_found("الأمر غير موجود.")
    if "manage_units" not in (user.get("permissions") or []):
        if order["unit_id"] != (user.get("unit_id") or ""):
            raise forbidden("الأمر خارج نطاق مؤسستك.")
    order["type_label"] = ORDER_TYPES.get(order["order_type"], order["order_type"])
    order["status_label"] = STATUS_LABELS.get(order["status"], order["status"])
    order["recipients"] = db.query(
        "SELECT r.*, e.emp_no, e.full_name, h.name AS unit_name FROM hr_order_recipients r "
        "JOIN employees e ON e.employee_id=r.employee_id "
        "LEFT JOIN health_units h ON h.unit_id=e.unit_id "
        "WHERE r.order_id=? ORDER BY e.full_name", (order_id,))
    order["documents"] = db.query(
        "SELECT d.*, l.link_id, l.purpose FROM document_links l "
        "JOIN documents d ON d.document_id=l.document_id "
        "WHERE l.entity_type='order' AND l.entity_id=? ORDER BY d.uploaded_at DESC",
        (order_id,))
    return order


def create_order(db, user: dict, data: dict, ip: str = "") -> dict:
    order_type = str(data.get("order_type") or "")
    if order_type not in ORDER_TYPES:
        raise validation("نوع الأمر غير معروف.")
    order_no = str(data.get("order_no") or "").strip()
    order_date = str(data.get("order_date") or today_iso())[:10]
    effective = str(data.get("effective_date") or order_date)[:10]
    if not order_no:
        raise validation("رقم الأمر مطلوب.")
    if as_date(order_date) is None or as_date(effective) is None:
        raise validation("تاريخ الأمر أو تاريخ السريان غير صالح.")
    apply_mode = str(data.get("apply_mode") or "auto")
    if apply_mode not in APPLY_MODES:
        raise validation("طريقة التطبيق غير معروفة.")
    to_grade = str(data.get("to_grade") or "").strip()
    to_stage = str(data.get("to_stage") or "").strip()
    if order_type == "promotion" and apply_mode == "fixed" and not to_grade:
        raise validation("حدّد الدرجة المستهدفة للأمر الثابت.")
    if order_type == "increment" and apply_mode == "fixed" and not to_stage:
        raise validation("حدّد المرحلة المستهدفة للأمر الثابت.")
    employee_ids = [str(item) for item in (data.get("employee_ids") or [])]
    if not employee_ids:
        raise validation("اختر موظفاً واحداً على الأقل.")

    unit_id = str(data.get("unit_id") or "")
    if user.get("role") in {"unit_manager", "unit_editor"}:
        unit_id = user.get("unit_id") or ""
    clause, args = E.scope_sql(user)
    placeholders = ",".join("?" for _ in employee_ids)
    visible = {row["employee_id"] for row in db.query(
        "SELECT e.employee_id FROM employees e WHERE e.employee_id IN (" + placeholders + ") "
        "AND e.deleted_at IS NULL" + clause, (*employee_ids, *args))}
    missing = [item for item in employee_ids if item not in visible]
    if missing:
        raise validation(f"{len(missing)} موظفاً خارج نطاقك أو غير موجود.")
    if unit_id:
        units = {row["unit_id"] for row in db.query(
            "SELECT unit_id FROM employees WHERE employee_id IN (" + placeholders + ")",
            tuple(employee_ids))}
        if len(units) > 1:
            raise validation("الأمر الجماعي يجب أن يكون داخل مؤسسة واحدة.")
    else:
        units = {row["unit_id"] for row in db.query(
            "SELECT unit_id FROM employees WHERE employee_id IN (" + placeholders + ")",
            tuple(employee_ids))}
        if len(units) == 1:
            unit_id = next(iter(units)) or ""

    order_id = uuid.uuid4().hex
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "INSERT INTO hr_orders(order_id, unit_id, order_type, order_no, order_date, issuer, "
            "effective_date, status, notes, created_by, created_at, updated_at, apply_mode, "
            "to_grade, to_stage) VALUES (?,?,?,?,?,?,?,'draft',?,?,?,?,?,?,?)",
            (order_id, unit_id or None, order_type, order_no, order_date,
             str(data.get("issuer") or "").strip(), effective,
             str(data.get("notes") or "").strip(), user.get("username", ""), stamp, stamp,
             apply_mode, to_grade, to_stage))
        conn.executemany("INSERT INTO hr_order_recipients(order_id, employee_id, note) "
                         "VALUES (?,?,?)",
                         [(order_id, employee_id, "") for employee_id in employee_ids])
        audit.log(db, user, "إضافة أمر", "hr_orders", order_id,
                  f"{ORDER_TYPES[order_type]} {order_no} — {len(employee_ids)} موظف",
                  ip=ip, conn=conn)
    return get_order(db, user, order_id)


def _next_number(value, label: str, employee: dict) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        raise validation(
            f"{label} للموظف «{employee.get('full_name')}» غير رقمي ({text or 'فارغ'})؛ "
            "استخدم طريقة «قيم محددة» بدلاً من التلقائي.")
    return str(int(text) + 1)


def _target(order: dict, employee: dict) -> tuple[str, str]:
    order_type = order["order_type"]
    mode = order.get("apply_mode") or "auto"
    if order_type == "promotion":
        if mode == "fixed":
            grade = str(order.get("to_grade") or "").strip()
            if not grade:
                raise validation("الأمر لا يحمل درجة مستهدفة.")
        else:
            grade = _next_number(employee.get("grade"), "الدرجة", employee)
        stage = str(order.get("to_stage") or "").strip() or "1"
        return grade, stage
    if order_type == "increment":
        grade = str(order.get("to_grade") or employee.get("grade") or "").strip()
        if mode == "fixed":
            stage = str(order.get("to_stage") or "").strip()
            if not stage:
                raise validation("الأمر لا يحمل مرحلة مستهدفة.")
        else:
            stage = _next_number(employee.get("stage"), "المرحلة", employee)
        return grade, stage
    return str(employee.get("grade") or ""), str(employee.get("stage") or "")


def apply_order_effects(db, order: dict, user: dict, conn=None, ip: str = "") -> int:
    """يطبّق نتيجة الأمر على درجات/مراحل المستفيدين ويسجّل التاريخ."""
    if order.get("applied_at"):
        return 0
    if order.get("order_type") not in {"promotion", "increment"}:
        _mark_applied(db, order["order_id"], conn)
        return 0
    recipients = db.query(
        "SELECT e.* FROM hr_order_recipients r JOIN employees e ON e.employee_id=r.employee_id "
        "WHERE r.order_id=? AND e.deleted_at IS NULL", (order["order_id"],))
    targets: list[tuple[dict, str, str]] = []
    for employee in recipients:
        grade, stage = _target(order, employee)
        targets.append((employee, grade, stage))

    def _apply(connection) -> int:
        changed = 0
        for employee, grade, stage in targets:
            old_grade = str(employee.get("grade") or "")
            old_stage = str(employee.get("stage") or "")
            if old_grade == grade and old_stage == stage:
                continue
            effective = order.get("effective_date") or today_iso()
            if order["order_type"] == "promotion":
                connection.execute(
                    "UPDATE employees SET grade=?, stage=?, last_grade_date=?, "
                    "last_stage_date=?, version=version+1, updated_at=? WHERE employee_id=?",
                    (grade, stage, effective, effective, now_iso(), employee["employee_id"]))
            else:
                connection.execute(
                    "UPDATE employees SET grade=?, stage=?, last_stage_date=?, "
                    "version=version+1, updated_at=? WHERE employee_id=?",
                    (grade, stage, effective, now_iso(), employee["employee_id"]))
            connection.execute(
                "INSERT INTO employee_history(history_id, employee_id, event_type, "
                "effective_date, old_value, new_value, order_no, note, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, employee["employee_id"], order["order_type"],
                 effective,
                 f"{old_grade} / {old_stage}", f"{grade} / {stage}",
                 order.get("order_no", ""), "تطبيق نتيجة الأمر",
                 user.get("username", ""), now_iso()))
            changed += 1
        connection.execute("UPDATE hr_orders SET applied_at=? WHERE order_id=?",
                           (now_iso(), order["order_id"]))
        if changed:
            audit.log(db, user, "تطبيق أمر على الموظفين", "hr_orders", order["order_id"],
                      f"{order.get('order_no', '')} — {changed} موظف", ip=ip, conn=connection)
        return changed

    if conn is not None:
        return _apply(conn)
    with db.write() as connection:
        return _apply(connection)


def _mark_applied(db, order_id: str, conn=None) -> None:
    if conn is not None:
        conn.execute("UPDATE hr_orders SET applied_at=? WHERE order_id=?", (now_iso(), order_id))
    else:
        with db.write() as connection:
            connection.execute("UPDATE hr_orders SET applied_at=? WHERE order_id=?",
                               (now_iso(), order_id))


def approve_order(db, user: dict, order_id: str, ip: str = "") -> dict:
    order = get_order(db, user, order_id)
    if order["status"] == "approved":
        return order
    with db.write() as conn:
        conn.execute("UPDATE hr_orders SET status='approved', updated_at=? WHERE order_id=?",
                     (now_iso(), order_id))
        order["status"] = "approved"
        applied = apply_order_effects(db, order, user, conn=conn, ip=ip)
        audit.log(db, user, "اعتماد أمر", "hr_orders", order_id,
                  f"{order['order_no']} — طُبّق على {applied} موظف", ip=ip, conn=conn)
    return get_order(db, user, order_id)


def delete_order(db, user: dict, order_id: str, ip: str = "") -> dict:
    order = get_order(db, user, order_id)
    if order["status"] == "approved":
        raise conflict("لا يُحذف أمر معتمد.")
    with db.write() as conn:
        conn.execute("UPDATE hr_orders SET deleted_at=? WHERE order_id=?",
                     (now_iso(), order_id))
        audit.log(db, user, "حذف أمر", "hr_orders", order_id, order["order_no"],
                  ip=ip, conn=conn)
    return {"deleted": order_id}
