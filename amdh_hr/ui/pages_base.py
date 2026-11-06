"""قاعدة صفحات الواجهة."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ..server.client import ApiClient
from .app_settings import AppSettings


class BasePage(QWidget):
    def __init__(self, client: ApiClient, user: dict, meta: dict,
                 settings: AppSettings) -> None:
        super().__init__()
        self.client = client
        self.user = user
        self.meta = meta
        self.settings = settings
        self.build()

    def build(self) -> None:  # pragma: no cover - تُنفَّذ في الأبناء
        pass

    def refresh(self) -> None:  # pragma: no cover
        pass

    def can(self, permission: str) -> bool:
        return permission in (self.user.get("permissions") or [])

    @property
    def reports_dir(self) -> str:
        from pathlib import Path
        return str(Path(self.meta.get("data_dir", ".")) / "reports")
