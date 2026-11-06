"""عرض بيانات الدخول مرة واحدة مع معاينة HTML وطباعة من المتصفح."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QTextBrowser, QVBoxLayout,
)

from ..exporters import html as H
from ..util import safe_filename, stamp
from . import widgets as W
from .notify import info


class CredentialsDialog(QDialog):
    """بطاقة الدخول: معاينة، فتح للطباعة، حفظ HTML، نسخ."""

    def __init__(self, parent, page_html: str, *, reports_dir: str | Path = "",
                 filename: str = "", copy_text: str = "",
                 title: str = "بيانات الدخول", preview_html: str = "") -> None:
        super().__init__(parent)
        self.page_html = page_html
        self.preview_html = preview_html or page_html
        self.reports_dir = Path(reports_dir) if reports_dir else None
        self.filename = safe_filename(filename or f"بيانات_دخول_{stamp()}", "credentials")
        self.copy_text = copy_text
        self.setWindowTitle(title)
        self.setMinimumSize(780, 680)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        root.addWidget(W.title("بيانات الدخول", 15))
        warning = W.muted(
            "اعرضها مرة واحدة، واطبعها ورقياً وسلّم كل حساب لصاحبه. "
            "لن تُعرض كلمات المرور مرة أخرى بعد الإغلاق.")
        warning.setStyleSheet("color: #b45309; font-weight: 600;")
        root.addWidget(warning)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(
            "QTextBrowser { background: #ffffff; color: #0f172a; "
            "border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px; }")
        self.preview.setHtml(self.preview_html)
        root.addWidget(self.preview, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(W.button("فتح للطباعة", "Accent", self._print, width=150))
        buttons.addWidget(W.button("حفظ HTML", "Ghost", self._save, width=120))
        if self.copy_text:
            buttons.addWidget(W.button("نسخ البيانات", "Ghost", self._copy, width=140))
        self.auto_print = QCheckBox("طباعة تلقائية عند الفتح")
        buttons.addWidget(self.auto_print)
        buttons.addStretch()
        buttons.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        root.addLayout(buttons)

    # ------------------------------------------------------------------
    def _target_path(self) -> Path | None:
        folder = self.reports_dir
        if folder is None:
            chosen = QFileDialog.getExistingDirectory(self, "مجلد حفظ الملف")
            if not chosen:
                return None
            folder = Path(chosen)
        content = H.add_auto_print(self.page_html) if self.auto_print.isChecked() \
            else self.page_html
        return H.save(content, folder, self.filename + ".html")

    def _save(self) -> None:
        path = self._target_path()
        if path:
            info(self, f"حُفظ الملف:\n{path}", "حفظ HTML")

    def _print(self) -> None:
        path = self._target_path()
        if path is None:
            return
        H.open_in_browser(path)
        info(self, "فُتح الملف في المتصفح. استخدم زر «طباعة» أو «حفظ PDF» من نافذة الطباعة.",
             "الطباعة")

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.copy_text)
        info(self, "نُسخت بيانات الدخول إلى الحافظة.", "نسخ")

    def open_reports_folder(self) -> None:
        if self.reports_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.reports_dir)))
