"""نافذة الموظف: البيانات، السجل، والمرفقات."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QVBoxLayout,
)

from ..server.client import ApiClient, ApiError
from . import widgets as W
from .notify import info

STATUS_ITEMS = [("على الملاك", "active"), ("موقوف", "suspended"),
                ("منتهي", "ended"), ("متقاعد", "retired")]
GENDER_ITEMS = [("ذكر", "male"), ("أنثى", "female")]


def _label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("Muted")
    return widget


class EmployeeDialog(QDialog):
    def __init__(self, parent, client: ApiClient, user: dict, employee: dict | None = None,
                 units: list[dict] | None = None, titles: list[dict] | None = None,
                 assignees: list[dict] | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.user = user
        self.employee = employee
        self.units = units or []
        self.titles = titles or []
        self.assignees = assignees
        self.saved: dict | None = None
        self.setWindowTitle("تعديل موظف" if employee else "موظف جديد")
        self.setMinimumSize(720, 780)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        data = self.employee or {}
        editing = bool(self.employee)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("تعديل بيانات الموظف" if editing else "إضافة موظف", 15))

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 14, 18, 14)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)

        self.emp_no = QLineEdit(str(data.get("emp_no") or ""))
        form.addRow(_label("الرقم الوظيفي *"), self.emp_no)
        self.full_name = QLineEdit(str(data.get("full_name") or ""))
        form.addRow(_label("الاسم *"), self.full_name)

        self.unit = QComboBox()
        for unit in self.units:
            self.unit.addItem(f"{unit['name']} ({unit['code']})", unit["unit_id"])
        index = self.unit.findData(data.get("unit_id") or (self.units[0]["unit_id"]
                                                           if self.units else ""))
        self.unit.setCurrentIndex(max(0, index))
        if self.user.get("role") in {"unit_manager", "unit_editor"}:
            self.unit.setEnabled(False)
        self.unit.currentIndexChanged.connect(self._refresh_assignees)
        form.addRow(_label("المؤسسة *"), self.unit)

        self.title = QComboBox()
        for title in self.titles:
            self.title.addItem(f"{title['name']} ({title['code']})", title["title_id"])
        index = self.title.findData(data.get("job_title_id") or "")
        self.title.setCurrentIndex(max(0, index))
        form.addRow(_label("العنوان الوظيفي *"), self.title)

        row = QHBoxLayout()
        self.grade = QLineEdit(str(data.get("grade") or ""))
        self.grade.setPlaceholderText("3")
        self.stage = QLineEdit(str(data.get("stage") or ""))
        self.stage.setPlaceholderText("1")
        self.category = QLineEdit(str(data.get("category") or ""))
        self.category.setPlaceholderText("طبية / إدارية")
        row.addWidget(self.grade)
        row.addWidget(self.stage)
        row.addWidget(self.category)
        form.addRow(_label("الدرجة / المرحلة / الفئة"), row)

        self.hire = QDateEdit()
        self.hire.setCalendarPopup(True)
        self.hire.setDisplayFormat("yyyy-MM-dd")
        self.hire.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.hire.setMinimumWidth(150)
        parsed = QDate.fromString(str(data.get("hire_date") or ""), "yyyy-MM-dd")
        self.hire.setDate(parsed if parsed.isValid() else QDate.currentDate())
        form.addRow(_label("تاريخ المباشرة *"), self.hire)

        self.last_grade = QDateEdit()
        self.last_grade.setCalendarPopup(True)
        self.last_grade.setDisplayFormat("yyyy-MM-dd")
        self.last_grade.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.last_grade.setMinimumWidth(150)
        grade_date = QDate.fromString(
            str(data.get("last_grade_date") or data.get("hire_date") or ""), "yyyy-MM-dd")
        self.last_grade.setDate(grade_date if grade_date.isValid() else self.hire.date())
        form.addRow(_label("تاريخ الدرجة الحالية"), self.last_grade)

        self.last_stage = QDateEdit()
        self.last_stage.setCalendarPopup(True)
        self.last_stage.setDisplayFormat("yyyy-MM-dd")
        self.last_stage.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.last_stage.setMinimumWidth(150)
        stage_date = QDate.fromString(
            str(data.get("last_stage_date") or data.get("hire_date") or ""), "yyyy-MM-dd")
        self.last_stage.setDate(stage_date if stage_date.isValid() else self.hire.date())
        form.addRow(_label("تاريخ المرحلة الحالية"), self.last_stage)

        self.end_date = QLineEdit(str(data.get("end_date") or ""))
        self.end_date.setPlaceholderText("YYYY-MM-DD — اتركه فارغاً إن كان على الملاك")
        form.addRow(_label("تاريخ انتهاء الخدمة"), self.end_date)

        row2 = QHBoxLayout()
        self.gender = QComboBox()
        for label, code in GENDER_ITEMS:
            self.gender.addItem(label, code)
        self.gender.setCurrentIndex(0 if data.get("gender") != "female" else 1)
        self.status = QComboBox()
        for label, code in STATUS_ITEMS:
            self.status.addItem(label, code)
        status_index = next((i for i, (_l, code) in enumerate(STATUS_ITEMS)
                             if code == (data.get("status") or "active")), 0)
        self.status.setCurrentIndex(status_index)
        row2.addWidget(self.gender)
        row2.addWidget(self.status)
        form.addRow(_label("الجنس / الحالة"), row2)

        self.assigned = QComboBox()
        self.assigned.addItem("— بدون —", "")
        self.assigned_visible = self.assignees is not None
        if self.assigned_visible:
            self._refresh_assignees()
        self.assigned_label = _label("المستخدم المسؤول (الحصة)")
        form.addRow(self.assigned_label, self.assigned)
        self.assigned_label.setVisible(self.assigned_visible)
        self.assigned.setVisible(self.assigned_visible)

        self.notes = QLineEdit(str(data.get("notes") or ""))
        form.addRow(_label("ملاحظات"), self.notes)
        root.addWidget(card)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        if editing:
            history_card = W.card()
            history_layout = QVBoxLayout(history_card)
            history_layout.setContentsMargins(14, 10, 14, 10)
            history_layout.addWidget(QLabel("<b>السجل الوظيفي</b>"))
            self.history_table = W.table(["التاريخ", "الحدث", "من", "إلى", "ملاحظة"])
            self.history_table.setMaximumHeight(150)
            history_layout.addWidget(self.history_table)
            root.addWidget(history_card)

            docs_card = W.card()
            docs_layout = QVBoxLayout(docs_card)
            docs_layout.setContentsMargins(14, 10, 14, 10)
            docs_header = QHBoxLayout()
            docs_header.addWidget(QLabel("<b>المرفقات</b>"))
            docs_header.addStretch()
            docs_header.addWidget(W.button("إرفاق ملف", "Ghost", self._upload, width=110))
            docs_header.addWidget(W.button("فتح المحدد", "Ghost", self._open_doc, width=110))
            docs_layout.addLayout(docs_header)
            self.docs_table = W.table(["الملف", "الحجم", "تاريخ الرفع"])
            self.docs_table.setMaximumHeight(130)
            docs_layout.addWidget(self.docs_table)
            root.addWidget(docs_card)
            self._fill_history(data.get("history") or [])
            self._fill_documents(data.get("documents") or [])

        buttons = QHBoxLayout()
        save = W.button("حفظ", "Accent", self._save, width=130)
        save.setMinimumHeight(36)
        buttons.addWidget(save)
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)

    # ------------------------------------------------------------------
    def _refresh_assignees(self) -> None:
        if not self.assigned_visible:
            return
        current = self.assigned.currentData() if self.assigned.count() else ""
        self.assigned.blockSignals(True)
        self.assigned.clear()
        self.assigned.addItem("— بدون —", "")
        unit_id = self.unit.currentData()
        for person in self.assignees or []:
            if person.get("unit_id") == unit_id:
                self.assigned.addItem(
                    f"{person.get('display_name') or person['username']} ({person['username']})",
                    person["user_id"])
        index = self.assigned.findData(current)
        self.assigned.setCurrentIndex(max(0, index))
        self.assigned.blockSignals(False)
        if self.employee and self.employee.get("assigned_user_id"):
            index = self.assigned.findData(self.employee["assigned_user_id"])
            if index >= 0:
                self.assigned.setCurrentIndex(index)

    def _fill_history(self, rows: list[dict]) -> None:
        labels = {"hire": "تعيين", "transfer": "نقل", "title": "عنوان وظيفي",
                  "grade": "درجة", "stage": "مرحلة", "end": "انتهاء خدمة",
                  "archive": "أرشفة", "promotion": "ترفيع", "increment": "علاوة",
                  "تعيين": "تعيين"}
        W.fill_table(self.history_table, [
            [row.get("effective_date"), labels.get(row.get("event_type"), row.get("event_type")),
             row.get("old_value") or "—", row.get("new_value") or "—", row.get("note") or ""]
            for row in rows], stretch_column=4)

    def _fill_documents(self, rows: list[dict]) -> None:
        self.documents = rows
        W.fill_table(self.docs_table, [
            [row.get("filename"), f"{round(int(row.get('size') or 0) / 1024, 1)} KB",
             row.get("uploaded_at")] for row in rows], stretch_column=0)

    # ------------------------------------------------------------------
    def _save(self) -> None:
        self.error.setVisible(False)
        data = {
            "emp_no": self.emp_no.text().strip(),
            "full_name": self.full_name.text().strip(),
            "unit_id": self.unit.currentData(),
            "job_title_id": self.title.currentData(),
            "grade": self.grade.text().strip(),
            "stage": self.stage.text().strip(),
            "category": self.category.text().strip(),
            "hire_date": self.hire.date().toString("yyyy-MM-dd"),
            "last_grade_date": self.last_grade.date().toString("yyyy-MM-dd"),
            "last_stage_date": self.last_stage.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.text().strip(),
            "gender": self.gender.currentData(),
            "status": self.status.currentData(),
            "notes": self.notes.text().strip(),
        }
        if self.assigned_visible:
            data["assigned_user_id"] = self.assigned.currentData() or ""
        try:
            if self.employee:
                data["version"] = self.employee.get("version", 1)
                result = self.client.call("employees.update",
                                          employee_id=self.employee["employee_id"], data=data)
            else:
                result = self.client.call("employees.create", data=data)
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.saved = result["employee"]
        self.accept()

    # ------------------------------------------------------------------
    def _upload(self) -> None:
        if not self.employee:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "اختيار ملف", "", "المستندات (*.pdf *.png *.jpg *.jpeg *.tif *.tiff)")
        if not path:
            return
        try:
            content = Path(path).read_bytes()
            self.client.call("documents.upload", entity_type="employee",
                             entity_id=self.employee["employee_id"],
                             filename=Path(path).name,
                             content_b64=base64.b64encode(content).decode())
            refreshed = self.client.call("employees.get",
                                         employee_id=self.employee["employee_id"])["employee"]
            self._fill_documents(refreshed.get("documents") or [])
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)

    def _open_doc(self) -> None:
        row = W.selected_row(self.docs_table)
        documents = getattr(self, "documents", [])
        if not (0 <= row < len(documents)):
            info(self, "اختر مرفقاً أولاً.")
            return
        try:
            data = self.client.call("documents.fetch",
                                    document_id=documents[row]["document_id"])
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        target = Path(tempfile.gettempdir()) / data["filename"]
        target.write_bytes(base64.b64decode(data["content_b64"]))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
