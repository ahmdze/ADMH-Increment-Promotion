"""الثوابت العامة ومسارات البيانات."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "نظام السجل الوظيفي والعلاوات والترفيعات"
APP_SHORT = "AMDH-HR"
APP_VERSION = "0.10.0"
APP_RELEASE = "2026-10"
APP_ORGANIZATION = "AMDH"
APP_DEVELOPER = "احمد زياد رحيمه"
APP_PHONE = "07723064622"
APP_EMAIL = "ahmdze@gmail.com"

DB_FILENAME = "amdh_hr.db"
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"

# المؤسسات
UNIT_KINDS = ("مركز الدائرة", "مستشفى", "مركز صحي", "قسم", "مؤسسة")
MAX_UNIT_USERS = 5          # الحد الأقصى للحسابات في المؤسسة (مدير + مدخلون)
MAX_EDITORS = 4

# الأمان
SESSION_HOURS = 12
MAX_LOGIN_ATTEMPTS = 5
LOCK_MINUTES = 2


def app_root() -> Path:
    """مجلد البرنامج: مجلد الـ EXE في النسخة المغلّفة، أو جذر المشروع في المصدر."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    """مسار أصل داخل الحزمة (شعار/أيقونة) في المصدر أو النسخة التنفيذية."""
    candidates = [app_root() / "amdh_hr" / "assets" / name,
                  app_root() / "_internal" / "amdh_hr" / "assets" / name]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".amdh_write_test"
        probe.write_bytes(b"1")
        probe.unlink()
        return True
    except OSError:
        return False


def default_data_dir() -> Path:
    """مجلد البيانات: ``data`` بجانب البرنامج، ثم ProgramData، ثم AppData."""
    env = os.environ.get("AMDH_HR_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    root = app_root()
    candidate = root / "data"
    if _writable(candidate):
        return candidate
    common = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "AMDH" / "HR"
    if _writable(common):
        return common
    return Path(os.environ.get("APPDATA", Path.home())) / "AMDH" / "HR"


class Paths:
    """يحلّ كل مسارات البيانات مرة واحدة وبشكل مطلق."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.app_root = app_root()
        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
        self.backups_dir = self.data_dir / "backups"
        self.attachments_dir = self.data_dir / "attachments"
        self.logs_dir = self.data_dir / "logs"
        self.reports_dir = self.data_dir / "reports"
        self.exports_dir = self.data_dir / "exports"

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    def ensure(self) -> "Paths":
        for folder in (self.data_dir, self.backups_dir, self.attachments_dir,
                       self.logs_dir, self.reports_dir, self.exports_dir):
            folder.mkdir(parents=True, exist_ok=True)
        return self
