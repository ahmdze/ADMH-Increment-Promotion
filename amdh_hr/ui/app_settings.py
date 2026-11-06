"""إعدادات المستخدم المحلية (QSettings): عنوان الخدمة والثيم."""

from __future__ import annotations

import os

from PyQt6.QtCore import QSettings

from ..config import DEFAULT_PORT

ORG = "AMDH"
APP = os.environ.get("AMDH_HR_SETTINGS", "HR")


class AppSettings:
    def __init__(self) -> None:
        self.qs = QSettings(ORG, APP)

    # ------------------------------------------------------------------
    @property
    def server_url(self) -> str:
        return str(self.qs.value("server_url", f"http://127.0.0.1:{DEFAULT_PORT}") or "")

    @server_url.setter
    def server_url(self, value: str) -> None:
        self.qs.setValue("server_url", str(value or "").strip())

    @property
    def theme(self) -> str:
        name = str(self.qs.value("theme", "dark") or "dark")
        return name if name in {"auto", "dark", "light"} else "dark"

    @theme.setter
    def theme(self, value: str) -> None:
        self.qs.setValue("theme", value if value in {"auto", "dark", "light"} else "dark")

    @property
    def last_username(self) -> str:
        return str(self.qs.value("last_username", "") or "")

    @last_username.setter
    def last_username(self, value: str) -> None:
        self.qs.setValue("last_username", str(value or ""))

    @property
    def window_size(self) -> tuple[int, int]:
        width = int(self.qs.value("window_width", 1280) or 1280)
        height = int(self.qs.value("window_height", 820) or 820)
        return max(1000, width), max(680, height)

    def save_window_size(self, width: int, height: int) -> None:
        self.qs.setValue("window_width", int(width))
        self.qs.setValue("window_height", int(height))
