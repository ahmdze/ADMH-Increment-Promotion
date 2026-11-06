"""لوحة المؤشرات."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ..server.client import ApiError
from . import widgets as W
from .pages_base import BasePage


class DashboardPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(W.page_header(
            "لوحة المؤشرات", "نظرة سريعة على المؤسسات والحسابات وحالة النظام"))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.values: dict[str, QLabel] = {}
        cards = [("units", "المؤسسات", "مؤسسات مسجلة في الدائرة"),
                 ("users", "المستخدمون", "حسابات نشطة"),
                 ("employees", "الموظفون", "سيُفعَّل في المرحلة 2"),
                 ("backups", "النسخ الاحتياطية", "نسخ محفوظة ومفحوصة")]
        for column, (key, title, note) in enumerate(cards):
            frame, value = _stat(title, note)
            self.values[key] = value
            grid.addWidget(frame, 0, column)
        root.addLayout(grid)

        actions = W.card()
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(18, 14, 18, 14)
        actions_layout.setSpacing(10)
        title = QLabel("إجراءات سريعة")
        title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        actions_layout.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(8)
        if self.can("manage_units"):
            row.addWidget(W.button("مؤسسة جديدة", "Accent", self._open_new_unit))
        if self.can("backup_restore"):
            row.addWidget(W.button("نسخة احتياطية الآن", "Ghost", self._backup))
        row.addWidget(W.button("تحديث", "Ghost", self.refresh))
        row.addStretch()
        actions_layout.addLayout(row)
        root.addWidget(actions)

        phase = W.card()
        phase_layout = QVBoxLayout(phase)
        phase_layout.setContentsMargins(18, 14, 18, 14)
        phase_layout.setSpacing(6)
        heading = QLabel("المرحلة الحالية: الأساس والمؤسسات والمستخدمون")
        heading.setStyleSheet("font-weight: 700; font-size: 11pt;")
        phase_layout.addWidget(heading)
        phase_layout.addWidget(W.muted(
            "منفّذ: خدمة محلية متعددة المستخدمين، دخول إلزامي، أربعة أدوار، إنشاء مؤسسة "
            "بحساباتها تلقائياً، بطاقة دخول HTML للطباعة، تصفير كلمات المرور، نسخ احتياطي، "
            "وتجهيز نسخة المؤسسة."))
        phase_layout.addWidget(W.muted(
            "التالي (المرحلة 2): ملف الموظف والعنوان الوظيفي التاريخي، السجل الوظيفي، "
            "مخزن الوثائق، عارض المرفقات، وتوزيع الموظفين على المستخدمين."))
        root.addWidget(phase)
        root.addStretch()
        self.note = W.muted("")
        root.addWidget(self.note)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            units = self.client.call("units.list").get("units", [])
            self.values["units"].setText(str(len(units)))
            self.values["employees"].setText(
                str(sum(int(unit.get("employees_count") or 0) for unit in units)))
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        if self.can("manage_users"):
            try:
                users = self.client.call("users.list").get("users", [])
                self.values["users"].setText(str(sum(1 for u in users if u.get("active"))))
            except ApiError:
                self.values["users"].setText("—")
        else:
            self.values["users"].setText("—")
        if self.can("backup_restore"):
            try:
                backups = self.client.call("backup.list").get("backups", [])
                self.values["backups"].setText(str(len(backups)))
            except ApiError:
                self.values["backups"].setText("—")
        else:
            self.values["backups"].setText("—")
        self.note.setText("")

    # ------------------------------------------------------------------
    def _backup(self) -> None:
        from .notify import error, info
        try:
            result = self.client.call("backup.run")
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"تم إنشاء النسخة:\n{result.get('path')}")
        self.refresh()

    def _open_new_unit(self) -> None:
        from ..exporters import html as H
        from .dialogs_credentials import CredentialsDialog
        from .dialogs_units import UnitDialog
        from .util_ui import copy_credentials
        dialog = UnitDialog(self, self.client, reports_dir=self.reports_dir,
                            center_name=self.meta.get("center", ""),
                            center_exists=bool(self.meta.get("center")))
        if not dialog.exec() or not dialog.saved:
            return
        unit = dialog.saved
        if dialog.credentials:
            center = self.meta.get("center", "")
            page = H.credentials_page(unit, dialog.credentials, center_name=center)
            preview = H.credentials_preview(unit, dialog.credentials, center_name=center)
            CredentialsDialog(
                self, page, reports_dir=self.reports_dir,
                filename=f"بيانات_دخول_{unit.get('code') or 'unit'}",
                copy_text=copy_credentials(unit, dialog.credentials),
                title="بيانات دخول المؤسسة", preview_html=preview).exec()
        window = self.window()
        if hasattr(window, "refresh_all"):
            window.refresh_all()


def _stat(title: str, note: str) -> tuple[QFrame, QLabel]:
    frame = W.card()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(2)
    name = QLabel(title)
    name.setObjectName("Subtitle")
    value = QLabel("—")
    value.setStyleSheet("font-size: 26pt; font-weight: 800;")
    value.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(name)
    layout.addWidget(value)
    layout.addWidget(W.muted(note))
    return frame, value
