"""كتاب شكر: الإنشاء بالأنماط الخمسة، المعاينة، العرض، والطباعة."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from ..exporters import html as H
from ..server.client import ApiClient, ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_attachments import AttachmentsDialog
from .notify import error, info

MODES = [("جميع الموظفين", "all"), ("الإناث فقط", "females"), ("مؤسسة واحدة", "unit"),
         ("عناوين وظيفية محددة", "titles"), ("أشخاص محددون", "specific")]
ISSUERS = [("رئيس الجمهورية", "president"), ("رئيس الوزراء", "prime_minister"),
           ("الوزير المختص", "minister"), ("رئيس جهة غير مرتبطة بوزارة", "authority_head"),
           ("الوكيل", "undersecretary"), ("المحافظ", "governor"),
           ("المدير العام", "director_general"), ("أخرى", "other")]


def _label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("Muted")
    return widget


def _date(value: str | None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    edit.setMinimumWidth(150)
    parsed = QDate.fromString(str(value or ""), "yyyy-MM-dd")
    edit.setDate(parsed if parsed.isValid() else QDate.currentDate())
    return edit


class LetterDialog(QDialog):
    def __init__(self, parent, client: ApiClient, user: dict, units: list[dict],
                 titles: list[dict], employees: list[dict]) -> None:
        super().__init__(parent)
        self.client = client
        self.user = user
        self.units = units
        self.titles = titles
        self.employees = employees
        self.result: dict | None = None
        self.preview_result: dict | None = None
        self.setWindowTitle("كتاب شكر جديد")
        self.setMinimumSize(820, 780)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("إضافة كتاب شكر", 15))

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(16, 12, 16, 12)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)
        self.issuer = QLineEdit()
        self.issuer.setPlaceholderText("اسم الجهة المانحة")
        self.issuer_type = QComboBox()
        for label, code in ISSUERS:
            self.issuer_type.addItem(label, code)
        self.letter_no = QLineEdit()
        self.letter_no.setPlaceholderText("رقم الكتاب")
        self.letter_date = _date(None)
        self.received = QLineEdit()
        self.received.setPlaceholderText("YYYY-MM-DD (اختياري)")
        self.subject = QLineEdit()
        self.notes = QLineEdit()
        form.addRow(_label("الجهة المانحة *"), self.issuer)
        form.addRow(_label("نوع الجهة"), self.issuer_type)
        form.addRow(_label("رقم الكتاب *"), self.letter_no)
        form.addRow(_label("تاريخ الكتاب"), self.letter_date)
        form.addRow(_label("تاريخ الورود"), self.received)
        form.addRow(_label("الموضوع"), self.subject)
        form.addRow(_label("ملاحظات"), self.notes)
        root.addWidget(card)

        target = W.card()
        target_layout = QVBoxLayout(target)
        target_layout.setContentsMargins(16, 12, 16, 12)
        target_layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(_label("نمط الاستهداف"))
        self.mode = QComboBox()
        for label, code in MODES:
            self.mode.addItem(label, code)
        self.mode.currentIndexChanged.connect(self._sync_mode)
        row.addWidget(self.mode, 1)
        row.addWidget(_label("التاريخ المرجعي"))
        self.reference = _date(None)
        row.addWidget(self.reference)
        target_layout.addLayout(row)

        self.unit_box = QWidget()
        unit_layout = QHBoxLayout(self.unit_box)
        unit_layout.setContentsMargins(0, 0, 0, 0)
        unit_layout.addWidget(_label("المؤسسة"))
        self.unit = QComboBox()
        for unit in self.units:
            self.unit.addItem(f"{unit['name']} ({unit['code']})", unit["unit_id"])
        unit_layout.addWidget(self.unit, 1)
        target_layout.addWidget(self.unit_box)

        self.titles_box = QWidget()
        titles_layout = QVBoxLayout(self.titles_box)
        titles_layout.setContentsMargins(0, 0, 0, 0)
        titles_layout.addWidget(_label("اختر عنواناً أو أكثر"))
        self.title_list = QListWidget()
        self.title_list.setMaximumHeight(120)
        for title in self.titles:
            item = QListWidgetItem(f"{title['name']} ({title['code']})")
            item.setData(Qt.ItemDataRole.UserRole, title["title_id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.title_list.addItem(item)
        titles_layout.addWidget(self.title_list)
        target_layout.addWidget(self.titles_box)

        self.specific_box = QWidget()
        specific_layout = QVBoxLayout(self.specific_box)
        specific_layout.setContentsMargins(0, 0, 0, 0)
        specific_layout.addWidget(_label("اختر الموظفين"))
        self.employee_list = QListWidget()
        self.employee_list.setMaximumHeight(160)
        self.employee_list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for employee in self.employees:
            item = QListWidgetItem(f"{employee['emp_no']} — {employee['full_name']} "
                                   f"({employee.get('unit_name') or ''})")
            item.setData(Qt.ItemDataRole.UserRole, employee["employee_id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.employee_list.addItem(item)
        specific_layout.addWidget(self.employee_list)
        select_row = QHBoxLayout()
        select_row.addWidget(W.button("تحديد الكل", "Ghost",
                                      lambda: self._check_all(self.employee_list, True), width=100))
        select_row.addWidget(W.button("إلغاء التحديد", "Ghost",
                                      lambda: self._check_all(self.employee_list, False), width=120))
        select_row.addStretch()
        specific_layout.addLayout(select_row)
        target_layout.addWidget(self.specific_box)
        root.addWidget(target)

        preview_card = W.card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 12, 16, 12)
        preview_row = QHBoxLayout()
        self.preview_btn = W.button("معاينة المستفيدين", "Ghost", self._preview, width=160)
        preview_row.addWidget(self.preview_btn)
        self.count_label = W.muted("لم تُجرَ معاينة بعد.")
        preview_row.addWidget(self.count_label, 1)
        preview_layout.addLayout(preview_row)
        self.preview_table = W.table(["الرقم", "الاسم", "المؤسسة", "العنوان"])
        self.preview_table.setMaximumHeight(180)
        preview_layout.addWidget(self.preview_table)
        root.addWidget(preview_card)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        self.save_btn = W.button("حفظ الكتاب وتطبيق المستفيدين", "Accent", self._save, width=250)
        self.save_btn.setEnabled(False)
        buttons.addWidget(self.save_btn)
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)
        self._sync_mode()

    # ------------------------------------------------------------------
    @staticmethod
    def _check_all(widget: QListWidget, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(widget.count()):
            widget.item(index).setCheckState(state)

    def _sync_mode(self) -> None:
        mode = self.mode.currentData()
        self.unit_box.setVisible(mode == "unit")
        self.titles_box.setVisible(mode == "titles")
        self.specific_box.setVisible(mode == "specific")
        self.popup = None
        self.save_btn.setEnabled(False)
        self.count_label.setText("لم تُجرَ معاينة بعد.")

    def _params(self) -> dict:
        mode = self.mode.currentData()
        params: dict = {}
        if mode == "unit":
            params["unit_id"] = self.unit.currentData()
        elif mode == "titles":
            params["title_ids"] = [self.title_list.item(i).data(Qt.ItemDataRole.UserRole)
                                   for i in range(self.title_list.count())
                                   if self.title_list.item(i).checkState() == Qt.CheckState.Checked]
        elif mode == "specific":
            params["employee_ids"] = [self.employee_list.item(i).data(Qt.ItemDataRole.UserRole)
                                      for i in range(self.employee_list.count())
                                      if self.employee_list.item(i).checkState() == Qt.CheckState.Checked]
        return params

    def _data(self) -> dict:
        return {
            "issuer": self.issuer.text().strip(),
            "issuer_type": self.issuer_type.currentData(),
            "letter_no": self.letter_no.text().strip(),
            "letter_date": self.letter_date.date().toString("yyyy-MM-dd"),
            "received_date": self.received.text().strip(),
            "subject": self.subject.text().strip(),
            "notes": self.notes.text().strip(),
            "target_mode": self.mode.currentData(),
            "reference_date": self.reference.date().toString("yyyy-MM-dd"),
            "target_params": self._params(),
            "unit_id": self.unit.currentData() if self.mode.currentData() == "unit" else "",
        }

    def _preview(self) -> None:
        self.error.setVisible(False)
        try:
            result = self.client.call("letters.preview", data=self._data())
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.preview_result = result
        W.fill_table(self.preview_table, [
            [row["emp_no"], row["full_name"], row.get("unit_name") or "—",
             row.get("title_name") or "—"] for row in result["employees"]], stretch_column=1)
        self.count_label.setText(f"{result['count']} موظف مطابق — "
                                 f"مستبعد {len(result['excluded'])}")
        self.save_btn.setEnabled(result["count"] > 0)

    def _save(self) -> None:
        self.error.setVisible(False)
        try:
            result = self.client.call("letters.create", data=self._data())
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.result = result
        self.accept()


class LetterViewDialog(QDialog):
    def __init__(self, parent, client: ApiClient, letter_id: str, meta: dict,
                 can_approve: bool = False, can_edit: bool = False) -> None:
        super().__init__(parent)
        self.client = client
        self.letter_id = letter_id
        self.meta = meta
        self.can_approve = can_approve
        self.can_edit = can_edit
        self.letter: dict | None = None
        self.setWindowTitle("كتاب شكر")
        self.setMinimumSize(760, 620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(8)
        self.header = W.title("كتاب شكر", 15)
        root.addWidget(self.header)
        self.info_label = W.muted("")
        root.addWidget(self.info_label)
        self.table = W.table(["الرقم", "الاسم", "المؤسسة", "العنوان", "أثر (يوم)", "الحالة"])
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        buttons = QHBoxLayout()
        self.approve_btn = W.button("اعتماد الكتاب", "Accent", self._approve, width=130)
        self.approve_btn.setVisible(can_approve)
        self.attach_btn = W.button("المرفقات", "Ghost", self._attachments, width=100)
        self.print_btn = W.button("طباعة المستفيدين", "Ghost", self._print, width=150)
        buttons.addWidget(self.approve_btn)
        buttons.addWidget(self.attach_btn)
        buttons.addWidget(self.print_btn)
        buttons.addStretch()
        buttons.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        root.addLayout(buttons)

    def refresh(self) -> None:
        try:
            self.letter = self.client.call("letters.get", letter_id=self.letter_id)["letter"]
        except ApiError as exc:
            error(self, str(exc))
            return
        letter = self.letter
        self.header.setText(f"كتاب شكر — {letter['letter_no']}")
        self.info_label.setText(
            f"الجهة: {letter['issuer']} · التاريخ: {letter['letter_date']} · "
            f"النمط: {letter['mode_label']} · الحالة: {letter['status_label']}")
        W.fill_table(self.table, [
            [row["emp_no"], row["full_name"], row.get("unit_name") or "—",
             row.get("title_name") or "—", row.get("effect_days"),
             "محتسب" if row.get("effect_state") == "computed" else "يحتاج مراجعة"]
            for row in letter["recipients"]], stretch_column=1)
        self.approve_btn.setEnabled(letter["status"] != "approved")
        self.note.setText(f"{len(letter['recipients'])} مستفيد. "
                          f"المرفقات: {len(letter.get('documents') or [])}")

    def _approve(self) -> None:
        try:
            self.client.call("letters.approve", letter_id=self.letter_id)
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _attachments(self) -> None:
        AttachmentsDialog(self, self.client, "letter", self.letter_id,
                          "مرفقات كتاب الشكر", editable=self.can_edit).exec()

    def _print(self) -> None:
        if not self.letter:
            return
        rows = [[row["emp_no"], row["full_name"], row.get("unit_name") or "",
                 row.get("title_name") or "", row.get("effect_days") or 0,
                 "محتسب" if row.get("effect_state") == "computed" else "يحتاج مراجعة"]
                for row in self.letter["recipients"]]
        document = H.table_page(
            f"مستفيدو كتاب الشكر {self.letter['letter_no']}",
            ["الرقم", "الاسم", "المؤسسة", "العنوان", "الأثر (يوم)", "الحالة"], rows,
            subtitle=f"{self.letter['issuer']} — {self.letter['letter_date']}",
            center_name=self.meta.get("center", ""))
        path = H.save(document, Path(self.meta.get("data_dir", ".")) / "reports",
                      f"كتاب_شكر_{self.letter['letter_no']}_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتحت القائمة للطباعة:\n{path}")
