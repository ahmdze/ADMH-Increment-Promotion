"""اختبارات الخدمة المحلية عبر HTTP وعميل API."""

from __future__ import annotations

import pytest

from amdh_hr.config import Paths
from amdh_hr.server.app import ServiceApp
from amdh_hr.server.client import ApiClient, ApiError
from amdh_hr.server.http_api import ApiServer
from tests.conftest import ADMIN_PASSWORD, call


@pytest.fixture()
def running(service, admin):
    server = ApiServer(service, "127.0.0.1", 0).start(background=True)
    yield server
    server.stop()


def test_health_and_login(running):
    client = ApiClient(running.url)
    assert client.health()["ok"] is True
    login = client.login("admin", ADMIN_PASSWORD)
    assert login["user"]["role"] == "center_admin"
    assert client.call("units.list")["units"] == []
    client.logout()
    with pytest.raises(ApiError) as info:
        client.call("units.list")
    assert info.value.code == "unauthenticated"


def test_http_forbidden(running, service, admin):
    created = call(service, "units.create", admin["token"],
                   data={"name": "مركز صحي النور", "code": "PH2", "kind": "مركز صحي"},
                   editor_count=1, create_manager=False)
    editor = created["credentials"][0]
    client = ApiClient(running.url)
    client.login(editor["username"], editor["password"])
    with pytest.raises(ApiError) as info:
        client.call("units.create", data={"name": "x", "code": "y"})
    assert info.value.code == "forbidden"


def test_http_requires_initialization(running):
    client = ApiClient(running.url)
    status = client.bootstrap_status()
    assert status["initialized"] is True


def test_first_run_over_http(tmp_path):
    """أول تشغيل: قاعدة فارغة ← إنشاء مدير ← دخول، عبر HTTP كما تفعل الواجهة."""
    app = ServiceApp(Paths(tmp_path / "data"))
    server = ApiServer(app, "127.0.0.1", 0).start(background=True)
    try:
        client = ApiClient(server.url)
        assert client.bootstrap_status()["initialized"] is False
        created = client.create_admin("admin", ADMIN_PASSWORD, "مدير المركز")
        assert created["user"]["username"] == "admin"
        login = client.login("admin", ADMIN_PASSWORD)
        assert login["user"]["role"] == "center_admin"
        assert client.call("meta.info")["version"]
    finally:
        server.stop()
        app.close()
