"""عارض PDF/صور داخلي مع طباعة مباشرة للمرفقات."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from . import widgets as W
from .notify import error


class PdfViewerDialog(QDialog):
    def __init__(self, parent, path: Path, title_text: str = "عارض PDF") -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(title_text)
        self.setMinimumSize(900, 700)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(8)
        root.addWidget(W.title(title_text, 14))

        bar = QHBoxLayout()
        self.prev_btn = W.button("السابق", "Ghost", self._prev, width=90)
        self.next_btn = W.button("التالي", "Ghost", self._next, width=90)
        self.page_label = QLabel("—")
        self.page_label.setObjectName("Chip")
        self.zoom_out = W.button("−", "Ghost", lambda: self._zoom(0.85), width=40)
        self.zoom_in = W.button("+", "Ghost", lambda: self._zoom(1.18), width=40)
        self.print_btn = W.button("طباعة", "Accent", self.print_dialog, width=100)
        for widget in (self.prev_btn, self.next_btn, self.page_label, self.zoom_out,
                       self.zoom_in):
            bar.addWidget(widget)
        bar.addStretch()
        bar.addWidget(self.print_btn)
        bar.addWidget(W.button("إغلاق", "Ghost", self.accept, width=80))
        root.addLayout(bar)

        self.document = QPdfDocument(self)
        self.document.load(str(self.path))
        self.view = QPdfView(self)
        self.view.setDocument(self.document)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        root.addWidget(self.view, 1)
        navigator = self.view.pageNavigator()
        navigator.currentPageChanged.connect(lambda _page: self._update_label())
        self._update_label()

    def _update_label(self) -> None:
        current = self.view.pageNavigator().currentPage() + 1
        self.page_label.setText(f"{current} / {self.document.pageCount()}")

    def _prev(self) -> None:
        navigator = self.view.pageNavigator()
        if navigator.currentPage() > 0:
            navigator.jump(navigator.currentPage() - 1, QPointF(0, 0))

    def _next(self) -> None:
        navigator = self.view.pageNavigator()
        if navigator.currentPage() < self.document.pageCount() - 1:
            navigator.jump(navigator.currentPage() + 1, QPointF(0, 0))

    def _zoom(self, factor: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.2, min(4.0, self.view.zoomFactor() * factor)))

    def print_dialog(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        try:
            for index in range(self.document.pageCount()):
                if index:
                    printer.newPage()
                rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                image = self.document.render(index, rect.size().toSize())
                if not image.isNull():
                    painter.drawImage(rect.topLeft(), image)
        finally:
            painter.end()


class ImageViewerDialog(QDialog):
    def __init__(self, parent, path: Path, title_text: str = "عارض الصورة") -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.image = QImage(str(self.path))
        self.setWindowTitle(title_text)
        self.setMinimumSize(760, 620)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.addWidget(W.title(title_text, 14))
        bar = QHBoxLayout()
        bar.addWidget(W.button("طباعة", "Accent", self.print_dialog, width=100))
        bar.addStretch()
        bar.addWidget(W.button("إغلاق", "Ghost", self.accept, width=80))
        root.addLayout(bar)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not self.image.isNull():
            label.setPixmap(QPixmap.fromImage(self.image))
        else:
            label.setText("تعذّر عرض الصورة.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(label)
        root.addWidget(scroll, 1)

    def print_dialog(self) -> None:
        if self.image.isNull():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        try:
            rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            scaled = self.image.scaled(rect.size().toSize(),
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2
            painter.drawImage(int(x), int(y), scaled)
        finally:
            painter.end()


def view_attachment(parent, path: Path, title_text: str = "المرفق",
                    autoprint: bool = False) -> QDialog:
    if Path(path).suffix.lower() == ".pdf":
        dialog: QDialog = PdfViewerDialog(parent, Path(path), title_text)
    else:
        dialog = ImageViewerDialog(parent, Path(path), title_text)
    if autoprint:
        QTimer.singleShot(100, dialog.print_dialog)
    dialog.exec()
    return dialog
