"""إدارة العناوين الوظيفية (سجل مرجعي للقواعد والاستهداف)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from ..server.client import ApiClient, ApiError
from . import widgets as W
from .notify import confirm, error


def _label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("Muted")
    return widget


class TitleForm(QDialog):
    def __init__(self, parent, client: ApiClient, title: dict | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.title = title
        self.setWindowTitle("تعديل عنوان وظيفي" if title else "عنوان وظيفي جديد")
        self.setMinimumWidth(460)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("عنوان وظيفي", 14))
        card = W.card()
        form = QFormLayout(card)
        form.setContentsMargins(16, 14, 16, 14)
        self.code = QLineEdit(str((title or {}).get("code") or ""))
        self.code.setPlaceholderText("DOC")
        self.name = QLineEdit(str((title or {}).get("name") or ""))
        self.name.setPlaceholderText("طبيب")
        self.grade = QLineEdit(str((title or {}).get("grade") or ""))
        self.grade.setPlaceholderText("الدرجة المرتبطة (اختياري)")
        self.active = QCheckBox("مُفعّل")
        self.active.setChecked(bool((title or {}).get("active", True)))
        form.addRow(_label("الرمز *"), self.code)
        form.addRow(_label("الاسم *"), self.name)
        form.addRow(_label("الدرجة"), self.grade)
        form.addRow(_label(""), self.active)
        root.addWidget(card)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setVisible(False)
        root.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("حفظ", "Accent", self._save, width=110))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)

    def _save(self) -> None:
        data = {"code": self.code.text().strip(), "name": self.name.text().strip(),
                "grade": self.grade.text().strip(), "active": self.active.isChecked()}
        try:
            if self.title:
                self.client.call("titles.update", title_id=self.title["title_id"], data=data)
            else:
                self.client.call("titles.create", data=data)
        except ApiError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()


class TitlesDialog(QDialog):
    def __init__(self, parent, client: ApiClient, editable: bool = True) -> None:
        super().__init__(parent)
        self.client = client
        self.editable = editable
        self.setWindowTitle("العناوين الوظيفية")
        self.setMinimumSize(620, 520)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(10)
        root.addWidget(W.title("العناوين الوظيفية", 15))
        root.addWidget(W.muted("سجل مرجعي تُبنى عليه قواعد القدم واستهداف كتب الشكر."))
        toolbar = QHBoxLayout()
        self.add_btn = W.button("عنوان جديد", "Accent", self._add, width=120)
        self.edit_btn = W.button("تعديل", "Ghost", self._edit, width=90)
        self.add_btn.setVisible(editable)
        self.edit_btn.setVisible(editable)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addStretch()
        root.addLayout(toolbar)
        self.table = W.table(["الرمز", "الاسم", "الدرجة", "مُفعّل"])
        self.table.doubleClicked.connect(lambda _index: self._edit())
        root.addWidget(self.table, 1)
        root.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        self.refresh()

    def refresh(self) -> None:
        try:
            titles = self.client.call("titles.list")["titles"]
        except ApiError as exc:
            error(self, str(exc))
            return
        self.titles = titles
        W.fill_table(self.table, [[row["code"], row["name"], row.get("grade") or "—",
                                   "نعم" if row.get("active") else "لا"] for row in titles],
                     stretch_column=1)

    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        return self.titles[row] if 0 <= row < len(self.titles) else None

    def _add(self) -> None:
        if TitleForm(self, self.client).exec():
            self.refresh()

    def _edit(self) -> None:
        title = self._selected()
        if not title:
            return
        if TitleForm(self, self.client, title).exec():
            self.refresh()
