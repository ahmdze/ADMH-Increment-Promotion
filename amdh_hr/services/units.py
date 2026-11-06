"""إدارة المؤسسات: إنشاء، تعديل، حذف، وتوليد مستخدميها تلقائياً."""

from __future__ import annotations

import re
import uuid

from .. import permissions as P
from .. import security as sec
from ..config import MAX_EDITORS, MAX_UNIT_USERS, UNIT_KINDS
from ..errors import conflict, not_found, validation
from ..util import now_iso, safe_filename, slugify
from . import audit

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,15}$")


# ---------------------------------------------------------------------------
# قراءة
# ---------------------------------------------------------------------------
def _base_query() -> str:
    return ("SELECT h.*, "
            "(SELECT COUNT(*) FROM users u WHERE u.unit_id = h.unit_id) AS users_count "
            "FROM health_units h ")


def list_units(db, include_deleted: bool = False) -> list[dict]:
    where = "" if include_deleted else "WHERE h.deleted_at IS NULL"
    rows = db.query(_base_query() + where + " ORDER BY h.is_center DESC, h.name")
    for row in rows:
        row["is_center"] = bool(row["is_center"])
        row["active"] = bool(row["active"])
        row["employees_count"] = db.count("employees", "unit_id=? AND deleted_at IS NULL",
                                          (row["unit_id"],))
        row["manager_user"] = db.scalar(
            "SELECT display_name FROM users WHERE unit_id=? AND role='unit_manager' "
            "ORDER BY created_at LIMIT 1", (row["unit_id"],), "")
    return rows


def get_unit(db, unit_id: str) -> dict | None:
    row = db.one(_base_query() + "WHERE h.unit_id=?", (unit_id,))
    if row:
        row["is_center"] = bool(row["is_center"])
        row["active"] = bool(row["active"])
        row["employees_count"] = db.count("employees", "unit_id=? AND deleted_at IS NULL",
                                          (unit_id,))
    return row


def center_unit(db) -> dict | None:
    row = db.one(_base_query() + "WHERE h.is_center=1 AND h.deleted_at IS NULL LIMIT 1")
    if row:
        row["is_center"] = True
        row["active"] = bool(row["active"])
    return row


def unit_users(db, unit_id: str) -> list[dict]:
    rows = db.query(
        "SELECT user_id, username, display_name, role, active, last_login, must_change "
        "FROM users WHERE unit_id=? ORDER BY role, created_at", (unit_id,))
    for row in rows:
        row["role_label"] = P.ROLE_LABELS.get(row["role"], row["role"])
        row["active"] = bool(row["active"])
    return rows


# ---------------------------------------------------------------------------
# تحقق
# ---------------------------------------------------------------------------
def _clean_name(db, name: str, current_id: str = "") -> str:
    name = str(name or "").strip()
    if len(name) < 2:
        raise validation("اسم المؤسسة مطلوب (حرفان على الأقل).")
    existing = db.one("SELECT unit_id FROM health_units WHERE name=? AND unit_id<>?",
                      (name, current_id))
    if existing:
        raise conflict("يوجد مؤسسة أخرى بالاسم نفسه.")
    return name


def _clean_code(db, code: str, name: str, current_id: str = "") -> str:
    code = slugify(code or name, "unit").upper()[:16]
    if not CODE_RE.match(code):
        code = ("U" + code)[:16]
    existing = db.one("SELECT unit_id FROM health_units WHERE code=? AND unit_id<>?",
                      (code, current_id))
    if existing:
        raise conflict(f"الرمز «{code}» مستخدم لمؤسسة أخرى.")
    return code


def _clean_kind(kind: str) -> str:
    kind = str(kind or "").strip()
    return kind if kind in UNIT_KINDS else "مؤسسة"


# ---------------------------------------------------------------------------
# كتابة
# ---------------------------------------------------------------------------
def create_unit(db, data: dict, editor_count: int = 1, create_manager: bool = True,
                operator: dict | None = None, ip: str = "") -> dict:
    name = _clean_name(db, data.get("name", ""))
    code = _clean_code(db, data.get("code", ""), name)
    kind = _clean_kind(data.get("kind"))
    is_center = bool(data.get("is_center"))
    if is_center and center_unit(db):
        raise conflict("مركز الدائرة مُعرَّف مسبقاً.")

    editor_count = int(editor_count or 1)
    if is_center:
        create_manager = False
    max_editors = MAX_UNIT_USERS if is_center else MAX_EDITORS
    if not 1 <= editor_count <= max_editors:
        raise validation(f"عدد مدخلي البيانات يجب أن يكون بين 1 و{max_editors}.")
    total_users = editor_count + (1 if create_manager else 0)
    if total_users > MAX_UNIT_USERS:
        raise validation(f"الحد الأقصى للحسابات في المؤسسة {MAX_UNIT_USERS}.")

    unit_id = uuid.uuid4().hex
    stamp = now_iso()
    parent_id = str(data.get("parent_id") or "") or None
    with db.write() as conn:
        conn.execute(
            "INSERT INTO health_units(unit_id, code, name, kind, parent_id, is_center, active, "
            "manager, phone, address, notes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (unit_id, code, name, kind, parent_id, 1 if is_center else 0,
             1 if data.get("active", True) else 0,
             str(data.get("manager") or "").strip(), str(data.get("phone") or "").strip(),
             str(data.get("address") or "").strip(), str(data.get("notes") or "").strip(),
             stamp, stamp))
        credentials = _create_unit_users(db, conn, unit_id, code, name, editor_count,
                                         create_manager, is_center)
        audit.log(db, operator, "إنشاء مؤسسة", "health_units", unit_id,
                  f"{name} ({code}) — {len(credentials)} حساب", ip=ip, conn=conn)
    return {"unit": get_unit(db, unit_id), "credentials": credentials}


