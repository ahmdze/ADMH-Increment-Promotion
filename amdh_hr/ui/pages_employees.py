"""صفحة الموظفين: البحث، الإضافة، التوزيع، والاستيراد/التصدير."""

from __future__ import annotations

import base64
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QVBoxLayout,
)

from ..server.client import ApiError
from . import widgets as W
from .dialogs_employee import EmployeeDialog
from .dialogs_titles import TitlesDialog
from .notify import confirm, error, info
from .pages_base import BasePage


class EmployeesPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        self.add_btn = W.button("موظف جديد", "Accent", self._add, width=130)
        self.titles_btn = W.button("العناوين الوظيفية", "Ghost", self._titles, width=150)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "الموظفون", "السجل الوظيفي، العنوان التاريخي، والتوزيع على المستخدمين",
            [self.add_btn, self.titles_btn, self.refresh_btn]))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.edit_btn = W.button("تعديل", "Ghost", self._edit, width=90)
        self.assign_btn = W.button("توزيع المحدد", "Ghost", self._assign, width=120)
        self.archive_btn = W.button("أرشفة", "Danger", self._archive, width=80)
        self.excel_btn = W.button("Excel", "Ghost", None, width=90)
        self.excel_menu = QMenu(self.excel_btn)
        self.excel_menu.addAction("استيراد من Excel", self._import)
        self.excel_menu.addAction("تصدير إلى Excel", self._export)
        self.excel_menu.addAction("تنزيل القالب", self._template)
        self.excel_btn.setMenu(self.excel_menu)
        for button in (self.edit_btn, self.assign_btn, self.archive_btn, self.excel_btn):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.unit_filter = QComboBox()
        self.unit_filter.setFixedWidth(190)
        self.unit_filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.unit_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الرقم…")
        self.search.setFixedWidth(210)
        self.search.textChanged.connect(self._schedule)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)

        self.table = W.table(["الرقم", "الاسم", "العنوان الوظيفي", "الدرجة/المرحلة",
                              "المؤسسة", "الحالة", "المسؤول"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.doubleClicked.connect(lambda _index: self._edit())
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)

        self.employees: list[dict] = []
        self.units: list[dict] = []
        self.titles: list[dict] = []
        self.assignees: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self.add_btn.setVisible(self.can("edit_employee"))
        self.titles_btn.setVisible(self.can("edit_rules"))
        self.edit_btn.setVisible(self.can("edit_employee"))
        self.archive_btn.setVisible(self.can("delete_employee"))
        self.assign_btn.setVisible(self.can("assign_employees"))
        self.excel_btn.setVisible(self.can("edit_employee") or self.can("export_reports"))
        self._sync()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            if not self.units:
                self.units = self.client.call("units.list")["units"]
                self.unit_filter.blockSignals(True)
                self.unit_filter.addItem("كل المؤسسات", "")
                for unit in self.units:
                    self.unit_filter.addItem(unit["name"], unit["unit_id"])
                self.unit_filter.blockSignals(False)
                self.unit_filter.setVisible("manage_units" in (self.user.get("permissions") or []))
            self.titles = self.client.call("titles.list", active_only=True)["titles"]
            if self.can("assign_employees"):
                self.assignees = self.client.call("employees.assignable_users")["users"]
            self.employees = self.client.call(
                "employees.list", search=self.search.text().strip(),
                unit_id=self.unit_filter.currentData() or "")["employees"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        W.fill_table(self.table, [
            [row["emp_no"], row["full_name"], row.get("title_name") or "—",
             f"{row.get('grade') or '—'} / {row.get('stage') or '—'}",
             row.get("unit_name") or "—", row.get("status_label"),
             row.get("assigned_name") or row.get("assigned_username") or "—"]
            for row in self.employees], stretch_column=1)
        self.note.setText(f"{len(self.employees)} موظف — التوزيع على المستخدمين يحدد من يرى الملف.")
        self._sync()

    def _schedule(self) -> None:
        self._timer.start()

    def _selected(self) -> list[dict]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.employees[row] for row in rows if 0 <= row < len(self.employees)]

    def _sync(self) -> None:
        selected = self._selected()
        self.edit_btn.setEnabled(len(selected) == 1)
        self.assign_btn.setEnabled(bool(selected))
        self.archive_btn.setEnabled(len(selected) == 1)

    # ------------------------------------------------------------------
    def _add(self) -> None:
        if not self.titles:
            info(self, "أضف عنواناً وظيفياً واحداً على الأقل قبل إضافة الموظفين.")
            return
        dialog = EmployeeDialog(self, self.client, self.user, units=self.units,
                                titles=self.titles, assignees=self.assignees
                                if self.can("assign_employees") else None)
        if dialog.exec():
            self.refresh()

    def _edit(self) -> None:
        selected = self._selected()
        if len(selected) != 1:
            return
        try:
            employee = self.client.call(
                "employees.get", employee_id=selected[0]["employee_id"])["employee"]
        except ApiError as exc:
            error(self, str(exc))
            return
        dialog = EmployeeDialog(self, self.client, self.user, employee=employee,
                                units=self.units, titles=self.titles,
                                assignees=self.assignees if self.can("assign_employees") else None)
        if dialog.exec():
            self.refresh()

    def _titles(self) -> None:
        TitlesDialog(self, self.client, editable=self.can("edit_rules")).exec()
        self.refresh()

    def _archive(self) -> None:
        selected = self._selected()
        if len(selected) != 1:
            return
        employee = selected[0]
        if not confirm(self, f"أرشفة ملف «{employee['full_name']}»؟ يمكن استعادته من قاعدة البيانات "
                             "لكنه سيختفي من القوائم."):
            return
        try:
            self.client.call("employees.archive", employee_id=employee["employee_id"],
                             reason="أرشفة يدوية")
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _assign(self) -> None:
        selected = self._selected()
        if not selected:
            return
        units = {row["unit_id"] for row in selected}
        if len(units) > 1:
            error(self, "اختر موظفين من مؤسسة واحدة في كل عملية توزيع.")
            return
        unit_id = selected[0]["unit_id"]
        try:
            people = self.client.call("employees.assignable_users",
                                      unit_id=unit_id)["users"]
        except ApiError as exc:
            error(self, str(exc))
            return
        if not people:
            info(self, "لا يوجد مدخلو بيانات في هذه المؤسسة.")
            return
        dialog = AssignDialog(self, people, len(selected))
        if dialog.exec():
            target = dialog.selected_user()
            if not target:
                return
            try:
                result = self.client.call(
                    "employees.assign", employee_ids=[row["employee_id"] for row in selected],
                    target_user_id=target)
            except ApiError as exc:
                error(self, str(exc))
                return
            info(self, f"تم توزيع {result['assigned']} موظف على {result['target']}.")
            self.refresh()

    # ------------------------------------------------------------------
    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "ملف Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            content = Path(path).read_bytes()
            result = self.client.call(
                "employees.import", content_b64=base64.b64encode(content).decode(),
                update_existing=True)
        except ApiError as exc:
            error(self, str(exc))
            return
        message = (f"أُضيف: {result['added']} — حُدّث: {result['updated']} — "
                   f"تُخطي: {result['skipped']}")
        if result.get("errors"):
            message += "\n\nأول الأخطاء:\n" + "\n".join(result["errors"][:8])
        info(self, message, "استيراد الموظفين")
        self.refresh()

    def _export(self) -> None:
        try:
            path = self.client.call("employees.export")["path"]
        except ApiError as exc:
            error(self, str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        info(self, f"حُفظ الملف:\n{path}")

    def _template(self) -> None:
        try:
            path = self.client.call("employees.template")["path"]
        except ApiError as exc:
            error(self, str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        info(self, f"حُفظ القالب:\n{path}")


class AssignDialog(QDialog):
    def __init__(self, parent, people: list[dict], count: int) -> None:
        super().__init__(parent)
        self.people = people
        self.setWindowTitle("توزيع الموظفين")
        self.setMinimumWidth(440)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("توزيع الموظفين", 14))
        root.addWidget(W.muted(f"سيُنسب {count} موظف إلى المستخدم المختار."))
        self.combo = QComboBox()
        for person in people:
            self.combo.addItem(f"{person.get('display_name') or person['username']} "
                               f"({person['username']})", person["user_id"])
        root.addWidget(self.combo)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("توزيع", "Accent", self.accept, width=100))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)

    def selected_user(self) -> str:
        return self.combo.currentData() or ""
