"""تجهيز نسخة مؤسسة: قاعدة مُنقّاة + حساباتها + نصوص التشغيل + (اختياري) البرنامج."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import uuid
import zipfile
from pathlib import Path

from ..config import APP_NAME, APP_VERSION, DB_FILENAME
from ..errors import validation
from .. import security as sec
from ..util import now_iso, safe_filename, slugify
from . import audit

SKIP_NAMES = {DB_FILENAME, DB_FILENAME + "-wal", DB_FILENAME + "-shm", ".amdh_instance.lock"}


def build_bundle(db, paths, unit_id: str, *, admin_password: str,
                 dest_dir: Path | str, include_program: bool = True,
                 make_zip: bool = True, credentials: list[dict] | None = None,
                 operator: dict | None = None, ip: str = "") -> dict:
    """ينشئ مجلد نسخة المؤسسة (وZIP) ويعيد مساراته وبياناته."""
    unit = db.one("SELECT * FROM health_units WHERE unit_id=? AND deleted_at IS NULL", (unit_id,))
    if not unit:
        raise validation("المؤسسة غير موجودة.")
    if unit["is_center"]:
        raise validation("لا تجهّز نسخة لمركز الدائرة؛ المركز هو المرجع.")
    users = db.query("SELECT * FROM users WHERE unit_id=?", (unit_id,))
    if not users:
        raise validation("أنشئ حسابات المؤسسة أولاً.")
    ok, message = sec.password_strength(admin_password)
    if not ok:
        raise validation("كلمة مرور الصيانة (admin): " + message)
    if include_program and not getattr(sys, "frozen", False):
        raise validation("تجهيز نسخة كاملة يتطلب تشغيل النسخة التنفيذية (EXE).")

    destination = Path(dest_dir).expanduser().resolve()
    slug = safe_filename(f"{slugify(unit['code'] or unit['name'], 'unit')}")
    target = destination / f"AMDH_{slug}"
    if target.exists() and any(target.iterdir()):
        raise validation(f"المجلد غير فارغ: {target}")

    data_dir = target / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("backups", "attachments", "logs", "reports", "exports"):
        (data_dir / sub).mkdir(exist_ok=True)

    temp_db = data_dir / DB_FILENAME
    db.export_plaintext(temp_db)
    stats, stored = _sanitize(temp_db, unit, admin_password, db)
    if stored:
        _copy_attachments(paths, stored, data_dir / "attachments")
    _copy_program(target) if include_program else None
    _write_texts(target, unit, credentials or [], include_program)

    zip_path = None
    if make_zip:
        zip_path = destination / f"AMDH_{slug}.zip"
        _zip(target, zip_path)

    audit.log(db, operator, "تجهيز نسخة مؤسسة", "health_units", unit_id,
              f"{unit['name']} — {stats['users']} حساب، {stats['employees']} موظف", ip=ip)
    return {"folder": str(target), "zip": str(zip_path) if zip_path else "",
            "stats": stats, "unit": dict(unit), "credentials": credentials or []}


def _sanitize(db_path: Path, unit: dict, admin_password: str, center_db) -> dict:
    """يفرّغ قاعدة المركز من كل ما لا يخص المؤسسة ويضبط admin الصيانة."""
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    center = center_db.one("SELECT * FROM health_units WHERE is_center=1 AND deleted_at IS NULL")
    center_name = center["name"] if center else ""
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DELETE FROM sessions")
        connection.execute("DELETE FROM audit_events")
        connection.execute("DELETE FROM backup_jobs")

        # قصر البيانات على موظفي المؤسسة وكتبها وأوامرها ووثائقها
        unit_id = unit["unit_id"]
        connection.execute(
            "DELETE FROM employee_history WHERE employee_id NOT IN "
            "(SELECT employee_id FROM employees WHERE unit_id=?)", (unit_id,))
        connection.execute("DELETE FROM employees WHERE unit_id<>?", (unit_id,))
        connection.execute(
            "DELETE FROM calc_runs WHERE employee_id NOT IN "
            "(SELECT employee_id FROM employees)")
        connection.execute(
            "DELETE FROM appreciation_letter_recipients WHERE employee_id NOT IN "
            "(SELECT employee_id FROM employees)")
        connection.execute(
            "DELETE FROM appreciation_letters WHERE letter_id NOT IN "
            "(SELECT letter_id FROM appreciation_letter_recipients)")
        connection.execute(
            "DELETE FROM hr_order_recipients WHERE employee_id NOT IN "
            "(SELECT employee_id FROM employees)")
        connection.execute(
            "DELETE FROM hr_orders WHERE order_id NOT IN "
            "(SELECT order_id FROM hr_order_recipients)")
        connection.execute(
            "DELETE FROM document_links WHERE "
            "(entity_type='employee' AND entity_id NOT IN (SELECT employee_id FROM employees)) "
            "OR (entity_type='letter' AND entity_id NOT IN "
            "(SELECT letter_id FROM appreciation_letters)) "
            "OR (entity_type='order' AND entity_id NOT IN (SELECT order_id FROM hr_orders))")
        connection.execute(
            "DELETE FROM documents WHERE document_id NOT IN "
            "(SELECT document_id FROM document_links)")
        # القواعد: الإصدارات المنشورة فقط
        connection.execute(
            "DELETE FROM rule_rows WHERE package_id NOT IN "
            "(SELECT package_id FROM rule_packages WHERE status='published')")
        connection.execute("DELETE FROM rule_packages WHERE status<>'published'")

        # المستخدمون: حسابات المؤسسة فقط + admin جديد
        connection.execute("DELETE FROM users WHERE unit_id IS NULL OR unit_id<>?",
                           (unit["unit_id"],))
        connection.execute("DELETE FROM users WHERE lower(username)='admin'")
        password_hash, salt, iterations = sec.hash_password(admin_password)
        stamp = now_iso()
        connection.execute(
            "INSERT INTO users(user_id, username, display_name, role, unit_id, password_hash, "
            "salt, iterations, must_change, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,1,?,?)",
            (uuid.uuid4().hex, "admin", "صيانة المركز", "center_admin", None,
             password_hash, salt, iterations, stamp, stamp))

        # المؤسسات: مركز الدائرة (للاسم) + المؤسسة
        keep = [unit["unit_id"]]
        if center:
            keep.append(center["unit_id"])
        placeholders = ",".join("?" for _ in keep)
        connection.execute(f"DELETE FROM health_units WHERE unit_id NOT IN ({placeholders})",
                           keep)
        connection.execute("UPDATE health_units SET is_center=0 WHERE unit_id=?",
                           (unit["unit_id"],))
        if center:
            connection.execute("UPDATE health_units SET is_center=1 WHERE unit_id=?",
                               (center["unit_id"],))

        meta = {
            "auth_enabled": "1",
            "provisioned_unit_id": unit["unit_id"],
            "provisioned_unit_name": unit["name"],
            "provisioned_at": stamp,
            "center_unit_id": center["unit_id"] if center else "",
            "center_unit_name": center_name,
            "app_version": APP_VERSION,
        }
        for key, value in meta.items():
            connection.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES (?,?)",
                               (key, value))
        connection.commit()
        connection.execute("VACUUM")
        stats = {
            "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "employees": _count(connection, "employees", unit_id),
            "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "units": connection.execute("SELECT COUNT(*) FROM health_units").fetchone()[0],
        }
        stored = [row[0] for row in connection.execute(
            "SELECT DISTINCT stored_name FROM documents").fetchall() if row[0]]
    finally:
        connection.close()
    return stats, stored


def _copy_attachments(paths, stored: list[str], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(paths.attachments_dir)
    for name in stored:
        file = source / name
        if file.exists():
            shutil.copy2(file, destination / name)


def _count(connection, table: str, unit_id: str) -> int:
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table} WHERE unit_id=?",
                                  (unit_id,)).fetchone()[0]
    except sqlite3.DatabaseError:
        return 0


def _copy_program(target: Path) -> None:
    exe = Path(sys.executable)
    shutil.copy2(exe, target / exe.name)
    internal = exe.parent / "_internal"
    if internal.is_dir():
        shutil.copytree(internal, target / "_internal",
                        ignore=shutil.ignore_patterns(*SKIP_NAMES))


def _write_texts(target: Path, unit: dict, credentials: list[dict],
                 include_program: bool) -> None:
    code = unit.get("code") or "UNIT"
    rows = "\n".join(
        f"  {item['username']:<18} {item['password']:<12} {item.get('role_label', '')}"
        for item in credentials)
    credential_text = (
        f"{APP_NAME} — نسخة مؤسسة: {unit['name']}\n"
        f"الرمز: {code}\n"
        f"تاريخ التجهيز: {now_iso()}\n\n"
        + ("بيانات الدخول الجديدة:\n" + rows + "\n\n" if credentials else
           "بيانات الدخول: هي البطاقة التي سلّمها مركز الدائرة عند إنشاء الحسابات.\n"
           "إذا فُقدت، اطلب من المركز تصفير كلمات المرور وإصدار بطاقة جديدة.\n")
        + "حساب الصيانة (admin): كلمة مروره لدى مركز الدائرة، ولا تُكتب هنا.\n")
    (target / "بيانات_الدخول.txt").write_text(credential_text, encoding="utf-8")

    exe_name = "AMDH-HR.exe" if include_program else "run.py"
    instructions = f"""{APP_NAME} — نسخة مؤسسة: {unit['name']}
{'=' * 60}