def _first_free_username(db, base: str, busy: set[str]) -> str:
    candidate = base
    index = 2
    while candidate.lower() in busy or db.one(
            "SELECT 1 FROM users WHERE lower(username)=lower(?)", (candidate,)):
        candidate = f"{base}{index}"
        index += 1
    busy.add(candidate.lower())
    return candidate


def _create_unit_users(db, conn, unit_id: str, code: str, name: str, editor_count: int,
                       create_manager: bool, is_center: bool) -> list[dict]:
    base = slugify(code, "unit")
    busy: set[str] = set()
    passwords: set[str] = set()
    created: list[dict] = []
    stamp = now_iso()

    def add(role: str, username_base: str, display: str) -> None:
        username = _first_free_username(db, username_base, busy)
        password = sec.unique_password(passwords)
        passwords.add(password)
        password_hash, salt, iterations = sec.hash_password(password)
        conn.execute(
            "INSERT INTO users(user_id, username, display_name, role, unit_id, password_hash, "
            "salt, iterations, must_change, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,1,?,?)",
            (uuid.uuid4().hex, username, display, role, unit_id, password_hash, salt,
             iterations, stamp, stamp))
        created.append({"username": username, "password": password, "role": role,
                        "role_label": P.ROLE_LABELS.get(role, role), "display_name": display})

    if create_manager:
        add("unit_manager", f"{base}-m", f"مدير {name}")
    editor_role = "center_editor" if is_center else "unit_editor"
    for index in range(1, editor_count + 1):
        add(editor_role, f"{base}-{index}", f"{'مدخل مركز' if is_center else 'مدخل بيانات'} {index}")
    return created


def update_unit(db, unit_id: str, data: dict, operator: dict | None = None,
                ip: str = "") -> dict:
    current = get_unit(db, unit_id)
    if not current:
        raise not_found("المؤسسة غير موجودة.")
    name = _clean_name(db, data.get("name", current["name"]), unit_id)
    code = _clean_code(db, data.get("code", current["code"]), name, unit_id)
    with db.write() as conn:
        conn.execute(
            "UPDATE health_units SET name=?, code=?, kind=?, manager=?, phone=?, address=?, "
            "notes=?, active=?, updated_at=? WHERE unit_id=?",
            (name, code, _clean_kind(data.get("kind", current["kind"])),
             str(data.get("manager") or "").strip(), str(data.get("phone") or "").strip(),
             str(data.get("address") or "").strip(), str(data.get("notes") or "").strip(),
             1 if data.get("active", current["active"]) else 0, now_iso(), unit_id))
        audit.log(db, operator, "تعديل مؤسسة", "health_units", unit_id,
                  f"{current['name']} → {name} ({code})", ip=ip, conn=conn)
    return get_unit(db, unit_id)  # type: ignore[return-value]


def delete_unit(db, unit_id: str, operator: dict | None = None, ip: str = "") -> dict:
    unit = get_unit(db, unit_id)
    if not unit:
        raise not_found("المؤسسة غير موجودة.")
    if unit["is_center"]:
        raise validation("لا يمكن حذف مركز الدائرة.")
    if unit["employees_count"]:
        raise validation("لا يمكن حذف مؤسسة لها موظفون. انقل الموظفين أو عطّل المؤسسة.")
    usernames = [row["username"] for row in unit_users(db, unit_id)]
    with db.write() as conn:
        conn.execute("DELETE FROM users WHERE unit_id=?", (unit_id,))
        conn.execute("DELETE FROM health_units WHERE unit_id=?", (unit_id,))
        audit.log(db, operator, "حذف مؤسسة", "health_units", unit_id,
                  f"{unit['name']} ({unit['code']}) — حُذف {len(usernames)} حساب: "
                  + "، ".join(usernames), ip=ip, conn=conn)
    return {"deleted": unit["name"], "users_deleted": len(usernames), "usernames": usernames}


def reset_unit_users(db, unit_id: str, operator: dict | None = None, ip: str = "") -> dict:
    unit = get_unit(db, unit_id)
    if not unit:
        raise not_found("المؤسسة غير موجودة.")
    rows = unit_users(db, unit_id)
    if not rows:
        raise validation("لا توجد حسابات لهذه المؤسسة.")
    passwords: set[str] = set()
    credentials: list[dict] = []
    stamp = now_iso()
    with db.write() as conn:
        for row in rows:
            password = sec.unique_password(passwords)
            passwords.add(password)
            password_hash, salt, iterations = sec.hash_password(password)
            conn.execute(
                "UPDATE users SET password_hash=?, salt=?, iterations=?, must_change=0, "
                "failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?",
                (password_hash, salt, iterations, stamp, row["user_id"]))
            credentials.append({"username": row["username"], "password": password,
                                "role": row["role"], "role_label": row["role_label"],
                                "display_name": row["display_name"]})
        audit.log(db, operator, "تصفير كلمات مرور", "health_units", unit_id,
                  f"{unit['name']} — {len(credentials)} حساب", ip=ip, conn=conn)
    return {"unit": unit, "credentials": credentials}


def credentials_filename(unit: dict) -> str:
    return safe_filename(f"بيانات_دخول_{unit.get('code') or unit.get('name')}", "credentials")
