"""أدوات مشتركة: الوقت، السلاسل، الملفات، JSON."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# بغداد: توقيت ثابت +03:00 (لا تطبّق التوقيت الصيفي منذ 2007)
BAGHDAD = timezone(timedelta(hours=3), "Asia/Baghdad")


def now() -> datetime:
    return datetime.now(BAGHDAD)


def now_iso() -> str:
    """طابع زمني محلي قابل للفرز: ``YYYY-MM-DD HH:MM:SS``."""
    return now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso() -> str:
    return now().date().isoformat()


def parse_iso(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=BAGHDAD)
        except (ValueError, TypeError):
            continue
    return None


def date_only(value: str) -> date | None:
    parsed = parse_iso(value)
    return parsed.date() if parsed else None


def human_ts(value: str) -> str:
    parsed = parse_iso(value)
    if not parsed:
        return str(value or "—")
    return parsed.strftime("%Y-%m-%d %H:%M")


def stamp() -> str:
    return now().strftime("%Y%m%d_%H%M%S")


def as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_iso(str(value or ""))
    return parsed.date() if parsed else None


def add_months(value, months: int) -> date | None:
    """يضيف أشهراً تقويمية مع تثبيت آخر يوم في الشهر عند الحاجة."""
    start = as_date(value)
    if start is None:
        return None
    months = int(months)
    total = (start.year * 12 + (start.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = start.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def months_between(start, end) -> int:
    first, last = as_date(start), as_date(end)
    if not first or not last:
        return 0
    months = (last.year - first.year) * 12 + (last.month - first.month)
    if last.day < first.day:
        months -= 1
    return max(0, months)


def slugify(value: str, fallback: str = "unit") -> str:
    """يحوّل نصاً إلى رمز لاتيني صالح (a-z0-9-)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or fallback


def safe_filename(value: str, fallback: str = "file") -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(value or "")).strip(" ._")
    return text[:90] or fallback


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def jdump(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def jload(text, default=None):
    try:
        return json.loads(text) if text else (default if default is not None else {})
    except (ValueError, TypeError):
        return default if default is not None else {}


def truncate(value: str, length: int = 120) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= length else text[: length - 1] + "…"
