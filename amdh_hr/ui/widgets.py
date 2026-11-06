"""عناصر واجهة مشتركة: عناوين، بطاقات، أزرار، جداول."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


def _align_right(label: QLabel) -> QLabel:
    label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
    return label


def title(text: str, size: int = 18) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Title")
    label.setStyleSheet(f"font-size: {size}pt; font-weight: 700;")
    return _align_right(label)


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return _align_right(label)


def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Subtitle")
    label.setWordWrap(True)
    return _align_right(label)


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return _align_right(label)


def chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Chip")
    return label


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    return frame


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


def badge(text: str = "HR") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Badge")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(40, 40)
    return label


def button(text: str, variant: str = "", slot=None, width: int | None = None,
           tooltip: str = "") -> QPushButton:
    push = QPushButton(text)
    if variant:
        push.setObjectName(variant)
    push.setCursor(Qt.CursorShape.PointingHandCursor)
    if width:
        push.setMinimumWidth(width)
    if tooltip:
        push.setToolTip(tooltip)
    if slot is not None:
        push.clicked.connect(slot)
    return push


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(38)
    header = widget.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return widget


def fill_table(widget: QTableWidget, rows: list[list], *, stretch_column: int | None = None,
               align_center: bool = True) -> None:
    widget.setRowCount(0)
    for row in rows:
        index = widget.rowCount()
        widget.insertRow(index)
        for column, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            if align_center:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setItem(index, column, item)
    if stretch_column is not None and stretch_column < widget.columnCount():
        header = widget.horizontalHeader()
        for column in range(widget.columnCount()):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.Stretch if column == stretch_column
                else QHeaderView.ResizeMode.ResizeToContents)


def selected_row(widget: QTableWidget) -> int:
    indexes = widget.selectionModel().selectedRows() if widget.selectionModel() else []
    return indexes[0].row() if indexes else -1


def page_header(text: str, description: str = "", actions: list[QWidget] | None = None) -> QWidget:
    container = QWidget()
    container.setObjectName("PageHeader")
    container.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    text_widget = QWidget()
    text_widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    text_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    text_box = QVBoxLayout(text_widget)
    text_box.setContentsMargins(0, 0, 0, 0)
    text_box.setSpacing(2)
    text_box.addWidget(page_title(text))
    if description:
        text_box.addWidget(subtitle(description))
    layout.addWidget(text_widget, 1)
    for action in actions or []:
        layout.addWidget(action)
    return container


def form_row(label_text: str, widget: QWidget, hint: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    label = QLabel(label_text)
    label.setObjectName("Muted")
    layout.addWidget(label)
    layout.addWidget(widget)
    if hint:
        layout.addWidget(muted(hint))
    return container


def stat_card(label_text: str, value: str, note: str = "") -> QFrame:
    frame = card()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(4)
    value_label = QLabel(value)
    value_label.setStyleSheet("font-size: 22pt; font-weight: 800;")
    value_label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
    name_label = QLabel(label_text)
    name_label.setObjectName("Subtitle")
    layout.addWidget(name_label)
    layout.addWidget(value_label)
    if note:
        layout.addWidget(muted(note))
    return frame


def bold_font(size: int = 11) -> QFont:
    font = QFont("Segoe UI", size)
    font.setBold(True)
    return font


def transparent(color: str = "#00000000") -> QColor:
    return QColor(color)
