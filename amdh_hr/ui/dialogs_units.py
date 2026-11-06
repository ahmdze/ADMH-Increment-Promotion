"""نوافذ المؤسسة وتجهيز نسختها."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QVBoxLayout,
)

from ..config import MAX_EDITORS, UNIT_KINDS
from ..server.client import ApiClient, ApiError
from ..util import slugify
from . import widgets as W
from .dialogs_credentials import CredentialsDialog
from .notify import error as show_error


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


class UnitDialog(QDialog):
    """إضافة/تعديل مؤسسة، مع توليد حساباتها عند الإنشاء."""

    def __init__(self, parent, client: ApiClient, unit: dict | None = None,
                 center_exists: bool = False, reports_dir: str = "",
                 center_name: str = "") -> None:
        super().__init__(parent)
        self.client = client
        self.unit = unit
        self.reports_dir = reports_dir
        self.center_name = center_name
        self.saved: dict | None = None
        self.credentials: list[dict] = []
        self.setWindowTitle("تعديل مؤسسة" if unit else "إضافة مؤسسة")
        self.setMinimumWidth(620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build(center_exists)

    # ------------------------------------------------------------------
    def _build(self, center_exists: bool) -> None:
        unit = self.unit or {}
        editing = bool(self.unit)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(W.title("تعديل بيانات المؤسسة" if editing else "مؤسسة جديدة", 15))
        root.addWidget(W.muted(
            "عند الحفظ تُنشأ حسابات المؤسسة تلقائياً، وتُعرض كلمات مرورها مرة واحدة "
            "في بطاقة قابلة للطباعة." if not editing else
            "تعديل الاسم أو الرمز لا يغيّر أسماء المستخدمين الحالية."))

        form_card = W.card()
        form = QFormLayout(form_card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)

        self.name = QLineEdit(str(unit.get("name") or ""))
        self.name.setPlaceholderText("مثال: مستشفى الكرامة")
        self.name.editingFinished.connect(self._suggest_code)
        form.addRow(_label("اسم المؤسسة *"), self.name)

        self.code = QLineEdit(str(unit.get("code") or ""))
        self.code.setPlaceholderText("H1")
        self.code.setMaxLength(16)
        form.addRow(_label("الرمز (يُستخدم في أسماء المستخدمين)"), self.code)

        self.kind = QComboBox()
        self.kind.addItems(UNIT_KINDS)
        self.kind.setCurrentText(str(unit.get("kind") or "مستشفى"))
        form.addRow(_label("النوع"), self.kind)

        self.manager = QLineEdit(str(unit.get("manager") or ""))
        form.addRow(_label("المدير/المسؤول"), self.manager)
        self.phone = QLineEdit(str(unit.get("phone") or ""))
        self.phone.setPlaceholderText("07xxxxxxxxx")
        form.addRow(_label("الهاتف"), self.phone)
        self.address = QLineEdit(str(unit.get("address") or ""))
        form.addRow(_label("العنوان"), self.address)
        self.notes = QLineEdit(str(unit.get("notes") or ""))
        form.addRow(_label("ملاحظات"), self.notes)

        self.active = QCheckBox("مؤسسة مُفعّلة")
        self.active.setChecked(bool(unit.get("active", True)))
        form.addRow(_label("الحالة"), self.active)

        self.is_center = QCheckBox("هذا مركز الدائرة (لا يمكن تجهيز نسخة له)")
        self.is_center.setChecked(bool(unit.get("is_center")))
        self.is_center.setVisible(not editing and not center_exists)
        self.is_center.toggled.connect(self._on_center_toggled)
        form.addRow(_label(""), self.is_center)
        root.addWidget(form_card)

        self.users_card = W.card()
        users_layout = QVBoxLayout(self.users_card)
        users_layout.setContentsMargins(18, 14, 18, 14)
        users_layout.setSpacing(8)
        self.users_title = QLabel("حسابات المؤسسة")
        self.users_title.setStyleSheet("font-weight: 700;")
        users_layout.addWidget(self.users_title)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_label("عدد حسابات الإدخال"))
        self.editors = QSpinBox()
        self.editors.setRange(1, MAX_EDITORS)
        self.editors.setValue(1)
        self.editors.valueChanged.connect(self._update_total)
        row.addWidget(self.editors)
        self.with_manager = QCheckBox("إنشاء حساب مدير للمؤسسة")
        self.with_manager.setChecked(True)
        self.with_manager.toggled.connect(self._update_total)
        row.addWidget(self.with_manager)
        row.addStretch()
        users_layout.addLayout(row)
        self.total_label = W.muted("")
        users_layout.addWidget(self.total_label)
        self.users_card.setVisible(not editing)
        root.addWidget(self.users_card)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        save = W.button("حفظ وإظهار البيانات", "Accent", self._save, width=190)
        save.setMinimumHeight(38)
        buttons.addWidget(save)
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)
        self._update_total()
        if unit.get("is_center"):
            self._on_center_toggled(True)

    # ------------------------------------------------------------------
    def _suggest_code(self) -> None:
        if not self.code.text().strip():
            self.code.setText(slugify(self.name.text(), "unit").upper()[:8])

    def _on_center_toggled(self, checked: bool) -> None:
        if checked:
            self.kind.setCurrentText("مركز الدائرة")
            self.kind.setEnabled(False)
            self.with_manager.setChecked(False)
            self.with_manager.setVisible(False)
            self.users_title.setText("حسابات مدخلي المركز")
            self.editors.setRange(1, 5)
        else:
            self.kind.setEnabled(True)
            self.with_manager.setVisible(True)
            self.editors.setRange(1, MAX_EDITORS)
        self._update_total()

    def _update_total(self) -> None:
        total = self.editors.value() + (1 if self.with_manager.isChecked() else 0)
        label = {1: "حساب واحد", 2: "حسابان"}.get(total, f"{total} حسابات")
        self.total_label.setText(f"إجمالي الحسابات: {label} — الحد الأقصى 5 حسابات للمؤسسة.")

    # ------------------------------------------------------------------
    def _data(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "code": self.code.text().strip(),
            "kind": self.kind.currentText(),
            "manager": self.manager.text().strip(),
            "phone": self.phone.text().strip(),
            "address": self.address.text().strip(),
            "notes": self.notes.text().strip(),
            "active": self.active.isChecked(),
            "is_center": self.is_center.isChecked(),
        }

    def _save(self) -> None:
        self.error.setVisible(False)
        data = self._data()
        if not data["name"]:
            self._fail("اسم المؤسسة مطلوب.")
            return
        try:
            if self.unit:
                result = self.client.call("units.update", unit_id=self.unit["unit_id"],
                                          data=data)
                self.saved = result["unit"]
            else:
                result = self.client.call(
                    "units.create", data=data, editor_count=self.editors.value(),
                    create_manager=self.with_manager.isChecked())
                self.saved = result["unit"]
                self.credentials = result.get("credentials") or []
        except ApiError as exc:
            self._fail(str(exc))
            return
        self.accept()

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)


class ProvisionDialog(QDialog):
    """تجهيز نسخة مؤسسة كاملة (ZIP)."""

    def __init__(self, parent, client: ApiClient, unit: dict, meta: dict) -> None:
        super().__init__(parent)
        self.client = client
        self.unit = unit
        self.meta = meta
        self.folder = ""
        self.zip_path = ""
        self.new_credentials: list[dict] = []
        self.setWindowTitle("تجهيز نسخة المؤسسة")
        self.setMinimumSize(640, 520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(W.title(f"تجهيز نسخة: {self.unit['name']}", 15))
        root.addWidget(W.muted(
            "تُنشأ نسخة بقاعدة مؤسستك فقط، وحساباتها الحالية، وحساب admin للصيانة. "
            "النسخة تعمل دون إنترنت، وتُسلَّم على USB أو مجلد."))

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("كلمة مرور حساب admin للصيانة")
        form.addRow(_label("كلمة مرور الصيانة (admin) *"), self.password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_label("تأكيد كلمة مرور الصيانة"), self.confirm)

        dest_row = QHBoxLayout()
        self.dest = QLineEdit(str(Path(self.meta.get("data_dir", ".")) / "exports"))
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(W.button("استعراض", "Ghost", self._browse, width=90))
        form.addRow(_label("مجلد الحفظ (على جهاز الخدمة)"), dest_row)

        self.include_program = QCheckBox("تضمين ملفات البرنامج (يتطلب تشغيل النسخة التنفيذية)")
        self.include_program.setChecked(bool(getattr(sys, "frozen", False)))
        self.include_program.setEnabled(bool(getattr(sys, "frozen", False)))
        form.addRow(_label(""), self.include_program)
        self.make_zip = QCheckBox("إنشاء ملف ZIP")
        self.make_zip.setChecked(True)
        form.addRow(_label(""), self.make_zip)
        self.reset_users = QCheckBox("تصفير كلمات مرور المؤسسة وإصدار بطاقة جديدة")
        form.addRow(_label(""), self.reset_users)
        root.addWidget(card)

        self.note = W.muted(
            "ملاحظة: التجهيز ينفَّذ على جهاز الخدمة. لتصدير نسخة تحمل بيانات الدخول "
            "فعّل «تصفير كلمات المرور»؛ كلمات المرور القديمة لا يمكن استرجاعها.\n"
            "تضمين ملفات البرنامج (EXE) يتطلب تشغيل النسخة التنفيذية.")
        root.addWidget(self.note)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)
        self.result = W.muted("")
        self.result.setVisible(False)
        root.addWidget(self.result)

        buttons = QHBoxLayout()
        self.run_btn = W.button("تجهيز النسخة", "Accent", self._run, width=160)
        self.run_btn.setMinimumHeight(38)
        buttons.addWidget(self.run_btn)
        self.open_btn = W.button("فتح المجلد", "Ghost", self._open_folder, width=130)
        self.open_btn.setVisible(False)
        buttons.addWidget(self.open_btn)
        buttons.addStretch()
        buttons.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        root.addLayout(buttons)

    # ------------------------------------------------------------------
    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "مجلد حفظ النسخة", self.dest.text())
        if folder:
            self.dest.setText(folder)

    def _run(self) -> None:
        self.error.setVisible(False)
        password = self.password.text()
        if password != self.confirm.text():
            self._fail("كلمتا المرور غير متطابقتين.")
            return
        if len(password) < 8:
            self._fail("كلمة مرور الصيانة قصيرة (8 أحرف على الأقل).")
            return
        credentials: list[dict] = []
        if self.reset_users.isChecked():
            try:
                reset = self.client.call("units.reset_users",
                                         unit_id=self.unit["unit_id"])
            except ApiError as exc:
                self._fail(str(exc))
                return
            credentials = reset.get("credentials") or []
            self.new_credentials = credentials
            page = _credentials_page(self.unit, credentials, self.meta)
            preview = _credentials_preview(self.unit, credentials, self.meta)
            dialog = CredentialsDialog(
                self, page, reports_dir=Path(self.meta.get("data_dir", ".")) / "reports",
                filename=f"بيانات_دخول_{self.unit.get('code', 'unit')}",
                copy_text=_copy_text(self.unit, credentials),
                title="بيانات الدخول الجديدة", preview_html=preview)
            dialog.exec()

        self.run_btn.setEnabled(False)
        self.run_btn.setText("جارٍ التجهيز…")
        try:
            result = self.client.call(
                "units.provision", unit_id=self.unit["unit_id"],
                admin_password=password, dest_dir=self.dest.text().strip(),
                include_program=self.include_program.isChecked(),
                make_zip=self.make_zip.isChecked(), credentials=credentials)
        except ApiError as exc:
            self._fail(str(exc))
            self.run_btn.setEnabled(True)
            self.run_btn.setText("تجهيز النسخة")
            return
        finally:
            self.run_btn.setEnabled(True)
            self.run_btn.setText("تجهيز النسخة")
        self.folder = result.get("folder", "")
        self.zip_path = result.get("zip", "")
        stats = result.get("stats", {})
        lines = [f"تم التجهيز: {stats.get('users', 0)} حساب، "
                 f"{stats.get('employees', 0)} موظف."]
        if self.folder:
            lines.append(f"المجلد: {self.folder}")
        if self.zip_path:
            lines.append(f"ZIP: {self.zip_path}")
        self.result.setText("\n".join(lines))
        self.result.setVisible(True)
        self.open_btn.setVisible(bool(self.folder))
        self.run_btn.setText("تجهيز نسخة أخرى")

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)

    def _open_folder(self) -> None:
        target = self.zip_path or self.folder
        if target:
            path = Path(target)
            QDesktopServices.openUrl(QUrl.fromLocalFile(
                str(path if path.is_dir() else path.parent)))


def _credentials_page(unit: dict, credentials: list[dict], meta: dict) -> str:
    from ..exporters import html as H
    return H.credentials_page(unit, credentials, center_name=meta.get("center", ""))


def _credentials_preview(unit: dict, credentials: list[dict], meta: dict) -> str:
    from ..exporters import html as H
    return H.credentials_preview(unit, credentials, center_name=meta.get("center", ""))


def _copy_text(unit: dict, credentials: list[dict]) -> str:
    lines = [f"المؤسسة: {unit.get('name')}", f"الرمز: {unit.get('code')}"]
    for item in credentials:
        lines.append(f"{item.get('role_label', '')}: {item['username']} / {item['password']}")
    return "\n".join(lines)
