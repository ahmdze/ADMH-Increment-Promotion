"""سجل التدقيق: append-only على مستوى التطبيق."""

from __future__ import annotations

import uuid

from ..util import jdump, now_iso


def log(db, user: dict | None = None, action: str = "", entity: str = "",
        entity_id: str = "", details="", ip: str = "", conn=None) -> None:
    """يسجّل حدثاً. يُمرَّر ``conn`` عند وجود معاملة مفتوحة لتجنّب تداخل الكتابة."""
    values = (
        uuid.uuid4().hex,
        now_iso(),
        (user or {}).get("user_id") or "",
        (user or {}).get("username") or "",
        action,
        entity,
        str(entity_id or ""),
        details if isinstance(details, str) else jdump(details),
        ip or "",
    )
    sql = ("INSERT INTO audit_events(event_id, ts, user_id, username, action, entity, "
           "entity_id, details, ip) VALUES (?,?,?,?,?,?,?,?,?)")
    if conn is not None:
        conn.execute(sql, values)
    else:
        with db.write() as connection:
            connection.execute(sql, values)


def recent(db, limit: int = 200, unit_users: set[str] | None = None) -> list[dict]:
    sql = "SELECT * FROM audit_events ORDER BY ts DESC LIMIT ?"
    rows = db.query(sql, (limit,))
    if unit_users is not None:
        rows = [row for row in rows if row["username"] in unit_users]
    return rows
