"""تصدير واستيراد Excel (RTL) — الموظفون والقوائم."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HAS_XLSX = True
except ImportError:  # pragma: no cover
    HAS_XLSX = False

HEADER_FILL = "0F172A"
HEADER_COLOR = "E2E8F0"


def _require() -> None:
    if not HAS_XLSX:
        raise RuntimeError("مكتبة openpyxl غير مثبتة.")


def read_table(path: str | Path) -> tuple[list[str], list[dict]]:
    _require()
    workbook = openpyxl.load_workbook(str(path), data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    records: list[dict] = []
    for row in rows[1:]:
        if all(cell in (None, "") for cell in row):
            continue
        records.append({headers[index]: row[index] for index in range(min(len(headers), len(row)))})
    return headers, records


def write_rows(path: str | Path, sheet_title: str, headers: list[str],
               rows: list[list], widths: list[int] | None = None) -> Path:
    _require()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_title[:31] or "ورقة"
    sheet.sheet_view.rightToLeft = True
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row))
    for cell in sheet[1]:
        cell.font = Font(bold=True, color=HEADER_COLOR)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for index, width in enumerate(widths or [18] * len(headers), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    workbook.save(path)
    return path


# ---------------------------------------------------------------------------
# الموظفون
# ---------------------------------------------------------------------------
EMPLOYEE_COLUMNS: list[tuple[str, str, list[str]]] = [
    ("emp_no", "الرقم الوظيفي *", ["emp_no", "الرقم الوظيفي", "الرقم", "الرقم الإحصائي"]),
    ("full_name", "الاسم *", ["full_name", "الاسم", "اسم الموظف"]),
    ("job_title", "العنوان الوظيفي *", ["job_title", "العنوان الوظيفي", "العنوان"]),
    ("grade", "الدرجة", ["grade", "الدرجة"]),
    ("stage", "المرحلة", ["stage", "المرحلة"]),
    ("category", "الفئة", ["category", "الفئة", "التصنيف"]),
    ("hire_date", "تاريخ المباشرة *", ["hire_date", "تاريخ المباشرة", "المباشرة"]),
    ("last_grade_date", "تاريخ الدرجة الحالية",
     ["last_grade_date", "تاريخ الدرجة", "تاريخ الدرجة الحالية"]),
    ("last_stage_date", "تاريخ المرحلة الحالية",
     ["last_stage_date", "تاريخ المرحلة", "تاريخ المرحلة الحالية"]),
    ("end_date", "تاريخ انتهاء الخدمة", ["end_date", "انتهاء الخدمة", "تاريخ الانتهاء"]),
    ("gender", "الجنس", ["gender", "الجنس"]),
    ("status", "الحالة", ["status", "الحالة", "الوضع"]),
    ("unit", "المؤسسة", ["unit", "المؤسسة", "المؤسسة/القسم", "القسم"]),
    ("assigned", "المستخدم المسؤول", ["assigned", "المستخدم المسؤول", "الحصة"]),
    ("notes", "ملاحظات", ["notes", "ملاحظات", "الملاحظات"]),
]


def normalize_date(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def export_employees(path: str | Path, employees: list[dict]) -> Path:
    headers = [label for _key, label, _synonyms in EMPLOYEE_COLUMNS]
    rows = []
    for item in employees:
        rows.append([
            item.get("emp_no"), item.get("full_name"), item.get("title_name"),
            item.get("grade"), item.get("stage"), item.get("category"),
            item.get("hire_date"), item.get("last_grade_date") or item.get("hire_date"),
            item.get("last_stage_date") or item.get("hire_date"),
            item.get("end_date") or "",
            {"male": "ذكر", "female": "أنثى"}.get(item.get("gender"), item.get("gender") or ""),
            {"active": "على الملاك", "suspended": "موقوف", "ended": "منتهي",
             "retired": "متقاعد"}.get(item.get("status"), item.get("status") or ""),
            item.get("unit_name"), item.get("assigned_username") or "",
            item.get("notes") or "",
        ])
    return write_rows(path, "الموظفون", headers, rows,
                      [14, 28, 22, 8, 8, 12, 14, 14, 14, 14, 8, 12, 24, 16, 26])


def employee_template(path: str | Path) -> Path:
    headers = [label for _key, label, _synonyms in EMPLOYEE_COLUMNS]
    sample = [
        "10001", "أحمد مثال", "طبيب", "3", "1", "طبية",
        "2015-01-01", "", "ذكر", "على الملاك", "مستشفى الكرامة", "", "صف توضيحي — احذفه",
    ]
    return write_rows(path, "الموظفون", headers, [sample],
                      [14, 28, 22, 8, 8, 12, 14, 14, 8, 12, 24, 16, 26])


def _norm_header(value) -> str:
    return str(value or "").strip().lower().replace("*", "").replace("ـ", "").strip()


def guess_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    lowered = {_norm_header(header): header for header in headers}
    for key, _label, synonyms in EMPLOYEE_COLUMNS:
        found = ""
        for synonym in synonyms:
            if _norm_header(synonym) in lowered:
                found = lowered[_norm_header(synonym)]
                break
        if not found:
            for header in headers:
                if any(_norm_header(synonym) in _norm_header(header) for synonym in synonyms):
                    found = header
                    break
        mapping[key] = found
    return mapping


def row_value(raw: dict, mapping: dict[str, str], key: str) -> str:
    header = mapping.get(key)
    if not header:
        return ""
    value = raw.get(header)
    return str(value).strip() if value is not None else ""
