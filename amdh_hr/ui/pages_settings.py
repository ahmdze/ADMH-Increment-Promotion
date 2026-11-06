"""صفحة الإعدادات: عام، النسخ الاحتياطي، الأمان."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..server.client import ApiError
from . import theme, widgets as W
from .notify import confirm, error, info
from .pages_base import BasePage


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


class SettingsPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(W.page_header("الإعدادات", "الثيم، النسخ الاحتياطي، وكلمة المرور"))

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "عام")
        if self.can("backup_restore"):
            tabs.addTab(self._backup_tab(), "النسخ الاحتياطي")
        tabs.addTab(self._security_tab(), "الأمان")
        root.addWidget(tabs, 1)

    # ------------------------------------------------------------------
    def _general_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("تلقائي (حسب النظام)", "auto")
        self.theme_combo.addItem("داكن", "dark")
        self.theme_combo.addItem("فاتح", "light")
        index = self.theme_combo.findData(self.settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.theme_combo.setMaximumWidth(300)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        form.addRow(_label("الثيم"), self.theme_combo)

        self.server_value = QLineEdit(self.client.base_url)
        self.server_value.setReadOnly(True)
        self.server_value.setMaximumWidth(520)
        form.addRow(_label("عنوان الخدمة"), self.server_value)

        data_dir = QLineEdit(str(self.meta.get("data_dir", "")))
        data_dir.setReadOnly(True)
        data_dir.setMaximumWidth(520)
        form.addRow(_label("مجلد البيانات"), data_dir)
        center_label = QLabel(self.meta.get("center") or "غير مُعرَّف — أنشئه من صفحة المؤسسات")
        center_label.setAlignment(Qt.AlignmentFlag.AlignLeading)
        form.addRow(_label("مركز الدائرة"), center_label)
        version_label = QLabel(f"{self.meta.get('version', '')} — مخطط "
                               f"{self.meta.get('schema_version', '')}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignLeading)
        form.addRow(_label("إصدار البرنامج"), version_label)
        root.addWidget(card)

        row = QHBoxLayout()
        row.addWidget(W.button("فتح مجلد البيانات", "Ghost", self._open_data_dir, width=190))
        row.addWidget(W.button("تحديث", "Ghost", self.refresh, width=100))
        row.addStretch()
        root.addLayout(row)
        root.addWidget(W.muted(
            "تغيير عنوان الخدمة يتطلب إعادة تشغيل البرنامج أو تسجيل الخروج والدخول من جديد."))
        root.addStretch()
        return page

    # ------------------------------------------------------------------
    def _backup_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(W.button("نسخة احتياطية الآن", "Accent", self._run_backup, width=190))
        row.addWidget(W.button("فحص المحددة", "Ghost", self._verify_backup, width=140))
        row.addWidget(W.button("فتح المجلد", "Ghost", self._open_backup_dir, width=130))
        row.addWidget(W.button("تحديث", "Ghost", self.refresh, width=100))
        row.addStretch()
        root.addLayout(row)

        self.backup_table = W.table(["التاريخ", "الحجم (KB)", "النوع", "الملف موجود"])
        root.addWidget(self.backup_table, 1)
        root.addWidget(W.muted(
            "النسخة تحتوي قاعدة البيانات كاملة. يُنصح بنسخة يومية على USB منفصل، "
            "واختبار استعادة قبل التحديثات الكبيرة."))
        return page

    # ------------------------------------------------------------------
    def _security_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.old_password = QLineEdit()
        self.old_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_label("كلمة المرور الحالية"), self.old_password)
        form.addRow(_label("كلمة المرور الجديدة (8 أحرف على الأقل)"), self.new_password)
        form.addRow(_label("تأكيد كلمة المرور"), self.confirm_password)
        root.addWidget(card)
        row = QHBoxLayout()
        row.addWidget(W.button("تغيير كلمة المرور", "Accent", self._change_password, width=190))
        row.addStretch()
        root.addLayout(row)
        root.addWidget(W.muted(
            "تُخزَّن كلمة المرور كبصمة PBKDF2، ولا يمكن استرجاعها نصاً. "
            "فقدانها يعني إعادة تعيينها من مدير المركز."))
        root.addStretch()
        return page

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.server_value.setText(self.client.base_url)
        if not self.can("backup_restore") or not hasattr(self, "backup_table"):
            return
        try:
            backups = self.client.call("backup.list").get("backups", [])
        except ApiError as exc:
            self.backup_table.setRowCount(0)
            return
        rows = [[item.get("ts"), item.get("size_kb"), item.get("kind"),
                 "نعم" if item.get("exists") else "لا"] for item in backups]
        W.fill_table(self.backup_table, rows, stretch_column=0)
        self.backups = backups

    # ------------------------------------------------------------------
    def _theme_changed(self) -> None:
        name = self.theme_combo.currentData() or "dark"
        self.settings.theme = name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(name))
        window = self.window()
        if hasattr(window, "sync_theme_button"):
            window.sync_theme_button()

    def _open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.meta.get("data_dir", ""))))

    def _open_backup_dir(self) -> None:
        folder = Path(self.meta.get("data_dir", "")) / "backups"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _run_backup(self) -> None:
        if not self.can("backup_restore"):
            return
        try:
            result = self.client.call("backup.run")
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"تم إنشاء النسخة:\n{result.get('path')}")
        self.refresh()

    def _verify_backup(self) -> None:
        row = W.selected_row(self.backup_table)
        backups = getattr(self, "backups", [])
        if not (0 <= row < len(backups)):
            info(self, "اختر نسخة من الجدول أولاً.", "فحص نسخة")
            return
        try:
            result = self.client.call("backup.verify", path=backups[row]["path"])
        except ApiError as exc:
            error(self, str(exc))
            return
        if result.get("ok"):
            info(self, f"النسخة سليمة.\nSHA-256: {result.get('sha256', '')[:32]}…")
        else:
            error(self, f"النسخة غير سليمة: {result.get('message')}")

    def _change_password(self) -> None:
        if self.new_password.text() != self.confirm_password.text():
            error(self, "كلمتا المرور الجديدتان غير متطابقتين.")
            return
        try:
            self.client.call("auth.change_password",
                             old_password=self.old_password.text(),
                             new_password=self.new_password.text())
        except ApiError as exc:
            error(self, str(exc))
            return
        for field in (self.old_password, self.new_password, self.confirm_password):
            field.clear()
        info(self, "تم تغيير كلمة المرور.")
