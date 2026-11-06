"""صفحة المؤسسات."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout

from ..exporters import html as H
from ..server.client import ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_credentials import CredentialsDialog
from .dialogs_units import ProvisionDialog, UnitDialog
from .notify import confirm, error, info
from .pages_base import BasePage
from .util_ui import copy_credentials


class UnitsPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        self.add_btn = W.button("مؤسسة جديدة", "Accent", self._add, width=150)
        self.print_btn = W.button("طباعة القائمة", "Ghost", self._print_list, width=130)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "المؤسسات", "إدارة مؤسسات الدائرة، حساباتها، وتجهيز نسخها",
            [self.add_btn, self.print_btn, self.refresh_btn]))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.edit_btn = W.button("تعديل", "Ghost", self._edit, width=100)
        self.reset_btn = W.button("تصفير كلمات المرور", "Ghost", self._reset, width=180)
        self.provision_btn = W.button("تجهيز نسخة", "Ghost", self._provision, width=140)
        self.card_btn = W.button("فتح آخر بطاقة", "Ghost", self._open_last_card, width=140)
        self.delete_btn = W.button("حذف", "Danger", self._delete, width=90)
        for button in (self.edit_btn, self.reset_btn, self.provision_btn, self.card_btn,
                       self.delete_btn):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الرمز…")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)

        self.table = W.table(["المؤسسة", "تصدير", "الرمز", "النوع", "الحسابات",
                              "الموظفون", "الحالة", "مدير المؤسسة", "آخر تحديث"])
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(lambda _index: self._edit())
        root.addWidget(self.table, 1)

        self.note = W.muted("")
        root.addWidget(self.note)
        self.units: list[dict] = []
        self.visible: list[dict] = []
        self._sync_buttons()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self.units = self.client.call("units.list").get("units", [])
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        self._apply_filter()
        self.note.setText(f"{len(self.units)} مؤسسة — الحد الأقصى للحسابات في المؤسسة 5.")

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        self.visible = [unit for unit in self.units
                        if not text or text in str(unit.get("name", "")).lower()
                        or text in str(unit.get("code", "")).lower()]
        rows = [[unit.get("name"), "", unit.get("code"), unit.get("kind"),
                 unit.get("users_count", 0), unit.get("employees_count", 0),
                 "مُفعّلة" if unit.get("active") else "معطّلة",
                 unit.get("manager_user") or "—", unit.get("updated_at", "—")]
                for unit in self.visible]
        W.fill_table(self.table, rows, stretch_column=0)
        for row, unit in enumerate(self.visible):
            if unit.get("is_center"):
                continue
            button = W.button("نسخة", "Ghost",
                              lambda _checked=False, item=unit: self._export_unit(item),
                              width=72)
            button.setFixedHeight(30)
            button.setToolTip(
                "تجهيز نسخة المؤسسة (برنامج + بيانات + بيانات الدخول).\n"
                "تضمين ملفات البرنامج يتطلب تشغيل النسخة التنفيذية.")
            self.table.setCellWidget(row, 1, button)
            self.table.setRowHeight(row, 38)
        self.table.setColumnWidth(1, 96)
        self._sync_buttons()

    # ------------------------------------------------------------------
    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def _sync_buttons(self) -> None:
        unit = self._selected()
        has = unit is not None
        self.edit_btn.setEnabled(has)
        self.reset_btn.setEnabled(has and bool(unit.get("users_count")))
        self.provision_btn.setEnabled(has and not unit.get("is_center") and bool(unit.get("users_count")))
        self.card_btn.setEnabled(has and bool(unit.get("users_count")))
        self.delete_btn.setEnabled(has and not unit.get("is_center"))

    # ------------------------------------------------------------------
    def _add(self) -> None:
        dialog = UnitDialog(self, self.client, reports_dir=self.reports_dir,
                            center_name=self.meta.get("center", ""),
                            center_exists=bool(self.meta.get("center")))
        if dialog.exec() and dialog.saved:
            self.refresh()
            if dialog.credentials:
                self._show_credentials(dialog.saved, dialog.credentials)

    def _edit(self) -> None:
        unit = self._selected()
        if not unit:
            return
        dialog = UnitDialog(self, self.client, unit=unit, reports_dir=self.reports_dir,
                            center_name=self.meta.get("center", ""))
        if dialog.exec():
            self.refresh()

    def _delete(self) -> None:
        unit = self._selected()
        if not unit:
            return
        if not confirm(self,
                       f"حذف المؤسسة «{unit['name']}» وكل حساباتها نهائياً؟\n"
                       "لا يمكن التراجع، ويُسجَّل الحذف في سجل التدقيق.",
                       "حذف مؤسسة"):
            return
        try:
            result = self.client.call("units.delete", unit_id=unit["unit_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"حُذفت المؤسسة وحُذف معها {result.get('users_deleted', 0)} حساب.")
        self.refresh()

    def _reset(self) -> None:
        unit = self._selected()
        if not unit:
            return
        if not confirm(self,
                       f"تصفير كلمات مرور كل حسابات «{unit['name']}»، وإصدار بطاقة جديدة؟\n"
                       "ستتوقف كلمات المرور القديمة فوراً.",
                       "تصفير كلمات المرور"):
            return
        try:
            result = self.client.call("units.reset_users", unit_id=unit["unit_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self._show_credentials(unit, result.get("credentials") or [])

    def _open_last_card(self) -> None:
        unit = self._selected()
        if not unit:
            return
        folder = Path(self.reports_dir)
        code = unit.get("code") or "unit"
        matches = sorted(folder.glob(f"بيانات_دخول_{code}*.html"),
                         key=lambda path: path.stat().st_mtime, reverse=True)
        if not matches:
            info(self, "لا توجد بطاقة محفوظة لهذه المؤسسة. استخدم «تصفير كلمات المرور» "
                       "لإصدار بطاقة جديدة.", "بطاقة الدخول")
            return
        H.open_in_browser(matches[0])

    def _provision(self) -> None:
        unit = self._selected()
        if not unit:
            return
        self._export_unit(unit)

    def _export_unit(self, unit: dict) -> None:
        if unit.get("is_center"):
            info(self, "مركز الدائرة لا تُصدَّر له نسخة؛ هو المرجع.")
            return
        dialog = ProvisionDialog(self, self.client, unit, self.meta)
        dialog.exec()
        self.refresh()

    # ------------------------------------------------------------------
    def _print_list(self) -> None:
        if not self.units:
            info(self, "لا توجد مؤسسات لطباعتها.", "طباعة القائمة")
            return
        rows = [[unit.get("name"), unit.get("code"), unit.get("kind"),
                 unit.get("users_count", 0), unit.get("employees_count", 0),
                 "مُفعّلة" if unit.get("active") else "معطّلة",
                 unit.get("manager_user") or "—", unit.get("updated_at", "—")]
                for unit in self.units]
        document = H.table_page(
            "قائمة المؤسسات",
            ["المؤسسة", "الرمز", "النوع", "الحسابات", "الموظفون", "الحالة",
             "مدير المؤسسة", "آخر تحديث"],
            rows, subtitle=f"{len(self.units)} مؤسسة",
            center_name=self.meta.get("center", ""))
        path = H.save(document, self.reports_dir, f"قائمة_المؤسسات_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتحت القائمة في المتصفح للطباعة:\n{path}", "طباعة القائمة")

    # ------------------------------------------------------------------
    def _show_credentials(self, unit: dict, credentials: list[dict]) -> None:
        if not credentials:
            return
        page = H.credentials_page(unit, credentials, center_name=self.meta.get("center", ""))
        preview = H.credentials_preview(unit, credentials,
                                        center_name=self.meta.get("center", ""))
        dialog = CredentialsDialog(
            self, page, reports_dir=self.reports_dir,
            filename=f"بيانات_دخول_{unit.get('code') or 'unit'}",
            copy_text=copy_credentials(unit, credentials),
            title="بيانات دخول المؤسسة", preview_html=preview)
        dialog.exec()