1) انسخ المجلد إلى قرص محلي (مثال: C:\\AMDH\\{code}). لا تضعه في Program Files.
2) للمستخدم الواحد: شغّل «تشغيل_المستخدم_الواحد.bat».
   لأكثر من مستخدم على الشبكة الداخلية:
     • على جهاز الخدمة: شغّل «تشغيل_الخدمة.bat» واتركه يعمل.
     • على أجهزة العملاء: عدّل «server.txt» ليحمل عنوان جهاز الخدمة، ثم
       شغّل «تشغيل_العميل.bat».
3) سجّل الدخول بحسابك من بيانات_الدخول.txt.
4) لا تحذف مجلد data: فيه قاعدة المؤسسة والنسخ الاحتياطية والمرفقات.
5) عند نهاية الشهر: «تصدير للمركز» ← احفظ الحزمة على USB ← سلّمها للمركز.
6) عند التحديث: استبدل ملفات البرنامج فقط، وأبقِ data كما هي.
"""
    (target / "تعليمات_التشغيل.txt").write_text(instructions, encoding="utf-8")

    (target / "VERSION.txt").write_text(
        f"APP={APP_NAME}\nVERSION={APP_VERSION}\nUNIT={unit['name']}\nCODE={code}\n"
        f"CREATED_AT={now_iso()}\n", encoding="utf-8")

    data_arg = '--data-dir "%~dp0data"'
    if include_program:
        (target / "تشغيل_الخدمة.bat").write_text(
            "@echo off\r\ncd /d \"%~dp0\"\r\n"
            f"\"{exe_name}\" --server --host 0.0.0.0 --port 8765 {data_arg}\r\npause\r\n",
            encoding="utf-8")
        (target / "تشغيل_العميل.bat").write_text(
            "@echo off\r\ncd /d \"%~dp0\"\r\n"
            "set /p SERVER=<server.txt\r\n"
            f"\"{exe_name}\" --server-url \"%SERVER%\"\r\n", encoding="utf-8")
        (target / "تشغيل_المستخدم_الواحد.bat").write_text(
            "@echo off\r\ncd /d \"%~dp0\"\r\n"
            f"\"{exe_name}\" --standalone {data_arg}\r\n", encoding="utf-8")
    (target / "server.txt").write_text("http://127.0.0.1:8765\n", encoding="utf-8")


def _zip(folder: Path, zip_path: Path) -> Path:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in folder.rglob("*"):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(folder).as_posix())
    return zip_path
