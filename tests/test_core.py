"""اختبارات الطبقة الأساسية: التهيئة، الدخول، المؤسسات، الصلاحيات، النسخ والتجهيز."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from amdh_hr import security as sec
from amdh_hr.config import Paths
from amdh_hr.exporters import html as H
from amdh_hr.server.app import ServiceApp
from tests.conftest import ADMIN_PASSWORD, call, fails


def test_schema_v2_tables(service):
    expected = {
        "job_titles", "employees", "employee_history", "documents", "document_links",
        "appreciation_letters", "appreciation_letter_recipients", "hr_orders",
        "hr_order_recipients", "rule_packages", "rule_rows", "calc_runs", "sync_packages",
    }
    for table in expected:
        assert service.db.table_exists(table), table
    assert service.db.get_meta("schema_version") == "5"


def _create_unit(service, token, **overrides):
    data = {"name": "مستشفى الكرامة", "code": "H1", "kind": "مستشفى"}
    data.update(overrides.pop("data", {}))
    return call(service, "units.create", token, data=data, **overrides)


def test_bootstrap_and_login(service, admin):
    status = call(service, "bootstrap.status")
    assert status["initialized"] is True
    login = call(service, "auth.login", username="admin", password=ADMIN_PASSWORD)
    assert login["user"]["role"] == "center_admin"
    assert "manage_units" in login["user"]["permissions"]
    me = call(service, "auth.me", admin["token"])
    assert me["user"]["username"] == "admin"


def test_create_unit_with_users(service, admin):
    result = _create_unit(service, admin["token"], editor_count=3, create_manager=True)
    credentials = result["credentials"]
    assert len(credentials) == 4
    usernames = {item["username"] for item in credentials}
    assert usernames == {"h1-m", "h1-1", "h1-2", "h1-3"}
    assert len({item["password"] for item in credentials}) == 4
    unit = result["unit"]
    assert unit["name"] == "مستشفى الكرامة"
    assert unit["users_count"] == 4

    for item in credentials:
        login = call(service, "auth.login", username=item["username"],
                     password=item["password"])
        assert login["user"]["unit_id"] == unit["unit_id"]


def test_duplicate_name_and_code(service, admin):
    _create_unit(service, admin["token"])
    error = fails(service, "units.create", admin["token"],
                  data={"name": "مستشفى الكرامة", "code": "H2"})
    assert error["code"] == "conflict"
    error = fails(service, "units.create", admin["token"],
                  data={"name": "مستشفى آخر", "code": "H1"})
    assert error["code"] == "conflict"


def test_editor_is_scoped_and_forbidden(service, admin):
    created = _create_unit(service, admin["token"], editor_count=1)
    editor = next(item for item in created["credentials"] if item["role"] == "unit_editor")
    login = call(service, "auth.login", username=editor["username"],
                 password=editor["password"])
    token = login["token"]
    units = call(service, "units.list", token)["units"]
    assert len(units) == 1
    assert units[0]["unit_id"] == created["unit"]["unit_id"]

    error = fails(service, "units.create", token,
                  data={"name": "مؤسسة جديدة", "code": "X1"})
    assert error["code"] == "forbidden"
    error = fails(service, "users.list", token)
    assert error["code"] == "forbidden"


def test_delete_unit_removes_users(service, admin):
    created = _create_unit(service, admin["token"], editor_count=2)
    usernames = [item["username"] for item in created["credentials"]]
    result = call(service, "units.delete", admin["token"],
                  unit_id=created["unit"]["unit_id"])
    assert result["users_deleted"] == 3
    for username in usernames:
        error = fails(service, "auth.login", username=username, password="whatever")
        assert error["code"] in {"bad_credentials", "inactive"}
    assert call(service, "units.list", admin["token"])["units"] == []


def test_reset_unit_users(service, admin):
    created = _create_unit(service, admin["token"], editor_count=1)
    old = created["credentials"][0]
    result = call(service, "units.reset_users", admin["token"],
                  unit_id=created["unit"]["unit_id"])
    new = next(item for item in result["credentials"] if item["username"] == old["username"])
    assert new["password"] != old["password"]
    assert fails(service, "auth.login", username=old["username"],
                 password=old["password"])["code"] == "bad_credentials"
    call(service, "auth.login", username=new["username"], password=new["password"])


def test_login_lockout(service, admin):
    for _ in range(5):
        fails(service, "auth.login", username="admin", password="wrong-pass")
    error = fails(service, "auth.login", username="admin", password=ADMIN_PASSWORD)
    assert error["code"] == "locked"


def test_backup_roundtrip(service, admin):
    run = call(service, "backup.run", admin["token"])
    path = Path(run["path"])
    assert path.exists() and path.stat().st_size > 0
    assert len(run["sha256"]) == 64
    verified = call(service, "backup.verify", admin["token"], path=str(path))
    assert verified["ok"] is True
    assert call(service, "backup.list", admin["token"])["backups"][0]["exists"] is True


def test_provisioning_bundle(service, admin, tmp_path):
    created = _create_unit(service, admin["token"], editor_count=2, create_manager=True)
    unit_id = created["unit"]["unit_id"]
    bundled = call(service, "units.provision", admin["token"], unit_id=unit_id,
                   admin_password="Maint#2026", dest_dir=str(tmp_path / "exports"),
                   include_program=False, make_zip=True)
    folder = Path(bundled["folder"])
    assert (folder / "data" / "amdh_hr.db").exists()
    assert (folder / "تعليمات_التشغيل.txt").exists()
    assert Path(bundled["zip"]).exists()

    connection = sqlite3.connect(str(folder / "data" / "amdh_hr.db"))
    try:
        usernames = {row[0] for row in connection.execute("SELECT username FROM users")}
        units = connection.execute("SELECT COUNT(*) FROM health_units").fetchone()[0]
        audits = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    finally:
        connection.close()
    assert usernames == {"admin", "h1-m", "h1-1", "h1-2"}
    assert units == 1
    assert audits == 0

    # النسخة تعمل مستقلةً بكلمة صيانة جديدة وحسابات المؤسسة نفسها
    instance = ServiceApp(Paths(folder / "data"))
    try:
        login = instance.dispatch("auth.login", {"username": "admin",
                                                 "password": "Maint#2026"})
        assert login["ok"], login
        editor = next(item for item in created["credentials"] if item["role"] == "unit_editor")
        login = instance.dispatch("auth.login", {"username": editor["username"],
                                                 "password": editor["password"]})
        assert login["ok"], login
        assert login["result"]["user"]["unit_id"] == unit_id
    finally:
        instance.close()


def test_center_cannot_be_provisioned(service, admin):
    center = call(service, "units.create", admin["token"],
                  data={"name": "مركز الدائرة", "code": "CTR", "kind": "مركز الدائرة",
                        "is_center": True}, editor_count=2, create_manager=False)
    assert center["unit"]["is_center"] is True
    error = fails(service, "units.provision", admin["token"],
                  unit_id=center["unit"]["unit_id"], admin_password="Maint#2026",
                  dest_dir="unused", include_program=False)
    assert error["code"] == "validation"
    meta = call(service, "meta.info", admin["token"])
    assert meta["center"] == "مركز الدائرة"


def test_html_escapes_user_data():
    page = H.credentials_page(
        {"name": "<script>alert(1)</script>", "code": "X1", "kind": "مستشفى", "is_center": False},
        [{"username": "u1", "password": "P<&>", "role": "unit_editor",
          "role_label": "مدخل بيانات"}],
        center_name="مركز <b>الدائرة</b>")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "P&lt;&amp;&gt;" in page


def test_password_hashing():
    digest, salt, iterations = sec.hash_password("Secret#123")
    assert sec.verify_password("Secret#123", digest, salt, iterations)
    assert not sec.verify_password("Secret#124", digest, salt, iterations)
    ok, _message = sec.password_strength("123")
    assert ok is False


def test_center_allows_five_editors(service, admin):
    result = call(service, "units.create", admin["token"],
                  data={"name": "مركز الدائرة", "code": "CTR", "kind": "مركز الدائرة",
                        "is_center": True}, editor_count=5, create_manager=False)
    assert len(result["credentials"]) == 5
    assert all(item["role"] == "center_editor" for item in result["credentials"])

    other = call(service, "units.create", admin["token"],
                 data={"name": "مؤسسة تجريبية", "code": "T1"}, editor_count=4,
                 create_manager=False)
    assert len(other["credentials"]) == 4
    error = fails(service, "units.create", admin["token"],
                  data={"name": "مؤسسة أخرى", "code": "T2"}, editor_count=5,
                  create_manager=True)
    assert error["code"] == "validation"


def test_institution_without_manager_and_username_conflict(service, admin):
    result = call(service, "units.create", admin["token"],
                  data={"name": "مركز صحي", "code": "PH9"}, editor_count=1,
                  create_manager=False)
    assert result["credentials"][0]["username"] == "ph9-1"
    error = fails(service, "users.create", admin["token"],
                  data={"username": "ph9-1", "role": "unit_editor",
                        "unit_id": result["unit"]["unit_id"]})
    assert error["code"] == "conflict"


def test_unit_manager_scope_and_permissions(service, admin):
    created = _create_unit(service, admin["token"], editor_count=1)
    manager = next(item for item in created["credentials"] if item["role"] == "unit_manager")
    login = call(service, "auth.login", username=manager["username"],
                 password=manager["password"])
    token = login["token"]
    assert call(service, "units.list", token)["units"][0]["name"] == "مستشفى الكرامة"
    assert "view_audit" in login["user"]["permissions"]
    fails(service, "units.create", token, data={"name": "x", "code": "y"})
    fails(service, "users.list", token)


def test_credentials_page_lists_all_accounts(service, admin):
    created = _create_unit(service, admin["token"], editor_count=2)
    page = H.credentials_page(created["unit"], created["credentials"],
                              center_name="مركز الدائرة")
    preview = H.credentials_preview(created["unit"], created["credentials"],
                                    center_name="مركز الدائرة")
    for item in created["credentials"]:
        assert item["username"] in page
        assert item["password"] in page
        assert item["username"] in preview
        assert item["password"] in preview
    assert "A4" in page
    assert "@media print" in page


def test_table_page_and_auto_print():
    document = H.table_page(
        "قائمة المؤسسات", ["المؤسسة", "الرمز"],
        [["<b>مؤسسة</b>", "A1"], ["أخرى", "B2"]], center_name="مركز الدائرة")
    assert "&lt;b&gt;مؤسسة&lt;/b&gt;" in document
    assert "A1" in document and "B2" in document
    assert "عدد السجلات: 2" in document
    assert "@media print" in document
    assert "window.addEventListener('load'" not in document
    printed = H.add_auto_print(document)
    assert "window.addEventListener('load'" in printed
    assert printed.count("</body>") == 1

