"""تجهيزات الاختبار: خدمة على قاعدة مؤقتة."""

from __future__ import annotations

import pytest

from amdh_hr.config import Paths
from amdh_hr.server.app import ServiceApp

ADMIN_PASSWORD = "Strong#2026"


@pytest.fixture()
def service(tmp_path):
    app = ServiceApp(Paths(tmp_path / "data"))
    yield app
    app.close()


@pytest.fixture()
def admin(service):
    created = service.dispatch("bootstrap.create_admin",
                              {"username": "admin", "password": ADMIN_PASSWORD,
                               "display_name": "مدير المركز"})
    assert created["ok"], created
    login = service.dispatch("auth.login",
                             {"username": "admin", "password": ADMIN_PASSWORD})
    assert login["ok"], login
    return {"token": login["result"]["token"], "user": login["result"]["user"]}


def call(service, method: str, token: str = "", **params):
    response = service.dispatch(method, params, token)
    assert response["ok"], response
    return response["result"]


def fails(service, method: str, token: str = "", **params) -> dict:
    response = service.dispatch(method, params, token)
    assert not response["ok"], response
    return response["error"]
