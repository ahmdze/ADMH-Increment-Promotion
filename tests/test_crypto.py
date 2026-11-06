"""اختبار تشفير SQLCipher: إنشاء، فتح، تصدير، ونسخ احتياطي."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from amdh_hr import crypto
from amdh_hr.config import Paths
from amdh_hr.db import Database
from amdh_hr.server.app import ServiceApp
from tests.conftest import call

PASSPHRASE = "Strong#2026"


def test_encrypt_open_export_and_wrong_key(tmp_path):
    path = tmp_path / "amdh_hr.db"
    db = Database(path)
    db.set_meta("probe", "ok")
    db.close()
    backup = crypto.encrypt_database(path, PASSPHRASE, tmp_path / "backups")
    assert crypto.is_encrypted(path)
    assert crypto.is_encrypted(backup)
    key = crypto.key_for_passphrase(tmp_path, PASSPHRASE)
    opened = Database(path, key)
    try:
        assert opened.get_meta("probe") == "ok"
        plain = tmp_path / "plain.db"
        opened.export_plaintext(plain)
        assert plain.read_bytes()[:15] == b"SQLite format 3"
        assert sqlite3.connect(plain).execute(
            "SELECT value FROM app_meta WHERE key='probe'").fetchone()[0] == "ok"
    finally:
        opened.close()
    try:
        Database(path, "00" * 32)
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    assert raised


def test_service_with_encrypted_database(tmp_path):
    paths = Paths(tmp_path / "data")
    paths.ensure()
    bootstrap = ServiceApp(paths)
    bootstrap.db.set_meta("probe", "encrypted")
    bootstrap.close()
    crypto.encrypt_database(paths.db_path, PASSPHRASE, paths.backups_dir)
    key = crypto.key_for_passphrase(paths.data_dir, PASSPHRASE)
    service = ServiceApp(paths, key)
    try:
        assert service.db.get_meta("probe") == "encrypted"
        result = service.dispatch("bootstrap.create_admin", {
            "username": "admin", "password": "Strong#2026",
            "display_name": "مدير المركز"})
        assert result["ok"], result
    finally:
        service.close()


def test_headless_key_setup_and_backup(tmp_path, monkeypatch):
    import run
    paths = Paths(tmp_path / "data")
    monkeypatch.setenv("AMDH_HR_DB_PASSPHRASE", PASSPHRASE)
    key = run._ensure_key(paths, headless=True)
    assert key
    assert crypto.key_path(paths.data_dir).exists()
    service = ServiceApp(paths, key)
    try:
        service.dispatch("bootstrap.create_admin", {
            "username": "admin", "password": "Strong#2026",
            "display_name": "مدير المركز"})
        login = service.dispatch("auth.login", {
            "username": "admin", "password": "Strong#2026"})
        token = login["result"]["token"]
        result = call(service, "backup.run", token)
        backup_path = Path(result["path"])
        assert crypto.is_encrypted(backup_path)
        verified = call(service, "backup.verify", token, path=str(backup_path))
        assert verified["ok"] is True
    finally:
        service.close()


def test_provision_from_encrypted_database_is_plaintext(tmp_path, monkeypatch):
    import run
    from tests.conftest import call
    paths = Paths(tmp_path / "data")
    monkeypatch.setenv("AMDH_HR_DB_PASSPHRASE", PASSPHRASE)
    key = run._ensure_key(paths, headless=True)
    service = ServiceApp(paths, key)
    try:
        service.dispatch("bootstrap.create_admin", {
            "username": "admin", "password": "Strong#2026",
            "display_name": "مدير المركز"})
        token = service.dispatch("auth.login", {
            "username": "admin", "password": "Strong#2026"})["result"]["token"]
        created = call(service, "units.create", token,
                       data={"name": "مؤسسة مشفرة", "code": "E1"},
                       editor_count=1, create_manager=True)
        title = call(service, "titles.create", token,
                     data={"code": "DOC", "name": "طبيب"})["title"]
        call(service, "employees.create", token, data={
            "emp_no": "E-100", "full_name": "موظف مشفر",
            "unit_id": created["unit"]["unit_id"], "job_title_id": title["title_id"],
            "hire_date": "2015-01-01", "gender": "male"})
        bundled = call(service, "units.provision", token,
                       unit_id=created["unit"]["unit_id"],
                       admin_password="Maint#2026",
                       dest_dir=str(tmp_path / "bundles"),
                       include_program=False, make_zip=False)
        bundled_db = Path(bundled["folder"]) / "data" / "amdh_hr.db"
        assert bundled_db.read_bytes()[:15] == b"SQLite format 3"
        check = sqlite3.connect(bundled_db)
        try:
            assert check.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 1
        finally:
            check.close()
    finally:
        service.close()


def test_headless_encrypts_existing_plain_database(tmp_path, monkeypatch):
    import run
    paths = Paths(tmp_path / "data")
    paths.ensure()
    plain = Database(paths.db_path)
    plain.set_meta("probe", "plain")
    plain.close()
    monkeypatch.setenv("AMDH_HR_DB_PASSPHRASE", PASSPHRASE)
    key = run._ensure_key(paths, headless=True)
    assert key
    assert crypto.is_encrypted(paths.db_path)
    opened = Database(paths.db_path, key)
    try:
        assert opened.get_meta("probe") == "plain"
    finally:
        opened.close()
