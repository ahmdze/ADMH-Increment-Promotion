"""عارض مرفقات بسيط لأي كيان (موظف/كتاب/أمر)."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout

from ..server.client import ApiClient, ApiError
from . import widgets as W
from .notify import info
from .pdf_viewer import view_attachment


class AttachmentsDialog(QDialog):
    def __init__(self, parent, client: ApiClient, entity_type: str, entity_id: str,
                 title_text: str = "المرفقات", editable: bool = True) -> None:
        super().__init__(parent)
        self.client = client
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.setWindowTitle(title_text)
        self.setMinimumSize(600, 460)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(10)
        root.addWidget(W.title(title_text, 14))
        toolbar = QHBoxLayout()
        self.upload_btn = W.button("إرفاق ملف", "Accent", self._upload, width=110)
        self.open_btn = W.button("فتح المحدد", "Ghost", self._open, width=110)
        self.print_btn = W.button("طباعة المحدد", "Ghost", self._print, width=120)
        self.upload_btn.setVisible(editable)
        toolbar.addWidget(self.upload_btn)
        toolbar.addWidget(self.open_btn)
        toolbar.addWidget(self.print_btn)
        toolbar.addStretch()
        root.addLayout(toolbar)
        self.table = W.table(["الملف", "الحجم", "تاريخ الرفع"])
        root.addWidget(self.table, 1)
        root.addWidget(W.muted("الملفات المدعومة: PDF وJPG/PNG/TIFF، بحد أقصى 20 ميغابايت."))
        root.addWidget(W.button("إغلاق", "Ghost", self.accept, width=90))
        self.docs: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        try:
            self.docs = self.client.call("documents.list", entity_type=self.entity_type,
                                         entity_id=self.entity_id)["documents"]
        except ApiError as exc:
            info(self, str(exc))
            return
        W.fill_table(self.table, [[row["filename"],
                                   f"{round(int(row.get('size') or 0) / 1024, 1)} KB",
                                   row.get("uploaded_at")] for row in self.docs],
                     stretch_column=0)

    def _upload(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "اختيار ملف", "", "المستندات (*.pdf *.png *.jpg *.jpeg *.tif *.tiff)")
        if not path:
            return
        try:
            content = Path(path).read_bytes()
            self.client.call("documents.upload", entity_type=self.entity_type,
                             entity_id=self.entity_id, filename=Path(path).name,
                             content_b64=base64.b64encode(content).decode())
        except ApiError as exc:
            info(self, str(exc))
            return
        self.refresh()

    def _fetch(self) -> Path | None:
        row = W.selected_row(self.table)
        if not (0 <= row < len(self.docs)):
            info(self, "اختر مرفقاً أولاً.")
            return None
        try:
            data = self.client.call("documents.fetch",
                                    document_id=self.docs[row]["document_id"])
        except ApiError as exc:
            info(self, str(exc))
            return None
        folder = Path(tempfile.mkdtemp(prefix="amdh_att_"))
        target = folder / data["filename"]
        target.write_bytes(base64.b64decode(data["content_b64"]))
        return target

    def _open(self) -> None:
        target = self._fetch()
        if target:
            view_attachment(self, target, target.name)

    def _print(self) -> None:
        target = self._fetch()
        if target:
            view_attachment(self, target, target.name, autoprint=True)
