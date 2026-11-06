"""رسائل موحّدة."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox


def info(parent, text: str, title: str = "تم") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def warning(parent, text: str, title: str = "تنبيه") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def error(parent, text: str, title: str = "خطأ") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def confirm(parent, text: str, title: str = "تأكيد") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes
