"""تصدير HTML جاهز للطباعة (A4، RTL، بلا اعتماد على مكتبات خارجية).

كل قيمة تُهرَّب بـ ``html.escape``، ويُفتح الملف في المتصفح للطباعة أو الحفظ PDF.
"""

from __future__ import annotations

import base64
import html
import webbrowser
from datetime import datetime
from pathlib import Path

from ..config import APP_DEVELOPER, APP_NAME, APP_PHONE, APP_VERSION, asset_path
from ..util import safe_filename

PRINT_CSS = """
@page { size: A4; margin: 15mm 13mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', Tahoma, Arial, sans-serif; direction: rtl;
  color: #0f172a; background: #eef2f7; padding: 22px; font-size: 11.5pt;
}
.sheet {
  max-width: 190mm; margin: 0 auto; background: #fff; padding: 12mm 12mm 10mm;
  border-radius: 10px; box-shadow: 0 10px 34px rgba(15,23,42,.12);
}
.brand { display: flex; justify-content: space-between; align-items: flex-start;
         border-bottom: 3px solid #0f766e; padding-bottom: 8px; margin-bottom: 14px; }
.brand-id { display: flex; gap: 10px; align-items: center; }
.brand-logo { width: 46px; height: 46px; border-radius: 10px; }
.brand .name { font-size: 13pt; font-weight: 700; color: #0f172a; }
.brand .sub { font-size: 9pt; color: #64748b; }
h1 { font-size: 19pt; color: #0f766e; margin: 2px 0 4px; }
.subtitle { color: #475569; font-size: 10pt; margin-bottom: 14px; }
h2 { font-size: 12pt; color: #0f172a; margin: 16px 0 6px; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 12px; }
th, td { border: 1px solid #cbd5e1; padding: 7px 9px; text-align: right; vertical-align: middle; }
th { background: #e2e8f0; font-weight: 700; }
table.meta th { width: 30%; background: #f1f5f9; }
table.users thead th { background: #0f172a; color: #e2e8f0; }
table.users td.role { width: 26%; }
table.report thead th { background: #0f172a; color: #e2e8f0; }
table.report tbody tr:nth-child(even) td { background: #f8fafc; }
.pass { font-family: Consolas, 'Courier New', monospace; direction: ltr; text-align: center;
        letter-spacing: .8px; font-size: 11pt; font-weight: 700; }
.mono { font-family: Consolas, 'Courier New', monospace; direction: ltr; text-align: center; }
.box { border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px 14px; margin: 12px 0;
       background: #f8fafc; }
.warn { background: #fff7ed; border-color: #fb923c; color: #7c2d12; }
.box ol, .box ul { margin: 6px 0 0; padding-inline-start: 20px; }
.box li { margin: 3px 0; }
.signatures { width: 100%; margin-top: 34px; border: 0; }
.signatures td { border: 0; text-align: center; padding-top: 26px; vertical-align: bottom; }
.signatures .line { border-top: 1px solid #0f172a; padding-top: 5px; font-weight: 700; }
.footer { margin-top: 18px; border-top: 1px solid #e2e8f0; padding-top: 6px;
          color: #64748b; font-size: 8.5pt; display: flex; justify-content: space-between; }
.toolbar { position: sticky; top: 0; z-index: 5; display: flex; gap: 8px; justify-content: center;
           margin-bottom: 14px; }
.toolbar button { padding: 9px 18px; border-radius: 8px; border: 1px solid #0f766e;
                  background: #0f766e; color: #fff; font-size: 11pt; font-weight: 700;
                  font-family: inherit; cursor: pointer; }
.toolbar button.ghost { background: #fff; color: #0f766e; }
@media print {
  body { background: #fff; padding: 0; }
  .sheet { box-shadow: none; border-radius: 0; padding: 0; max-width: none; }
  .toolbar { display: none !important; }
  tr, .box { break-inside: avoid; page-break-inside: avoid; }
  thead { display: table-header-group; }
}
"""

_AUTO_PRINT = (
    "<script>window.addEventListener('load',function(){"
    "setTimeout(function(){window.print();},350);});</script>"
)


def esc(value) -> str:
    """تهريب آمن لكل بيانات المستخدم."""
    return html.escape("" if value is None else str(value), quote=True)


def stamp_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _logo_data() -> str:
    for name in ("logo.png", "logo_small.png"):
        path = asset_path(name)
        if path.exists():
            return base64.b64encode(path.read_bytes()).decode("ascii")
    return ""


