"""اختبار مسار الواجهة الفعلي: أول تشغيل ← إنشاء مدير ← دخول."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AMDH_HR_SETTINGS", "HR_TEST")

import pytest  # noqa: E402

from amdh_hr.config import Paths  # noqa: E402
from amdh_hr.server.app import ServiceApp  # noqa: E402
from amdh_hr.server.client import ApiClient  # noqa: E402
from amdh_hr.server.http_api import ApiServer  # noqa: E402

PASSWORD = "Strong#2026"


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_letter_dialog_builds(qapp):
    from amdh_hr.ui.dialogs_letter import LetterDialog

    dialog = LetterDialog(
        None, None, {"role": "center_admin"},
        [{"unit_id": "u1", "name": "مؤسسة", "code": "U1"}],
        [{"title_id": "t1", "name": "طبيب", "code": "DOC"}],
        [{"employee_id": "e1", "emp_no": "1", "full_name": "أحمد",
          "unit_name": "مؤسسة", "grade": "3", "stage": "1", "title_code": "DOC"}])
    assert "كتاب" in dialog.windowTitle()
    dialog.close()


def test_first_run_setup_and_login(qapp, tmp_path):
    from amdh_hr.ui.app_settings import AppSettings
    from amdh_hr.ui.dialogs_login import LoginDialog, SetupDialog

    service = ServiceApp(Paths(tmp_path / "data"))
    server = ApiServer(service, "127.0.0.1", 0).start(background=True)
    try:
        client = ApiClient(server.url)
        settings = AppSettings()

        login = LoginDialog(client, settings, local_mode=True)
        login._probe()
        assert login._initialized is False
        assert login.login_btn.isEnabled() is False

        setup = SetupDialog(client, login)
        setup.username.setText("admin")
        setup.password.setText(PASSWORD)
        setup.confirm.setText(PASSWORD)
        setup._create()
        assert setup.user is not None
        assert setup.user["username"] == "admin"

        login2 = LoginDialog(client, settings, local_mode=True)
        login2._probe()
        assert login2._initialized is True
        assert login2.login_btn.isEnabled() is True

        login2.username.setText("admin")
        login2.password.setText(PASSWORD)
        login2._login()
        assert login2.user is not None
        assert login2.user["role"] == "center_admin"
    finally:
        server.stop()
        service.close()
