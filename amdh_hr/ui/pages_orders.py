"""صفحة الأوامر."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout

from ..exporters import html as H
from ..server.client import ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_order import OrderDialog, OrderViewDialog
from .notify import confirm, error, info
from .pages_base import BasePage


class OrdersPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        self.add_btn = W.button("أمر جديد", "Accent", self._add, width=110)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "الأوامر", "أوامر الترفيع والعلاوة، فردية أو جماعية، ومرفقاتها",
            [self.add_btn, self.refresh_btn]))
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.view_btn = W.button("عرض", "Ghost", self._view, width=80)
        self.approve_btn = W.button("اعتماد", "Ghost", self._approve, width=90)
        self.delete_btn = W.button("حذف", "Danger", self._delete, width=80)
        toolbar.addWidget(self.view_btn)
        toolbar.addWidget(self.approve_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث برقم الأمر…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)
        self.table = W.table(["التاريخ", "الرقم", "النوع", "الجهة", "المستفيدون",
                              "الحالة", "المؤسسة"])
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.doubleClicked.connect(lambda _index: self._view())
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        self.orders: list[dict] = []
        self.visible: list[dict] = []
        self.add_btn.setVisible(self.can("edit_orders"))
        self.delete_btn.setVisible(self.can("edit_orders"))
        self.approve_btn.setVisible(self.can("approve_orders"))
        self._sync()

    def refresh(self) -> None:
        try:
            self.orders = self.client.call("orders.list")["orders"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        self._filter()
        self.note.setText(f"{len(self.orders)} أمر — معتمد "
                          f"{sum(1 for row in self.orders if row['status'] == 'approved')}")

    def _filter(self) -> None:
        text = self.search.text().strip().lower()
        self.visible = [row for row in self.orders
                        if not text or text in str(row.get("order_no", "")).lower()]
        W.fill_table(self.table, [
            [row.get("order_date"), row.get("order_no"), row.get("type_label"),
             row.get("issuer") or "—", row.get("recipients_count"), row.get("status_label"),
             row.get("unit_name") or "—"] for row in self.visible], stretch_column=3)
        self._sync()

    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def _sync(self) -> None:
        row = self._selected()
        has = row is not None
        self.view_btn.setEnabled(has)
        self.approve_btn.setEnabled(has and row.get("status") != "approved")
        self.delete_btn.setEnabled(has and row.get("status") != "approved")

    def _add(self) -> None:
        try:
            units = self.client.call("units.list")["units"]
            employees = self.client.call("employees.list", limit=2000)["employees"]
        except ApiError as exc:
            error(self, str(exc))
            return
        if not employees:
            info(self, "لا يوجد موظفون بعد.")
            return
        dialog = OrderDialog(self, self.client, self.user, units, employees)
        if dialog.exec():
            self.refresh()

    def _view(self) -> None:
        row = self._selected()
        if not row:
            return
        OrderViewDialog(self, self.client, row["order_id"], self.meta,
                        can_approve=self.can("approve_orders"),
                        can_edit=self.can("edit_orders")).exec()
        self.refresh()

    def _approve(self) -> None:
        row = self._selected()
        if not row:
            return
        try:
            self.client.call("orders.approve", order_id=row["order_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        row = self._selected()
        if not row:
            return
        if not confirm(self, f"حذف الأمر «{row['order_no']}»؟"):
            return
        try:
            self.client.call("orders.delete", order_id=row["order_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()
