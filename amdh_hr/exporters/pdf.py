"""تصدير تقارير PDF مباشرة بخط عربي مشكّل (ReportLab + Reshaper + Bidi)."""

from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import asset_path

FONT_NAME = "Tahoma"
FONT_PATH = Path(r"C:\Windows\Fonts\tahoma.ttf")
_registered = False


def _font() -> str:
    global _registered
    if not _registered:
        path = FONT_PATH if FONT_PATH.exists() else Path(r"C:\Windows\Fonts\arial.ttf")
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(path)))
        _registered = True
    return FONT_NAME


def _shape(value) -> str:
    text = "" if value is None else str(value)
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _xml(value) -> str:
    return _shape(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _style(size: int = 8, color=colors.HexColor("#0f172a"),
           align=TA_RIGHT, leading: int | None = None) -> ParagraphStyle:
    return ParagraphStyle(
        f"ar{size}{align}", fontName=_font(), fontSize=size, leading=leading or size + 3,
        alignment=align, textColor=color, wordWrap="RTL")


def export_report(path: str | Path, title: str, headers: list[str], rows: list[list],
                  note: str = "", center_name: str = "") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = max(1, len(headers))
    pagesize = landscape(A4) if columns > 6 else A4
    width = pagesize[0] - 24 * mm
    body = _style(7)
    head = _style(7, colors.white, TA_CENTER, leading=10)
    cell = ParagraphStyle("cell", parent=body, splitLongWords=1)

    data = [[Paragraph(_xml(item), head) for item in headers]]
    for row in rows:
        data.append([Paragraph(_xml(item), cell) for item in row])
    table = Table(data, colWidths=[width / columns] * columns, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story = []
    logo = asset_path("logo.png")
    if logo.exists():
        image = Image(str(logo), width=16 * mm, height=16 * mm)
        image.hAlign = "CENTER"
        story.append(image)
    story.extend([
        Paragraph(_xml(center_name or "مركز الدائرة"), _style(9, colors.HexColor("#64748b"),
                                                               TA_CENTER)),
        Paragraph(_xml(title), _style(16, colors.HexColor("#0f766e"), TA_CENTER, 22)),
        Paragraph(_xml(note or f"{len(rows)} سجل"), _style(8, colors.HexColor("#64748b"),
                                                          TA_CENTER)),
        Spacer(1, 6 * mm),
        table,
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_font(), 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawCentredString(pagesize[0] / 2, 8 * mm, _shape(f"صفحة {doc.page}"))
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(path), pagesize=pagesize, rightMargin=12 * mm, leftMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm, title=title,
        author=center_name or "AMDH-HR")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return path
