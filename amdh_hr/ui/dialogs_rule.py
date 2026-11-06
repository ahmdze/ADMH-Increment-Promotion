"""محرر القواعد: حزمة وإصداراتها وقواعدها (بيانات فقط)."""

from __future__ import annotations

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..server.client import ApiClient, ApiError
from . import widgets as W
from .notify import error

TYPES = [("ترفيع", "promotion"), ("علاوة", "increment"), ("أثر كتاب شكر", "letter_effect")]
ISSUERS = [("رئيس الجمهورية", "president"), ("رئيس الوزراء", "prime_minister"),
           ("الوزير المختص", "minister"), ("رئيس جهة غير مرتبطة بوزارة", "authority_head"),
           ("الوكيل", "undersecretary"), ("المحافظ", "governor"),
           ("المدير العام", "director_general"), ("أخرى", "other")]


def _label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("Muted")
    return widget


def _date_edit(value: str | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    edit.setMinimumWidth(150)
    parsed = QDate.fromString(str(value or ""), "yyyy-MM-dd")
    edit.setDate(parsed if parsed.isValid() else QDate.currentDate())
    return edit


class PackageDialog(QDialog):
    def __init__(self, parent, client: ApiClient, user: dict) -> None:
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("حزمة قواعد جديدة")
        self.setMinimumWidth(520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("حزمة قواعد جديدة", 14))
        root.addWidget(W.muted("الحزمة مسودة حتى تُنشر. لا تُعدّل بعد النشر؛ أنشئ إصداراً جديداً."))
        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(16, 12, 16, 12)
        self.code = QLineEdit()
        self.code.setPlaceholderText("HR-2026-001")
        self.effective = _date_edit()
        self.note = QLineEdit()
        self.legal = QLineEdit()
        self.legal.setPlaceholderText("القانون/القرار والمادة")
        form.addRow(_label("رمز الحزمة *"), self.code)
        form.addRow(_label("تاريخ النفاذ *"), self.effective)
        form.addRow(_label("ملاحظة"), self.note)
        form.addRow(_label("السند القانوني"), self.legal)
        root.addWidget(card)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setVisible(False)
        root.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("إنشاء", "Accent", self._save, width=110))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)

    def _save(self) -> None:
        try:
            self.client.call("rules.create_package", data={
                "code": self.code.text().strip(),
                "effective_from": self.effective.date().toString("yyyy-MM-dd"),
                "note": self.note.text().strip(), "legal_source": self.legal.text().strip()})
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()


