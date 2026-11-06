"""صفحة التقارير: توليد وطباعة وتصدير."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

from ..server.client import ApiError
from ..util import today_iso
from . import widgets as W
from .notify import error, info
from .pages_base import BasePage


class ReportsPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(W.page_header(
            "التقارير", "قوائم قابلة للطباعة والتصدير وفق الصلاحيات والنطاق"))

        card = W.card()
        bar = QVBoxLayout(card)
        bar.setContentsMargins(16, 12, 16, 12)
        bar.setSpacing(8)
        first = QHBoxLayout()
        first.addWidget(QLabel("التقرير"))
        self.kind = QComboBox()
        self.kind.setMinimumWidth(260)
        self.kind.currentIndexChanged.connect(self._sync_filters)
        first.addWidget(self.kind)
        first.addSpacing(10)
        self.from_label = QLabel("من")
        self.date_from = QLineEdit()
        self.date_from.setPlaceholderText("YYYY-MM-DD")
        self.date_from.setFixedWidth(120)
        self.to_label = QLabel("إلى")
        self.date_to = QLineEdit()
        self.date_to.setPlaceholderText("YYYY-MM-DD")
        self.date_to.setFixedWidth(120)
        for widget in (self.from_label, self.date_from, self.to_label, self.date_to):
            first.addWidget(widget)
        self.status = QComboBox()
        self.status.addItem("كل الحالات", "")
        self.status.addItem("مسودة", "draft")
        self.status.addItem("معتمد", "approved")
        self.status_label = QLabel("الحالة")
        first.addWidget(self.status_label)
        first.addWidget(self.status)
        self.days = QSpinBox()
        self.days.setRange(7, 3650)
        self.days.setValue(90)
        self.days.setFixedWidth(90)
        self.days_label = QLabel("خلال (يوم)")
        first.addWidget(self.days_label)
        first.addWidget(self.days)
        first.addStretch()
        self.run_btn = W.button("توليد", "Accent", self._run, width=100)
        first.addWidget(self.run_btn)
        bar.addLayout(first)
        self.pkg_row = QHBoxLayout()
        self.old_label = QLabel("من إصدار")
        self.old_pkg = QComboBox()
        self.old_pkg.setMinimumWidth(240)
        self.new_label = QLabel("إلى إصدار")
        self.new_pkg = QComboBox()
        self.new_pkg.setMinimumWidth(240)
        for widget in (self.old_label, self.old_pkg, self.new_label, self.new_pkg):
            self.pkg_row.addWidget(widget)
        self.pkg_row.addStretch()
        bar.addLayout(self.pkg_row)
        second = QHBoxLayout()
        second.addStretch()
        self.print_btn = W.button("طباعة HTML", "Ghost", lambda: self._export("html"), width=130)
        self.pdf_btn = W.button("تصدير PDF", "Ghost", lambda: self._export("pdf"), width=120)
        self.csv_btn = W.button("تصدير CSV", "Ghost", lambda: self._export("csv"), width=120)
        self.excel_btn = W.button("تصدير Excel", "Ghost", lambda: self._export("xlsx"), width=130)
        self.print_btn.setEnabled(False)
        self.pdf_btn.setEnabled(False)
        self.csv_btn.setEnabled(False)
        self.excel_btn.setEnabled(False)
        second.addWidget(self.print_btn)
        second.addWidget(self.pdf_btn)
        second.addWidget(self.csv_btn)
        second.addWidget(self.excel_btn)
        bar.addLayout(second)
        root.addWidget(card)

        self.table = W.table(["—"])
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        self.result: dict | None = None

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            types = self.client.call("reports.types")["types"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        current = self.kind.currentData()
        self.kind.blockSignals(True)
        self.kind.clear()
        for item in types:
            self.kind.addItem(item["name"], item["code"])
        index = self.kind.findData(current)
        self.kind.setCurrentIndex(max(0, index))
        self.kind.blockSignals(False)
        self._sync_filters()

    def _sync_filters(self) -> None:
        kind = self.kind.currentData()
        dated = kind in {"letters", "letters_missing", "orders", "orders_missing", "audit"}
        for widget in (self.from_label, self.date_from, self.to_label, self.date_to):
            widget.setVisible(dated)
        self.status.setVisible(kind in {"letters", "letters_missing"})
        self.status_label.setVisible(kind in {"letters", "letters_missing"})
        self.days.setVisible(kind == "upcoming")
        self.days_label.setVisible(kind == "upcoming")
        diff = kind == "rule_diff"
        for widget in (self.old_label, self.old_pkg, self.new_label, self.new_pkg):
            widget.setVisible(diff)
        if diff and self.old_pkg.count() == 0:
            self._load_packages()

    def _load_packages(self) -> None:
        try:
            packages = [item for item in self.client.call("rules.packages")["packages"]
                        if item["status"] == "published"]
        except ApiError:
            return
        for combo in (self.new_pkg, self.old_pkg):
            combo.clear()
            for item in packages:
                combo.addItem(f"{item['code']} — إصدار {item['version']}",
                              item["package_id"])
        if self.old_pkg.count() > 1:
            self.old_pkg.setCurrentIndex(1)
        self.new_pkg.setCurrentIndex(0)

    def _filters(self) -> dict:
        return {"from": self.date_from.text().strip(), "to": self.date_to.text().strip(),
                "status": self.status.currentData() or "", "days": self.days.value(),
                "as_of": today_iso(),
                "old_package": self.old_pkg.currentData() or "",
                "new_package": self.new_pkg.currentData() or ""}

    def _run(self) -> None:
        try:
            self.result = self.client.call("reports.run", report_type=self.kind.currentData(),
                                           filters=self._filters())
        except ApiError as exc:
            error(self, str(exc))
            return
        headers = self.result["headers"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        W.fill_table(self.table, self.result["rows"], stretch_column=min(1, len(headers) - 1))
        self.note.setText(self.result["note"])
        self.print_btn.setEnabled(bool(self.result["rows"]))
        self.pdf_btn.setEnabled(bool(self.result["rows"]))
        self.csv_btn.setEnabled(bool(self.result["rows"]))
        self.excel_btn.setEnabled(bool(self.result["rows"]))

    def _export(self, fmt: str) -> None:
        try:
            path = self.client.call("reports.export", report_type=self.kind.currentData(),
                                    filters=self._filters(), format=fmt)["path"]
        except ApiError as exc:
            error(self, str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        info(self, f"حُفظ الملف:\n{path}")
