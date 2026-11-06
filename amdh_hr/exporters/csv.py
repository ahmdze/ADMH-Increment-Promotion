"""تصدير CSV بترميز UTF-8 مع BOM ليفتح في Excel العربي مباشرة."""

from __future__ import annotations

import csv
from pathlib import Path


def export_rows(path: str | Path, headers: list[str], rows: list[list]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(["" if item is None else str(item) for item in headers])
        for row in rows:
            writer.writerow(["" if item is None else str(item) for item in row])
    return path