class RuleDialog(QDialog):
    def __init__(self, parent, client: ApiClient, package_id: str, titles: list[dict],
                 row: dict | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.package_id = package_id
        self.titles = titles
        self.row = row
        self.setWindowTitle("تعديل قاعدة" if row else "قاعدة جديدة")
        self.setMinimumSize(560, 560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        data = self.row or {}
        scope = data.get("scope_data") or {}
        params = data.get("params_data") or {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("قاعدة", 14))

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(16, 12, 16, 12)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.name = QLineEdit(str(data.get("name") or ""))
        form.addRow(_label("اسم القاعدة"), self.name)
        self.type = QComboBox()
        for label, code in TYPES:
            self.type.addItem(label, code)
        index = self.type.findData(data.get("rule_type") or "promotion")
        self.type.setCurrentIndex(max(0, index))
        self.type.currentIndexChanged.connect(self._sync)
        form.addRow(_label("النوع"), self.type)
        self.priority = QSpinBox()
        self.priority.setRange(1, 9999)
        self.priority.setValue(int(data.get("priority") or 100))
        form.addRow(_label("الأولوية (الأصغر أولاً)"), self.priority)
        root.addWidget(card)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._promotion_page(scope, params))
        self.stack.addWidget(self._increment_page(scope, params))
        self.stack.addWidget(self._letter_page(scope, params))
        root.addWidget(self.stack)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("حفظ القاعدة", "Accent", self._save, width=140))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)
        self._sync()

    # ------------------------------------------------------------------
    def _promotion_page(self, scope: dict, params: dict) -> QWidget:
        page = W.card()
        form = QFormLayout(page)
        form.setContentsMargins(16, 12, 16, 12)
        self.p_grade = QLineEdit(str(scope.get("grade") or ""))
        self.p_stage = QLineEdit(str(scope.get("stage") or ""))
        self.p_months = QSpinBox()
        self.p_months.setRange(1, 600)
        self.p_months.setValue(int(params.get("required_months") or 36))
        self.p_to_grade = QLineEdit(str(params.get("to_grade") or ""))
        self.p_to_stage = QLineEdit(str(params.get("to_stage") or ""))
        form.addRow(_label("الدرجة الحالية (نطاق)"), self.p_grade)
        form.addRow(_label("المرحلة الحالية (نطاق)"), self.p_stage)
        form.addRow(_label("القدم المطلوب (أشهر) *"), self.p_months)
        form.addRow(_label("الدرجة بعد الترفيع"), self.p_to_grade)
        form.addRow(_label("المرحلة بعد الترفيع"), self.p_to_stage)
        form.addRow(_label(""), W.muted("تُطابق القاعدة الموظف حسب الدرجة/المرحلة في ملفه."))
        return page

    def _increment_page(self, scope: dict, params: dict) -> QWidget:
        page = W.card()
        form = QFormLayout(page)
        form.setContentsMargins(16, 12, 16, 12)
        self.i_grade = QLineEdit(str(scope.get("grade") or ""))
        self.i_months = QSpinBox()
        self.i_months.setRange(1, 240)
        self.i_months.setValue(int(params.get("required_months") or 12))
        self.i_max_stage = QLineEdit(str(params.get("max_stage") or ""))
        form.addRow(_label("الدرجة (نطاق، اختياري)"), self.i_grade)
        form.addRow(_label("مدة العلاوة (أشهر) *"), self.i_months)
        form.addRow(_label("أعلى مرحلة (اختياري)"), self.i_max_stage)
        return page

    def _letter_page(self, scope: dict, params: dict) -> QWidget:
        page = W.card()
        form = QFormLayout(page)
        form.setContentsMargins(16, 12, 16, 12)
        self.l_issuer = QComboBox()
        for label, code in ISSUERS:
            self.l_issuer.addItem(label, code)
        index = self.l_issuer.findData(scope.get("issuer_type") or "director_general")
        self.l_issuer.setCurrentIndex(max(0, index))
        self.l_title = QComboBox()
        self.l_title.addItem("كل العناوين", "")
        for title in self.titles:
            self.l_title.addItem(f"{title['name']} ({title['code']})", title["code"])
        index = self.l_title.findData(scope.get("job_title") or "")
        self.l_title.setCurrentIndex(max(0, index))
        self.l_days = QSpinBox()
        self.l_days.setRange(0, 3650)
        self.l_days.setValue(int(params.get("days") or 30))
        self.l_cap = QSpinBox()
        self.l_cap.setRange(0, 3650)
        self.l_cap.setValue(int(params.get("cap_days") or 0))
        form.addRow(_label("الجهة المانحة *"), self.l_issuer)
        form.addRow(_label("العنوان الوظيفي (نطاق)"), self.l_title)
        form.addRow(_label("الأثر (أيام) *"), self.l_days)
        form.addRow(_label("سقف الأثر (0 = بلا سقف)"), self.l_cap)
        return page

    def _sync(self) -> None:
        self.stack.setCurrentIndex(self.type.currentIndex())

    # ------------------------------------------------------------------
    def _save(self) -> None:
        rule_type = self.type.currentData()
        scope: dict = {}
        params: dict = {}
        if rule_type == "promotion":
            if self.p_grade.text().strip():
                scope["grade"] = self.p_grade.text().strip()
            if self.p_stage.text().strip():
                scope["stage"] = self.p_stage.text().strip()
            params = {"required_months": self.p_months.value(),
                      "to_grade": self.p_to_grade.text().strip(),
                      "to_stage": self.p_to_stage.text().strip()}
        elif rule_type == "increment":
            if self.i_grade.text().strip():
                scope["grade"] = self.i_grade.text().strip()
            params = {"required_months": self.i_months.value(),
                      "max_stage": self.i_max_stage.text().strip()}
        else:
            scope = {"issuer_type": self.l_issuer.currentData()}
            if self.l_title.currentData():
                scope["job_title"] = self.l_title.currentData()
            params = {"days": self.l_days.value(), "cap_days": self.l_cap.value()}
        data = {"rule_type": rule_type, "name": self.name.text().strip(),
                "scope": scope, "params": params, "priority": self.priority.value()}
        if self.row:
            data["rule_id"] = self.row["rule_id"]
        try:
            self.client.call("rules.save_row", package_id=self.package_id, data=data)
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()
