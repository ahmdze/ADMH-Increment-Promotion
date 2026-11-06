"""أوامر الترفيع والعلاوة: الإنشاء والعرض والطباعة."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ..exporters import html as H
from ..server.client import ApiClient, ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_attachments import AttachmentsDialog
from .notify import error, info

TYPES = [("ترفيع", "promotion"), ("علاوة", "increment"), ("أخرى", "other")]


def _label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("Muted")
    return widget


def _date() -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    edit.setMinimumWidth(150)
    edit.setDate(QDate.currentDate())
    return edit


class OrderDialog(QDialog):
    def __init__(self, parent, client: ApiClient, user: dict, units: list[dict],
                 employees: list[dict]) -> None:
        super().__init__(parent)
        self.client = client
        self.user = user
        self.units = units
        self.employees = employees
        self.result: dict | None = None
        self.setWindowTitle("أمر جديد")
        self.setMinimumSize(720, 680)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("إضافة أمر ترفيع/علاوة", 15))
        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(16, 12, 16, 12)
        self.order_type = QComboBox()
        for label, code in TYPES:
            self.order_type.addItem(label, code)
        self.order_no = QLineEdit()
        self.issuer = QLineEdit()
        self.order_date = _date()
        self.effective = _date()
        self.notes = QLineEdit()
        self.unit = QComboBox()
        for unit in self.units:
            self.unit.addItem(unit["name"], unit["unit_id"])
        self.apply_mode = QComboBox()
        self.apply_mode.addItem("تلقائي (التالي)", "auto")
        self.apply_mode.addItem("قيم محددة", "fixed")
        self.to_grade = QLineEdit()
        self.to_grade.setPlaceholderText("الدرجة المستهدفة")
        self.to_stage = QLineEdit()
        self.to_stage.setPlaceholderText("المرحلة المستهدفة")
        self.order_type.currentIndexChanged.connect(self._sync_apply)
        self.apply_mode.currentIndexChanged.connect(self._sync_apply)
        form.addRow(_label("النوع"), self.order_type)
        form.addRow(_label("رقم الأمر *"), self.order_no)
        form.addRow(_label("الجهة المصدرة"), self.issuer)
        form.addRow(_label("تاريخ الأمر"), self.order_date)
        form.addRow(_label("تاريخ السريان"), self.effective)
        form.addRow(_label("المؤسسة"), self.unit)
        self.apply_label = _label("طريقة التطبيق")
        form.addRow(self.apply_label, self.apply_mode)
        self.target_label = _label("الدرجة / المرحلة المستهدفة")
        targets_row = QHBoxLayout()
        targets_row.addWidget(self.to_grade)
        targets_row.addWidget(self.to_stage)
        form.addRow(self.target_label, targets_row)
        self.apply_hint = W.muted("")
        form.addRow(_label(""), self.apply_hint)
        form.addRow(_label("ملاحظات"), self.notes)
        root.addWidget(card)

        choose = W.card()
        choose_layout = QVBoxLayout(choose)
        choose_layout.setContentsMargins(16, 12, 16, 12)
        header = QHBoxLayout()
        header.addWidget(_label("الموظفون المستفيدون"))
        header.addStretch()
        header.addWidget(W.button("تحديد الكل", "Ghost",
                                  lambda: self._check_all(True), width=100))
        header.addWidget(W.button("إلغاء", "Ghost", lambda: self._check_all(False), width=80))
        choose_layout.addLayout(header)
        self.employee_list = QListWidget()
        for employee in self.employees:
            item = QListWidgetItem(f"{employee['emp_no']} — {employee['full_name']} "
                                   f"({employee.get('unit_name') or ''})")
            item.setData(Qt.ItemDataRole.UserRole, employee["employee_id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.employee_list.addItem(item)
        choose_layout.addWidget(self.employee_list, 1)
        root.addWidget(choose, 1)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("حفظ الأمر", "Accent", self._save, width=150))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)
        self._sync_apply()

    def _sync_apply(self) -> None:
        kind = self.order_type.currentData()
        other = kind == "other"
        fixed = self.apply_mode.currentData() == "fixed"
        for widget in (self.apply_label, self.apply_mode, self.target_label,
                       self.to_grade, self.to_stage):
            widget.setVisible(not other)
        self.to_grade.setEnabled(fixed and kind == "promotion")
        self.to_stage.setEnabled(fixed and kind in {"promotion", "increment"})
        if other:
            self.apply_hint.setText("")
        elif fixed:
            self.apply_hint.setText("تُطبّق القيم نفسها على كل المستفيدين عند الاعتماد.")
        elif kind == "promotion":
            self.apply_hint.setText("سيُرفَّع كل موظف إلى الدرجة التالية والمرحلة 1 عند الاعتماد.")
        else:
            self.apply_hint.setText("سينتقل كل موظف إلى المرحلة التالية عند الاعتماد.")

    def _check_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.employee_list.count()):
            self.employee_list.item(index).setCheckState(state)

    def _save(self) -> None:
        ids = [self.employee_list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self.employee_list.count())
               if self.employee_list.item(i).checkState() == Qt.CheckState.Checked]
        data = {
            "order_type": self.order_type.currentData(), "order_no": self.order_no.text().strip(),
            "issuer": self.issuer.text().strip(),
            "order_date": self.order_date.date().toString("yyyy-MM-dd"),
            "effective_date": self.effective.date().toString("yyyy-MM-dd"),
            "notes": self.notes.text().strip(), "unit_id": self.unit.currentData(),
            "apply_mode": self.apply_mode.currentData(),
            "to_grade": self.to_grade.text().strip() if self.to_grade.isEnabled() else "",
            "to_stage": self.to_stage.text().strip() if self.to_stage.isEnabled() else "",
            "employee_ids": ids,
        }
        try:
            self.result = self.client.call("orders.create", data=data)["order"]
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()


class OrderViewDialog(QDialog):
    def __init__(self, parent, client: ApiClient, order_id: str, meta: dict,
                 can_approve: bool, can_edit: bool) -> None:
        super().__init__(parent)
        self.client = client
        self.order_id = order_id
        self.meta = meta
        self.can_approve = can_approve
        self.can_edit = can_edit
        self.order: dict | None = None
        self.setWindowTitle("أمر")
        self.setMinimumSize(720, 560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(8)
        self.header = W.title("أمر", 15)
        root.addWidget(self.header)
        self.info = W.muted("")
        root.addWidget(self.info)
        self.table = W.table(["الرقم", "الاسم", "المؤسسة"])
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        buttons = QHBoxLayout()
        self.approve_btn = W.button("اعتماد", "Accent", self._approve, width=100)
        self.approve_btn.setVisible(can_approve)
        self.attach_btn = W.button("المرفقات", "Ghost", self._attachments, width=100)
        self.print_btn = W.button("طباعة", "Ghost", self._print, width=90)
        buttons.addWidget(self.approve_btn)
        buttons.addWidget(self.attach_btn)
        buttons.addWidget(self.print_btn)
        buttons.addStretch()
        buttons.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        root.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.order = self.client.call("orders.get", order_id=self.order_id)["order"]
        except ApiError as exc:
            error(self, str(exc))
            return
        order = self.order
        self.header.setText(f"{order['type_label']} — {order['order_no']}")
        mode = "تلقائي" if order.get("apply_mode") == "auto" else "قيم محددة"
        target = f" · الهدف: {order.get('to_grade') or '—'}/{order.get('to_stage') or '—'}" \
            if mode == "قيم محددة" else ""
        applied = f" · طُبّق في {order['applied_at']}" if order.get("applied_at") else ""
        self.info.setText(f"التاريخ: {order['order_date']} · السريان: {order['effective_date']} · "
                          f"الجهة: {order['issuer'] or '—'} · الحالة: {order['status_label']} · "
                          f"التطبيق: {mode}{target}{applied}")
        W.fill_table(self.table, [[row["emp_no"], row["full_name"],
                                   row.get("unit_name") or "—"]
                                  for row in order["recipients"]], stretch_column=1)
        self.note.setText(f"{len(order['recipients'])} موظف. المرفقات: "
                          f"{len(order.get('documents') or [])}")
        self.approve_btn.setEnabled(order["status"] != "approved")

    def _approve(self) -> None:
        try:
            self.client.call("orders.approve", order_id=self.order_id)
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _attachments(self) -> None:
        AttachmentsDialog(self, self.client, "order", self.order_id, "مرفقات الأمر",
                          editable=self.can_edit).exec()

    def _print(self) -> None:
        if not self.order:
            return
        rows = [[row["emp_no"], row["full_name"], row.get("unit_name") or ""]
                for row in self.order["recipients"]]
        document = H.table_page(
            f"{self.order['type_label']} {self.order['order_no']}",
            ["الرقم", "الاسم", "المؤسسة"], rows,
            subtitle=f"تاريخ الأمر {self.order['order_date']} — السريان "
                     f"{self.order['effective_date']}",
            center_name=self.meta.get("center", ""))
        path = H.save(document, Path(self.meta.get("data_dir", ".")) / "reports",
                      f"أمر_{self.order['order_no']}_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتح الأمر للطباعة:\n{path}")
