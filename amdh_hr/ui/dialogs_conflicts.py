"""حل تعارضات أرقام الموظفين بين حزمة المؤسسة وسجل المركز."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from . import widgets as W


class ConflictDialog(QDialog):
    def __init__(self, parent, conflicts: list[dict]) -> None:
        super().__init__(parent)
        self.conflicts = conflicts
        self.resolutions: dict[str, str] = {}
        self.setWindowTitle("تعارضات المزامنة")
        self.setMinimumSize(860, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(W.title("تعارض في الرقم الوظيفي", 15))
        root.addWidget(W.muted(
            "الرقم نفسه موجود في المركز بهوية مختلفة. اختر النسخة المعتمدة لكل موظف؛ "
            "سيُربط سجل الحزمة بالهوية المركزية."))
        table = QTableWidget(len(conflicts), 5)
        table.setHorizontalHeaderLabels(
            ["الرقم", "اسم الحزمة", "اسم المركز", "الحالة", "القرار"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        headers = table.horizontalHeader()
        for index in range(4):
            headers.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        self.combos: list[QComboBox] = []
        for row, item in enumerate(conflicts):
            values = [item["emp_no"], item["source_name"], item["target_name"],
                      f"{item.get('source_grade') or '—'}/{item.get('source_stage') or '—'} ↔ "
                      f"{item.get('target_grade') or '—'}/{item.get('target_stage') or '—'}"]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
            combo = QComboBox()
            combo.addItem("اعتماد نسخة المركز", "target")
            combo.addItem("اعتماد نسخة المؤسسة", "source")
            table.setCellWidget(row, 4, combo)
            self.combos.append(combo)
        root.addWidget(table, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(W.button("متابعة الاستيراد", "Accent", self._accept, width=160))
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=90))
        root.addLayout(buttons)

    def _accept(self) -> None:
        self.resolutions = {
            item["source_id"]: combo.currentData()
            for item, combo in zip(self.conflicts, self.combos)
        }
        self.accept()
