"""المصادقة: التهيئة الأولى، الدخول والخروج، الجلسات، تغيير كلمة المرور."""

from __future__ import annotations

import uuid
from datetime import timedelta

from .. import permissions as P
from .. import security as sec
from ..config import LOCK_MINUTES, MAX_LOGIN_ATTEMPTS, SESSION_HOURS
from ..errors import AppError, validation
from ..util import now, now_iso, parse_iso
from . import audit

PUBLIC_FIELDS = ("user_id", "username", "display_name", "role", "unit_id",
                 "must_change", "active", "last_login", "unit_name")


def _row(db, user_id: str | None = None, username: str | None = None,
         token_hash: str | None = None) -> dict | None:
    base = ("SELECT u.*, h.name AS unit_name, h.code AS unit_code "
            "FROM users u LEFT JOIN health_units h ON h.unit_id = u.unit_id ")
    if token_hash:
        return db.one(base + "JOIN sessions s ON s.user_id = u.user_id "
                             "WHERE s.token_hash = ?", (token_hash,))
    if user_id:
        return db.one(base + "WHERE u.user_id = ?", (user_id,))
    if username:
        return db.one(base + "WHERE lower(u.username) = lower(?)", (username,))
    return None


def public_user(db, row: dict) -> dict:
    data = {key: row.get(key) for key in PUBLIC_FIELDS}
    data["active"] = bool(data.get("active"))
    data["must_change"] = bool(data.get("must_change"))
    data["role_label"] = P.ROLE_LABELS.get(data["role"], data["role"])
    data["permissions"] = sorted(db.role_permissions(data["role"]))
    return data


def bootstrap_status(db) -> dict:
    has_users = db.count("users") > 0
    return {
        "initialized": has_users,
        "has_center": bool(db.one("SELECT 1 FROM health_units WHERE is_center=1 "
                                  "AND deleted_at IS NULL")),
        "schema_version": db.get_meta("schema_version", "0"),
    }


def create_admin(db, username: str, password: str, display_name: str = "") -> dict:
    """ينشئ مدير المركز الأول. مسموح فقط عندما لا يوجد أي مستخدم."""
    if db.count("users") > 0:
        raise AppError("already_initialized", "النظام مُهيّأ مسبقاً.")
    username = (username or "admin").strip()
    if not username or len(username) < 3:
        raise validation("اسم المستخدم قصير (3 أحرف على الأقل).")
    ok, message = sec.password_strength(password)
    if not ok:
        raise validation(message)
    password_hash, salt, iterations = sec.hash_password(password)
    user_id = uuid.uuid4().hex
    stamp = now_iso()
    with db.write() as conn:
        conn.execute(
            "INSERT INTO users(user_id, username, display_name, role, unit_id, password_hash, "
            "salt, iterations, must_change, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,1,?,?)",
            (user_id, username, display_name or "مدير المركز", "center_admin", None,
             password_hash, salt, iterations, stamp, stamp))
        audit.log(db, {"user_id": user_id, "username": username}, "تهيئة النظام", "users",
                  user_id, "إنشاء مدير المركز الأول", conn=conn)
    return public_user(db, _row(db, user_id=user_id))  # type: ignore[arg-type]


def login(db, username: str, password: str, ip: str = "") -> dict:
    row = _row(db, username=username)
    generic = AppError("bad_credentials", "اسم المستخدم أو كلمة المرور غير صحيحة.")
    if row is None:
        audit.log(db, {"username": username}, "دخول فاشل", "users", "",
                  "اسم مستخدم غير موجود", ip=ip)
        raise generic
    if not row["active"]:
        raise AppError("inactive", "الحساب معطّل. راجع مدير المركز.")
    locked_until = row.get("locked_until") or ""
    if locked_until and locked_until > now_iso():
        remaining = parse_iso(locked_until)
        seconds = max(1, int((remaining - now()).total_seconds())) if remaining else 60
        raise AppError("locked", f"الحساب مقفل مؤقتاً. أعد المحاولة بعد {seconds} ثانية.",
                       seconds=seconds)
    if not sec.verify_password(password, row["password_hash"], row["salt"],
                               row["iterations"]):
        attempts = int(row.get("failed_attempts") or 0) + 1
        locked = ""
        if attempts >= MAX_LOGIN_ATTEMPTS:
            locked = (now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        with db.write() as conn:
            conn.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE user_id=?",
                         (attempts, locked, row["user_id"]))
            audit.log(db, {"user_id": row["user_id"], "username": row["username"]},
                      "دخول فاشل", "users", row["user_id"],
                      f"محاولة {attempts} من {MAX_LOGIN_ATTEMPTS}", ip=ip, conn=conn)
        if locked:
            raise AppError("locked", "تجاوزت عدد المحاولات. الحساب مقفل مؤقتاً.", seconds=LOCK_MINUTES * 60)
        raise generic

    token = sec.new_token()
    expires = (now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    stamp = now_iso()
    with db.write() as conn:
        conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? "
                     "WHERE user_id=?", (stamp, row["user_id"]))
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (stamp,))
        conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, "
                     "last_seen, ip) VALUES (?,?,?,?,?,?)",
                     (sec.token_hash(token), row["user_id"], stamp, expires, stamp, ip))
        audit.log(db, {"user_id": row["user_id"], "username": row["username"]},
                  "تسجيل دخول", "users", row["user_id"], "دخول ناجح", ip=ip, conn=conn)
    return {"token": token, "expires_at": expires, "user": public_user(db, row)}


def logout(db, token: str, ip: str = "") -> dict:
    if token:
        with db.write() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (sec.token_hash(token),))
    return {"ok": True}


def resolve(db, token: str, ip: str = "") -> dict | None:
    if not token:
        return None
    row = _row(db, token_hash=sec.token_hash(token))
    if row is None:
        return None
    if (row.get("active") or 0) != 1:
        return None
    stamp = now_iso()
    session = db.one("SELECT * FROM sessions WHERE token_hash=?", (sec.token_hash(token),))
    if session is None or session["expires_at"] <= stamp:
        with db.write() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (sec.token_hash(token),))
        return None
    last_seen = session.get("last_seen") or ""
    if not last_seen or (parse_iso(stamp) - parse_iso(last_seen)).total_seconds() > 60:  # type: ignore[operator]
        with db.write() as conn:
            conn.execute("UPDATE sessions SET last_seen=?, ip=? WHERE token_hash=?",
                         (stamp, ip or session.get("ip", ""), sec.token_hash(token)))
    return public_user(db, row)


def change_password(db, token: str, old_password: str, new_password: str) -> dict:
    row = _row(db, token_hash=sec.token_hash(token))
    if row is None:
        raise AppError("unauthenticated", "انتهت الجلسة.", status=401)
    if not sec.verify_password(old_password, row["password_hash"], row["salt"],
                               row["iterations"]):
        raise validation("كلمة المرور الحالية غير صحيحة.")
    ok, message = sec.password_strength(new_password)
    if not ok:
        raise validation(message)
    password_hash, salt, iterations = sec.hash_password(new_password)
    with db.write() as conn:
        conn.execute("UPDATE users SET password_hash=?, salt=?, iterations=?, must_change=0, "
                     "updated_at=? WHERE user_id=?",
                     (password_hash, salt, iterations, now_iso(), row["user_id"]))
        audit.log(db, {"user_id": row["user_id"], "username": row["username"]},
                  "تغيير كلمة المرور", "users", row["user_id"], "", conn=conn)
    return {"ok": True}
