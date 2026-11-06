"""صفحة الاحتساب الاسترشادي."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
)

from ..exporters import html as H
from ..server.client import ApiError
from ..util import stamp
from . import widgets as W
from .notify import error, info
from .pages_base import BasePage
from .pdf_viewer import view_attachment


class CalcPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(W.page_header(
            "الاحتساب", "نتيجة استرشادية: الخدمة + أثر كتب الشكر + قواعد الترفيع والعلاوة"))

        card = W.card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)
        first = QHBoxLayout()
        first.addWidget(QLabel("الموظف"))
        self.employee = QComboBox()
        first.addWidget(self.employee, 1)
        card_layout.addLayout(first)
        second = QHBoxLayout()
        second.addWidget(QLabel("بتاريخ"))
        self.as_of = QDateEdit()
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("yyyy-MM-dd")
        self.as_of.setMinimumWidth(200)
        self.as_of.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.as_of.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.as_of.setDate(QDate.currentDate())
        second.addWidget(self.as_of)
        second.addWidget(QLabel("عند التعادل"))
        self.tie_policy = QComboBox()
        self.tie_policy.addItem("الترفيع أولاً", "promotion")
        self.tie_policy.addItem("العلاوة أولاً", "increment")
        second.addWidget(self.tie_policy)
        self.run_btn = W.button("احتساب", "Accent", self._run, width=110)
        self.pdf_btn = W.button("تصدير PDF", "Ghost", self._pdf, width=120)
        self.print_btn = W.button("طباعة النتيجة", "Ghost", self._print, width=140)
        self.pdf_btn.setEnabled(False)
        self.print_btn.setEnabled(False)
        second.addWidget(self.run_btn)
        second.addWidget(self.pdf_btn)
        second.addWidget(self.print_btn)
        second.addStretch()
        card_layout.addLayout(second)
        root.addWidget(card)

        self.result = QTextBrowser()
        self.result.setStyleSheet(
            "QTextBrowser { background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1;"
            " border-radius: 8px; padding: 8px; }")
        self.result.setHtml("<div dir='rtl' style='font-family:Segoe UI; padding:12px;'>"
                            "اختر موظفاً ثم اضغط «احتساب».</div>")
        root.addWidget(self.result, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        self.employees: list[dict] = []
        self.data: dict | None = None

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self.employees = self.client.call("employees.list", limit=2000)["employees"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        current = self.employee.currentData()
        self.employee.blockSignals(True)
        self.employee.clear()
        for row in self.employees:
            self.employee.addItem(f"{row['emp_no']} — {row['full_name']} "
                                  f"({row.get('unit_name') or ''})", row["employee_id"])
        index = self.employee.findData(current)
        self.employee.setCurrentIndex(max(0, index))
        self.employee.blockSignals(False)
        self.note.setText(f"{len(self.employees)} موظف متاح. النتيجة استرشادية ولا تُعد قراراً.")

    def _run(self) -> None:
        employee_id = self.employee.currentData()
        if not employee_id:
            info(self, "اختر موظفاً أولاً.")
            return
        try:
            self.data = self.client.call(
                "calc.employee", employee_id=employee_id,
                as_of=self.as_of.date().toString("yyyy-MM-dd"),
                tie_policy=self.tie_policy.currentData())
        except ApiError as exc:
            error(self, str(exc))
            return
        self.result.setHtml(_result_html(self.data))
        self.pdf_btn.setEnabled(True)
        self.print_btn.setEnabled(True)

    def _pdf(self) -> None:
        employee_id = self.employee.currentData()
        if not employee_id:
            info(self, "اختر موظفاً أولاً.")
            return
        try:
            result = self.client.call(
                "calc.export_pdf", employee_id=employee_id,
                as_of=self.as_of.date().toString("yyyy-MM-dd"),
                tie_policy=self.tie_policy.currentData())
        except ApiError as exc:
            error(self, str(exc))
            return
        view_attachment(self, Path(result["path"]), "نتيجة الاحتساب PDF")

    def _print(self) -> None:
        if not self.data:
            return
        body = _result_html(self.data, for_print=True)
        document = H.page(f"نتيجة احتساب — {self.data['employee']['full_name']}", body,
                          subtitle=f"بتاريخ {self.data['as_of']}",
                          brand_right=self.meta.get("center", ""),
                          brand_left="نتيجة استرشادية — لا تُعد قراراً إدارياً")
        path = H.save(document, Path(self.meta.get("data_dir", ".")) / "reports",
                      f"احتساب_{self.data['employee']['emp_no']}_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتحت النتيجة للطباعة:\n{path}")


def _row(label: str, value: str) -> str:
    return (f"<tr><td width='38%' bgcolor='#f1f5f9'><b>{H.esc(label)}</b></td>"
            f"<td>{H.esc(value)}</td></tr>")


def _result_html(result: dict, for_print: bool = False) -> str:
    employee = result["employee"]
    service = result["service"]
    letters = result["letters"]
    promotion = result["promotion"]
    increment = result["increment"]
    package = result.get("package") or {}
    rows = [
        _row("الموظف", f"{employee['full_name']} — {employee['emp_no']}"),
        _row("المؤسسة / العنوان", f"{employee.get('unit_name') or '—'} / "
                                  f"{employee.get('title_name') or '—'}"),
        _row("الدرجة / المرحلة", f"{employee.get('grade') or '—'} / "
                                 f"{employee.get('stage') or '—'}"),
        _row("تاريخ المباشرة", employee["hire_date"]),
        _row("الخدمة", f"{service['years']} سنة و{service['months']} شهراً و"
                       f"{service['days_remainder']} يوماً ({service['days']} يوماً)"),
        _row("أثر كتب الشكر", f"{letters['months']} شهراً ({letters['count']} سجل)"),
        _row("مجموع القدم", f"{result['seniority']['months']} شهراً "
                            f"({result['seniority']['years']} سنة و"
                            f"{result['seniority']['remaining_months']} شهراً)"),
    ]
    if promotion.get("state") == "computed":
        rows.append(_row("الترفيع", ("مستوفٍ" if promotion.get("eligible") else "غير مستوفٍ")
                         + f" — الاستحقاق {promotion.get('eligible_date')} "
                           f"(خصم {promotion.get('credit_months', 0)} شهراً)"))
    else:
        rows.append(_row("الترفيع", "لا توجد قاعدة مطابقة"))
    if increment.get("state") == "computed":
        rows.append(_row("العلاوة", f"الاستحقاق {increment.get('eligible_date')} — "
                                    f"القادم {increment.get('next_date')} "
                                    f"(خصم {increment.get('credit_months', 0)} شهراً)"))
    else:
        rows.append(_row("العلاوة", "لا توجد قاعدة مطابقة"))
    rows.append(_row("حزمة القواعد", f"{package.get('code', '—')} إصدار "
                                    f"{package.get('version', '—')}" if package else "غير محددة"))

    warnings = "".join(f"<li>{H.esc(item)}</li>" for item in result["warnings"])
    warning_html = (f"<div style='background:#fff7ed; border:1px solid #fb923c; padding:8px; "
                    f"margin-top:10px;'><b>تنبيهات:</b><ul>{warnings}</ul></div>"
                    if warnings else "")
    state = ("استرشادية بمحرك القواعد" if result["state"] == "estimated"
             else "تحتاج حزمة قواعد معتمدة")
    return (
        "<div dir='rtl' style=\"font-family:'Segoe UI'; color:#0f172a;\">"
        f"<div style='font-size:15pt; font-weight:700; color:#0f766e;'>نتيجة الاحتساب</div>"
        f"<div style='color:#64748b; font-size:9pt;'>بتاريخ {H.esc(result['as_of'])} — "
        f"{H.esc(state)}</div><hr>"
        "<table width='100%' border='1' cellspacing='0' cellpadding='6' "
        f"style='border-collapse:collapse; border-color:#cbd5e1;'>{''.join(rows)}</table>"
        f"{warning_html}"
        "<p style='color:#64748b; font-size:9pt; margin-top:10px;'>هذه النتيجة استرشادية "
        "ولا تُعد قراراً إدارياً معتمداً؛ تعتمدها الجهة المخولة وفق الأصول.</p></div>"
    )
