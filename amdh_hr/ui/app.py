"""تهيئة تطبيق سطح المكتب وتشغيل شاشة الدخول."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication, QDialog

from ..config import APP_NAME, asset_path
from ..server.client import ApiClient, ApiError
from . import theme
from .app_settings import AppSettings
from .dialogs_login import LoginDialog
from .main_window import MainWindow
from .notify import error


def run(server_url: str = "", theme_name: str = "", local_mode: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("AMDH")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setFont(QFont("Segoe UI", 10))
    icon = asset_path("icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    settings = AppSettings()
    if theme_name in {"auto", "dark", "light"}:
        settings.theme = theme_name
    app.setStyleSheet(theme.stylesheet(settings.theme))

    client = ApiClient(server_url or settings.server_url)
    dialog = LoginDialog(client, settings, local_mode=local_mode)
    if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.user:
        return 0
    try:
        meta = client.call("meta.info")
    except ApiError as exc:
        error(None, str(exc))
        return 1
    window = MainWindow(client, dialog.user, settings, meta, local_mode=local_mode)
    window.show()
    return app.exec()
