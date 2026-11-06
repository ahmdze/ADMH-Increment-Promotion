"""النسخ الاحتياطي: إنشاء، فحص، وسرد."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path

from ..errors import validation
from ..util import now_iso, stamp
from . import audit

KEEP = 30


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(db, paths, operator: dict | None = None, kind: str = "manual",
        ip: str = "") -> dict:
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    target = paths.backups_dir / f"amdh_hr_{stamp()}.db"
    if getattr(db, "key", ""):
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(db.path, target)
    else:
        db.export_plaintext(target)
    size = target.stat().st_size
    digest = sha256_file(target)
    backup_id = uuid.uuid4().hex
    with db.write() as conn:
        conn.execute(
            "INSERT INTO backup_jobs(backup_id, ts, path, size, sha256, ok, note, kind) "
            "VALUES (?,?,?,?,?,1,?,?)",
            (backup_id, now_iso(), str(target), size, digest,
             "نسخة يدوية" if kind == "manual" else kind, kind))
        audit.log(db, operator, "نسخة احتياطية", "backup_jobs", backup_id,
                  f"{target.name} ({size} بايت)", ip=ip, conn=conn)
    _prune(db, paths)
    return {"backup_id": backup_id, "path": str(target), "size": size, "sha256": digest}


def _prune(db, paths) -> None:
    rows = db.query("SELECT backup_id, path FROM backup_jobs ORDER BY ts DESC")
    for row in rows[KEEP:]:
        try:
            Path(row["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        with db.write() as conn:
            conn.execute("DELETE FROM backup_jobs WHERE backup_id=?", (row["backup_id"],))


def list_backups(db) -> list[dict]:
    rows = db.query("SELECT * FROM backup_jobs ORDER BY ts DESC")
    for row in rows:
        row["exists"] = Path(row["path"]).exists()
        row["ok"] = bool(row["ok"])
        row["size_kb"] = round((row["size"] or 0) / 1024, 1)
    return rows


def verify(path: str | Path, key: str = "") -> dict:
    path = Path(path)
    if not path.exists():
        raise validation("ملف النسخة غير موجود.")
    if key:
        from .. import crypto
        try:
            connection = crypto.connect(path, key)
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"ملف غير صالح أو مفتاح مختلف: {exc}"}
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass
        return {"ok": str(result).lower() == "ok", "message": str(result),
                "sha256": sha256_file(path), "size": path.stat().st_size}
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "message": f"ملف غير صالح: {exc}"}
    finally:
        connection.close()
    return {"ok": str(result).lower() == "ok", "message": str(result),
            "sha256": sha256_file(path), "size": path.stat().st_size}
