"""صفحة كتب الشكر."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout

from ..exporters import html as H
from ..server.client import ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_letter import LetterDialog, LetterViewDialog
from .notify import confirm, error, info
from .pages_base import BasePage


class LettersPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        self.add_btn = W.button("كتاب جديد", "Accent", self._add, width=120)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "كتب الشكر", "تسجيل الكتاب مرة واحدة وتطبيقه على المستفيدين وفق خمسة أنماط",
            [self.add_btn, self.refresh_btn]))
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.view_btn = W.button("عرض", "Ghost", self._view, width=80)
        self.approve_btn = W.button("اعتماد", "Ghost", self._approve, width=90)
        self.print_btn = W.button("طباعة المستفيدين", "Ghost", self._print, width=150)
        self.delete_btn = W.button("حذف", "Danger", self._delete, width=80)
        for button in (self.view_btn, self.approve_btn, self.print_btn, self.delete_btn):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث برقم الكتاب أو الجهة…")
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)
        self.table = W.table(["التاريخ", "الرقم", "الجهة", "النمط", "المستفيدون",
                              "الحالة", "المؤسسة"])
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.doubleClicked.connect(lambda _index: self._view())
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)
        self.letters: list[dict] = []
        self.visible: list[dict] = []
        self.add_btn.setVisible(self.can("edit_letters"))
        self.delete_btn.setVisible(self.can("edit_letters"))
        self.approve_btn.setVisible(self.can("approve_letters"))
        self._sync()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self.letters = self.client.call("letters.list")["letters"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        self._filter()
        approved = sum(1 for row in self.letters if row["status"] == "approved")
        self.note.setText(f"{len(self.letters)} كتاب — معتمد {approved} — مسودة "
                          f"{len(self.letters) - approved}")

    def _filter(self) -> None:
        text = self.search.text().strip().lower()
        self.visible = [row for row in self.letters
                        if not text or text in str(row.get("letter_no", "")).lower()
                        or text in str(row.get("issuer", "")).lower()]
        W.fill_table(self.table, [
            [row.get("letter_date"), row.get("letter_no"), row.get("issuer"),
             row.get("mode_label"), row.get("recipients_count"), row.get("status_label"),
             row.get("unit_name") or "—"] for row in self.visible], stretch_column=2)
        self._sync()

    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def _sync(self) -> None:
        letter = self._selected()
        has = letter is not None
        self.view_btn.setEnabled(has)
        self.print_btn.setEnabled(has)
        self.approve_btn.setEnabled(has and letter.get("status") != "approved")
        self.delete_btn.setEnabled(has and letter.get("status") != "approved")

    # ------------------------------------------------------------------
    def _add(self) -> None:
        try:
            units = self.client.call("units.list")["units"]
            titles = self.client.call("titles.list", active_only=True)["titles"]
            employees = self.client.call("employees.list", limit=2000)["employees"]
        except ApiError as exc:
            error(self, str(exc))
            return
        if not employees:
            info(self, "لا يوجد موظفون بعد. أضف الموظفين أولاً.")
            return
        dialog = LetterDialog(self, self.client, self.user, units, titles, employees)
        if dialog.exec():
            self.refresh()
            if dialog.result:
                info(self, f"حُفظ الكتاب وطُبّق على {dialog.result['count']} موظف."
                           + (" يحتاج بعضهم قاعدة أثر." if dialog.result.get("needs_review") else ""))

    def _view(self) -> None:
        letter = self._selected()
        if not letter:
            return
        LetterViewDialog(self, self.client, letter["letter_id"], self.meta,
                         can_approve=self.can("approve_letters"),
                         can_edit=self.can("edit_letters")).exec()
        self.refresh()

    def _approve(self) -> None:
        letter = self._selected()
        if not letter:
            return
        try:
            self.client.call("letters.approve", letter_id=letter["letter_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        letter = self._selected()
        if not letter:
            return
        if not confirm(self, f"حذف كتاب «{letter['letter_no']}»؟"):
            return
        try:
            self.client.call("letters.delete", letter_id=letter["letter_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()

    def _print(self) -> None:
        letter = self._selected()
        if not letter:
            return
        try:
            full = self.client.call("letters.get", letter_id=letter["letter_id"])["letter"]
        except ApiError as exc:
            error(self, str(exc))
            return
        rows = [[row["emp_no"], row["full_name"], row.get("unit_name") or "",
                 row.get("title_name") or "", row.get("effect_days") or 0,
                 "محتسب" if row.get("effect_state") == "computed" else "يحتاج مراجعة"]
                for row in full["recipients"]]
        document = H.table_page(
            f"مستفيدو كتاب الشكر {full['letter_no']}",
            ["الرقم", "الاسم", "المؤسسة", "العنوان", "الأثر (يوم)", "الحالة"], rows,
            subtitle=f"{full['issuer']} — {full['letter_date']}",
            center_name=self.meta.get("center", ""))
        path = H.save(document, Path(self.meta.get("data_dir", ".")) / "reports",
                      f"كتاب_شكر_{full['letter_no']}_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتحت القائمة للطباعة:\n{path}")
