"""إدارة المستخدمين: إنشاء، تعديل، تعطيل، وتصفير كلمة المرور."""

from __future__ import annotations

import re
import uuid

from .. import permissions as P
from .. import security as sec
from ..errors import conflict, not_found, validation
from ..util import now_iso
from . import audit

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

_QUERY = ("SELECT u.user_id, u.username, u.display_name, u.role, u.unit_id, u.active, "
          "u.must_change, u.last_login, u.created_at, h.name AS unit_name, h.code AS unit_code "
          "FROM users u LEFT JOIN health_units h ON h.unit_id = u.unit_id ")


def _clean_username(db, username: str, current_id: str = "") -> str:
    username = str(username or "").strip()
    if not USERNAME_RE.match(username):
        raise validation("اسم المستخدم: 3–32 حرفاً لاتينياً/رقماً، ويقبل . _ -")
    existing = db.one("SELECT user_id FROM users WHERE lower(username)=lower(?) AND user_id<>?",
                      (username, current_id))
    if existing:
        raise conflict("اسم المستخدم مستخدم مسبقاً.")
    return username


def _clean_role(db, role: str, unit_id: str | None) -> tuple[str, str | None]:
    if role not in P.ROLE_LABELS:
        raise validation("الدور غير معروف.")
    if role == "center_admin":
        return role, None
    if role in {"unit_manager", "unit_editor"}:
        if not unit_id:
            raise validation("اختر المؤسسة المرتبطة بالمستخدم.")
    if role == "center_editor" and unit_id:
        pass
    return role, unit_id or None


def list_users(db, unit_id: str | None = None) -> list[dict]:
    sql = _QUERY + ("WHERE u.unit_id=?" if unit_id else "") + " ORDER BY h.is_center DESC, h.name, u.role, u.username"
    rows = db.query(sql, (unit_id,) if unit_id else ())
    for row in rows:
        row["role_label"] = P.ROLE_LABELS.get(row["role"], row["role"])
        row["active"] = bool(row["active"])
        row["must_change"] = bool(row["must_change"])
    return rows


def get_user(db, user_id: str) -> dict | None:
    row = db.one(_QUERY + "WHERE u.user_id=?", (user_id,))
    if row:
        row["role_label"] = P.ROLE_LABELS.get(row["role"], row["role"])
        row["active"] = bool(row["active"])
    return row


def create_user(db, data: dict, operator: dict | None = None, ip: str = "") -> dict:
    username = _clean_username(db, data.get("username", ""))
    role, unit_id = _clean_role(db, data.get("role", "unit_editor"), data.get("unit_id"))
    password = str(data.get("password") or "")
    generated = False
    if password:
        ok, message = sec.password_strength(password)
        if not ok:
            raise validation(message)
    else:
        password = sec.generate_password()
        generated = True
    password_hash, salt, iterations = sec.hash_password(password)
    user_id = uuid.uuid4().hex
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "INSERT INTO users(user_id, username, display_name, role, unit_id, password_hash, "
            "salt, iterations, must_change, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,1,1,?,?)",
            (user_id, username, str(data.get("display_name") or username).strip(), role,
             unit_id, password_hash, salt, iterations, stamp, stamp))
        audit.log(db, operator, "إنشاء مستخدم", "users", user_id,
                  f"{username} — {P.ROLE_LABELS.get(role, role)}", ip=ip, conn=conn)
    result = {"user": get_user(db, user_id)}
    if generated:
        result["password"] = password
    return result


def update_user(db, user_id: str, data: dict, operator: dict | None = None,
                ip: str = "") -> dict:
    current = get_user(db, user_id)
    if not current:
        raise not_found("المستخدم غير موجود.")
    role, unit_id = _clean_role(db, data.get("role", current["role"]),
                                data.get("unit_id", current["unit_id"]))
    display = str(data.get("display_name", current["display_name"]) or "").strip()
    with db.write() as conn:
        conn.execute("UPDATE users SET display_name=?, role=?, unit_id=?, active=?, "
                     "updated_at=? WHERE user_id=?",
                     (display, role, unit_id,
                      1 if data.get("active", current["active"]) else 0,
                      now_iso(), user_id))
        audit.log(db, operator, "تعديل مستخدم", "users", user_id, current["username"],
                  ip=ip, conn=conn)
    return get_user(db, user_id)  # type: ignore[return-value]


def reset_password(db, user_id: str, operator: dict | None = None,
                   ip: str = "") -> dict:
    user = get_user(db, user_id)
    if not user:
        raise not_found("المستخدم غير موجود.")
    password = sec.generate_password()
    password_hash, salt, iterations = sec.hash_password(password)
    with db.write() as conn:
        conn.execute("UPDATE users SET password_hash=?, salt=?, iterations=?, must_change=0, "
                     "failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?",
                     (password_hash, salt, iterations, now_iso(), user_id))
        audit.log(db, operator, "تصفير كلمة مرور", "users", user_id, user["username"],
                  ip=ip, conn=conn)
    return {"user": user, "password": password}


def set_active(db, user_id: str, active: bool, operator: dict | None = None,
               ip: str = "") -> dict:
    user = get_user(db, user_id)
    if not user:
        raise not_found("المستخدم غير موجود.")
    if operator and operator.get("user_id") == user_id and not active:
        raise validation("لا يمكنك تعطيل حسابك الحالي.")
    with db.write() as conn:
        conn.execute("UPDATE users SET active=?, updated_at=? WHERE user_id=?",
                     (1 if active else 0, now_iso(), user_id))
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit.log(db, operator, "تفعيل مستخدم" if active else "تعطيل مستخدم", "users",
                  user_id, user["username"], ip=ip, conn=conn)
    return {"user": get_user(db, user_id)}