def page(title: str, body: str, *, subtitle: str = "", brand_right: str = "",
         brand_left: str = "", auto_print: bool = False, footer_note: str = "") -> str:
    toolbar = ('<div class="toolbar">'
               '<button onclick="window.print()">طباعة / حفظ PDF</button>'
               '<button class="ghost" onclick="window.close()">إغلاق</button></div>')
    brand = ""
    if brand_right or brand_left:
        data = _logo_data()
        logo = (f'<img class="brand-logo" alt="logo" '
                f'src="data:image/png;base64,{data}">' if data else "")
        brand = (
            f'<div class="brand"><div class="brand-id">{logo}'
            f'<div><div class="name">{esc(brand_right)}</div>'
            f'<div class="sub">{esc(brand_left)}</div></div></div>'
            f'<div class="sub">{esc(APP_NAME)}<br>الإصدار {esc(APP_VERSION)}</div></div>')
    footer = footer_note or f"{APP_NAME} — {APP_DEVELOPER} · {APP_PHONE}"
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{PRINT_CSS}</style>
</head>
<body>
{toolbar}
<div class="sheet">
{brand}
<h1>{esc(title)}</h1>
<div class="subtitle">{esc(subtitle)}</div>
{body}
<div class="footer"><span>تاريخ الطباعة: {esc(stamp_text())}</span>
<span>{esc(footer)}</span></div>
</div>
{_AUTO_PRINT if auto_print else ""}
</body>
</html>"""


def signatures(right: str = "تسليم (مدير المركز)", left: str = "استلام (موظف المؤسسة)") -> str:
    return (f'<table class="signatures"><tr>'
            f'<td><div class="line">{esc(right)}</div></td>'
            f'<td><div class="line">{esc(left)}</div></td>'
            f'</tr></table>')


def accounts_label(count: int) -> str:
    if count == 1:
        return "حساب واحد"
    if count == 2:
        return "حسابان"
    if 3 <= count <= 10:
        return f"{count} حسابات"
    return f"{count} حساباً"


def credentials_page(unit: dict, credentials: list[dict], *, center_name: str = "",
                     auto_print: bool = False, server_hint: str = "") -> str:
    """بطاقة بيانات دخول مؤسسة (أو مركز) بكل حساباتها."""
    is_center = bool(unit.get("is_center"))
    title = "بطاقة بيانات دخول مركز الدائرة" if is_center else "بطاقة بيانات دخول المؤسسة"
    subtitle = (f"{accounts_label(len(credentials))} — تُسلَّم كل بيانات لحاملها، وتُحفظ في "
                "مكان آمن")
    rows = "".join(
        f"<tr><td class='role'>{esc(item.get('role_label') or item.get('role'))}</td>"
        f"<td class='mono'>{esc(item.get('username'))}</td>"
        f"<td class='pass'>{esc(item.get('password'))}</td></tr>"
        for item in credentials)

    meta = (
        "<table class='meta'>"
        f"<tr><th>{'الجهة' if is_center else 'المؤسسة'}</th><td>{esc(unit.get('name'))}</td></tr>"
        f"<tr><th>الرمز</th><td>{esc(unit.get('code') or '—')}</td></tr>"
        f"<tr><th>النوع</th><td>{esc(unit.get('kind') or '—')}</td></tr>"
        f"<tr><th>مركز الدائرة</th><td>{esc(center_name or '—')}</td></tr>"
        f"<tr><th>تاريخ التسليم</th><td>{esc(stamp_text())}</td></tr>"
        "</table>")

    steps = [
        f"شغّل برنامج «{APP_NAME}» على جهازك.",
        "أدخل اسم المستخدم وكلمة المرور الخاصة بك من الجدول أعلاه.",
        "غيّر كلمة المرور من «الإعدادات ← الأمان» بعد أول دخول (يُستحسن).",
        "لا تشارك بياناتك مع أي مستخدم آخر؛ كل حساب يعمل على حصته من الموظفين.",
    ]
    if not is_center:
        steps.insert(1, server_hint or "اتصل بخدمة المؤسسة على الشبكة الداخلية (عنوان الجهاز الخادم).")
    instructions = "<div class='box'><strong>تعليمات الاستخدام:</strong><ol>" + \
                   "".join(f"<li>{esc(step)}</li>" for step in steps) + "</ol></div>"

    body = (
        meta +
        "<h2>الحسابات وكلمات المرور</h2>"
        "<table class='users'><thead><tr><th>نوع الحساب</th><th>اسم المستخدم</th>"
        "<th>كلمة المرور</th></tr></thead><tbody>" + rows + "</tbody></table>" +
        instructions +
        "<div class='box warn'><strong>تنبيه:</strong> كلمات المرور لا تُعرض مرة أخرى بعد "
        "إغلاق هذه الشاشة، والنظام يحفظ بصمتها فقط. إذا فُقدت، يصفّرها مدير المركز ويصدر "
        "بطاقة جديدة.</div>" +
        signatures()
    )
    return page(title, body, subtitle=subtitle, brand_right=center_name or (unit.get("name") or ""),
                brand_left="بطاقة دخول رسمية — تُطبع وتُسلَّم ورقياً", auto_print=auto_print)


def credentials_preview(unit: dict, credentials: list[dict], *, center_name: str = "") -> str:
    """نسخة مبسّطة من البطاقة تعرض داخل QTextBrowser (بلا CSS متقدم)."""
    is_center = bool(unit.get("is_center"))
    title = "بطاقة بيانات دخول مركز الدائرة" if is_center else "بطاقة بيانات دخول المؤسسة"
    meta_rows = "".join(
        f"<tr><td width='32%' bgcolor='#f1f5f9'><b>{esc(label)}</b></td>"
        f"<td>{esc(value)}</td></tr>"
        for label, value in (
            ("الجهة" if is_center else "المؤسسة", unit.get("name")),
            ("الرمز", unit.get("code") or "—"),
            ("النوع", unit.get("kind") or "—"),
            ("مركز الدائرة", center_name or "—"),
            ("تاريخ التسليم", stamp_text()),
        ))
    rows = "".join(
        f"<tr><td align='center'>{esc(item.get('role_label') or item.get('role'))}</td>"
        f"<td align='center'><font face='Consolas'>{esc(item.get('username'))}</font></td>"
        f"<td align='center'><b><font face='Consolas'>{esc(item.get('password'))}</font></b></td></tr>"
        for item in credentials)
    return (
        "<div dir='rtl' style=\"font-family:'Segoe UI'; color:#0f172a; background:#ffffff;\">"
        f"<div style='color:#64748b; font-size:9pt;'>{esc(center_name or '')}</div>"
        f"<div style='font-size:16pt; font-weight:700; color:#0f766e;'>{esc(title)}</div>"
        f"<div style='color:#64748b; font-size:9pt;'>{esc(APP_NAME)} — الإصدار "
        f"{esc(APP_VERSION)} · {esc(accounts_label(len(credentials)))}</div>"
        "<hr>"
        "<table width='100%' border='1' cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse; border-color:#cbd5e1;'>"
        f"{meta_rows}</table>"
        "<p><b>الحسابات وكلمات المرور</b></p>"
        "<table width='100%' border='1' cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse; border-color:#cbd5e1;'>"
        "<tr bgcolor='#0f172a'><td align='center'><font color='#ffffff'><b>نوع الحساب</b></font></td>"
        "<td align='center'><font color='#ffffff'><b>اسم المستخدم</b></font></td>"
        "<td align='center'><font color='#ffffff'><b>كلمة المرور</b></font></td></tr>"
        f"{rows}</table>"
        "<table width='100%' cellspacing='0' cellpadding='8' bgcolor='#fff7ed' "
        "style='margin-top:10px;'><tr><td><font color='#7c2d12'>"
        "<b>تنبيه:</b> كلمات المرور لا تُعرض مرة أخرى بعد إغلاق هذه الشاشة. "
        "اطبعها وسلّم كل حساب لصاحبه.</font></td></tr></table>"
        "<p style='color:#64748b; font-size:9pt;'>هذه معاينة فقط؛ صفحة الطباعة تُفتح في "
        "المتصفح بمقاس A4.</p></div>"
    )


def table_page(title: str, headers: list[str], rows: list[list], *, subtitle: str = "",
               center_name: str = "", brand_left: str = "", auto_print: bool = False) -> str:
    """تقرير جدولي جاهز للطباعة (قوائم المؤسسات والمستخدمين وغيرها)."""
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows)
    if not body_rows:
        body_rows = f"<tr><td colspan='{len(headers)}'>لا توجد سجلات</td></tr>"
    body = (
        f"<table class='report'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body_rows}</tbody></table>"
        f"<p class='subtitle'>عدد السجلات: {len(rows)}</p>"
    )
    return page(title, body, subtitle=subtitle, brand_right=center_name,
                brand_left=brand_left or "تقرير مطبوع من النظام", auto_print=auto_print)


def add_auto_print(document: str) -> str:
    """يضيف بدء الطباعة تلقائياً عند فتح الملف في المتصفح."""
    if "window.addEventListener('load'" in document:
        return document
    return document.replace("</body>", _AUTO_PRINT + "\n</body>")


def save(content: str, reports_dir: Path | str, filename: str) -> Path:
    folder = Path(reports_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_filename(filename, "report")
    if not path.suffix:
        path = path.with_suffix(".html")
    path.write_text(content, encoding="utf-8")
    return path


def open_in_browser(path: Path | str) -> None:
    try:
        webbrowser.open(Path(path).resolve().as_uri())
    except Exception:  # pragma: no cover - بيئة بلا متصفح
        pass
