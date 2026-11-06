"""نوافذ كلمة مرور تشفير قاعدة البيانات."""

from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox


def ask_passphrase(parent, title: str = "كلمة مرور التشفير") -> str:
    text, accepted = QInputDialog.getText(
        parent, title, "كلمة مرور تشفير قاعدة البيانات:",
        QLineEdit.EchoMode.Password)
    return text if accepted else ""


def ask_new_passphrase(parent, title: str = "تعيين كلمة مرور التشفير") -> str:
    while True:
        first, accepted = QInputDialog.getText(
            parent, title,
            "كلمة مرور التشفير (8 أحرف على الأقل):\nلا يمكن استعادتها إن نسيتها.",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return ""
        if len(first) < 8:
            QMessageBox.warning(parent, title, "كلمة المرور يجب ألا تقل عن 8 أحرف.")
            continue
        second, accepted = QInputDialog.getText(
            parent, title, "أعد إدخال كلمة المرور:",
            QLineEdit.EchoMode.Password)
        if not accepted:
            return ""
        if first != second:
            QMessageBox.warning(parent, title, "كلمتا المرور غير متطابقتين.")
            continue
        return first


def confirm_enable(parent, db_exists: bool) -> bool:
    text = ("قاعدة البيانات الحالية غير مشفرة.\n"
            "سيتم تشفيرها الآن بعد أخذ نسخة مشفرة احتياطية.\n\n"
            "لا يمكن استعادة كلمة المرور إن نسيتها. هل تريد المتابعة؟"
            if db_exists else
            "سيتم إنشاء قاعدة بيانات مشفرة.\n"
            "اختر كلمة مرور قوية ولا تنسها؛ لا يمكن استعادتها.\n\nهل تريد المتابعة؟")
    return QMessageBox.question(
        parent, "تشفير قاعدة البيانات", text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    ) == QMessageBox.StandardButton.Yes


def ask_package_password(parent, title: str = "كلمة مرور الحزمة",
                         confirm: bool = False) -> str | None:
    """None = إلغاء، و"" = حزمة قديمة غير مشفرة (عند الاستيراد)."""
    while True:
        first, accepted = QInputDialog.getText(
            parent, title,
            "كلمة مرور حزمة .amdhpkg" + (" (8 أحرف على الأقل):" if confirm else ":"),
            QLineEdit.EchoMode.Password)
        if not accepted:
            return None
        if not first:
            if confirm:
                QMessageBox.warning(parent, title,
                                    "حزمة التصدير يجب أن تكون مشفرة بكلمة مرور.")
                continue
            return ""
        if confirm and len(first) < 8:
            QMessageBox.warning(parent, title, "كلمة المرور يجب ألا تقل عن 8 أحرف.")
            continue
        if confirm:
            second, accepted = QInputDialog.getText(
                parent, title, "أعد إدخال كلمة مرور الحزمة:",
                QLineEdit.EchoMode.Password)
            if not accepted:
                return None
            if first != second:
                QMessageBox.warning(parent, title, "كلمتا المرور غير متطابقتين.")
                continue
        return first


def show_error(parent, message: str) -> None:
    QMessageBox.critical(parent, "تشفير قاعدة البيانات", message)
