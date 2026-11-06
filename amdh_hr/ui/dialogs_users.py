"""نوافذ المستخدمين."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout,
)

from .. import permissions as P
from ..server.client import ApiClient, ApiError
from . import widgets as W


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


class UserDialog(QDialog):
    def __init__(self, parent, client: ApiClient, units: list[dict],
                 user: dict | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.units = [unit for unit in units if not unit.get("is_center")]
        self.center = next((unit for unit in units if unit.get("is_center")), None)
        self.user = user
        self.result: dict | None = None
        self.setWindowTitle("تعديل مستخدم" if user else "مستخدم جديد")
        self.setMinimumWidth(540)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        user = self.user or {}
        editing = bool(self.user)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(W.title("تعديل مستخدم" if editing else "حساب مستخدم جديد", 15))

        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading)

        self.username = QLineEdit(str(user.get("username") or ""))
        self.username.setPlaceholderText("مثال: h1-4")
        self.username.setEnabled(not editing)
        form.addRow(_label("اسم المستخدم *"), self.username)

        self.display = QLineEdit(str(user.get("display_name") or ""))
        form.addRow(_label("الاسم الظاهر"), self.display)

        self.role = QComboBox()
        for code, name, _description in P.ROLES:
            self.role.addItem(name, code)
        self.role.setCurrentIndex(max(0, self.role.findData(user.get("role") or "unit_editor")))
        self.role.currentIndexChanged.connect(self._on_role)
        form.addRow(_label("الدور *"), self.role)

        self.unit = QComboBox()
        self.unit.addItem("— بدون (كل المؤسسات) —", "")
        for unit in self.units:
            self.unit.addItem(f"{unit['name']} ({unit['code']})", unit["unit_id"])
        if self.center:
            self.unit.addItem(f"{self.center['name']} (المركز)", self.center["unit_id"])
        index = self.unit.findData(user.get("unit_id") or "")
        self.unit.setCurrentIndex(max(0, index))
        form.addRow(_label("المؤسسة"), self.unit)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("اتركه فارغاً ليُولَّد تلقائياً")
        self.password.setVisible(not editing)
        self.password_label = _label("كلمة المرور")
        form.addRow(self.password_label, self.password)
        self.password_label.setVisible(not editing)
        root.addWidget(card)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        save = W.button("حفظ", "Accent", self._save, width=120)
        save.setMinimumHeight(36)
        buttons.addWidget(save)
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)
        self._on_role()

    def _on_role(self) -> None:
        role = self.role.currentData()
        self.unit.setEnabled(role != "center_admin")
        if role == "center_admin":
            self.unit.setCurrentIndex(0)
        elif role == "center_editor" and self.center:
            self.unit.setCurrentIndex(self.unit.findData(self.center["unit_id"]))

    def _save(self) -> None:
        self.error.setVisible(False)
        data = {
            "username": self.username.text().strip(),
            "display_name": self.display.text().strip(),
            "role": self.role.currentData(),
            "unit_id": self.unit.currentData() or "",
        }
        if not self.user:
            data["password"] = self.password.text()
        try:
            if self.user:
                result = self.client.call("users.update", user_id=self.user["user_id"],
                                          data=data)
            else:
                result = self.client.call("users.create", data=data)
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.result = result
        self.accept()


class PasswordDialog(QDialog):
    """عرض كلمة مرور مولّدة مرة واحدة."""

    def __init__(self, parent, username: str, password: str, role_label: str = "") -> None:
        super().__init__(parent)
        self.password = password
        self.setWindowTitle("كلمة المرور")
        self.setMinimumWidth(460)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(W.title("كلمة مرور جديدة", 15))
        root.addWidget(W.muted("تُعرض مرة واحدة فقط. انسخها أو اطبعها الآن."))
        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(18, 14, 18, 14)
        form.addRow(_label("المستخدم"), QLabel(username))
        if role_label:
            form.addRow(_label("الدور"), QLabel(role_label))
        field = QLineEdit(password)
        field.setReadOnly(True)
        field.setStyleSheet("font-family: Consolas; font-size: 13pt; letter-spacing: 1px;")
        form.addRow(_label("كلمة المرور"), field)
        root.addWidget(card)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("نسخ", "Accent", lambda: self._copy(), width=110))
        buttons.addStretch()
        buttons.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        root.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.password)
