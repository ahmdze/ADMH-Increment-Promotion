"""صفحة المزامنة: تصدير/استيراد حزم المؤسسات والقواعد عبر USB."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QVBoxLayout

from ..server.client import ApiError
from . import widgets as W
from .dialogs_conflicts import ConflictDialog
from .dialogs_crypto import ask_package_password
from .notify import confirm, error, info
from .pages_base import BasePage


class SyncPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(W.page_header(
            "المزامنة", "حزم USB: بيانات المؤسسة إلى المركز، والقواعد من المركز إلى المؤسسة"))

        self.status = W.muted("")
        root.addWidget(self.status)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.export_data_btn = W.button("تصدير بيانات للمركز", "Accent", self._export_data, width=180)
        self.import_data_btn = W.button("استيراد حزمة مؤسسة", "Ghost", self._import_data, width=170)
        self.export_rules_btn = W.button("تصدير حزمة قواعد", "Ghost", self._export_rules, width=160)
        self.import_rules_btn = W.button("استيراد حزمة قواعد", "Ghost", self._import_rules, width=170)
        self.export_results_btn = W.button("تصدير نتائج الاعتماد", "Ghost",
                                           self._export_results, width=170)
        self.import_results_btn = W.button("استيراد نتائج الاعتماد", "Ghost",
                                           self._import_results, width=170)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        for button in (self.export_data_btn, self.import_data_btn, self.export_rules_btn,
                       self.import_rules_btn, self.export_results_btn,
                       self.import_results_btn, self.refresh_btn):
            toolbar.addWidget(button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.export_data_btn.setVisible(self.can("export_package") and
                                        self.user.get("role") in {"unit_manager", "unit_editor"})
        self.import_data_btn.setVisible(self.can("import_package"))
        self.export_rules_btn.setVisible(self.can("publish_rules"))
        self.import_rules_btn.setVisible(self.can("import_rules"))
        self.export_results_btn.setVisible(self.can("approve_final"))
        self.import_results_btn.setVisible(self.can("import_results"))

        root.addWidget(W.muted("الحزم الجاهزة في مجلد التصدير"))
        self.files_table = W.table(["الملف", "الحجم (KB)", "التشفير", "آخر تعديل"])
        self.files_table.setMaximumHeight(180)
        root.addWidget(self.files_table)

        root.addWidget(W.muted("سجل الحزم"))
        self.log_table = W.table(["التاريخ", "الاتجاه", "المؤسسة", "الحالة", "ملاحظة"])
        root.addWidget(self.log_table, 1)
        self.open_btn = W.button("فتح مجلد التصدير", "Ghost", self._open_exports, width=160)
        root.addWidget(self.open_btn)
        self.files: list[dict] = []

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        meta = self.meta
        self.status.setText(f"مركز الدائرة: {meta.get('center') or '—'} · "
                            f"المؤسسة: {meta.get('provisioned_unit') or '—'}")
        try:
            self.files = self.client.call("sync.packages")["packages"]
            log = self.client.call("sync.log")["packages"]
        except ApiError as exc:
            self.status.setText(str(exc))
            return
        W.fill_table(self.files_table, [
            [row["name"], row["size_kb"], "مشفرة" if row.get("encrypted") else "نصية",
             datetime.fromtimestamp(row["modified"]).strftime(
                "%Y-%m-%d %H:%M")] for row in self.files], stretch_column=0)
        labels = {"exported": "مصدّرة", "imported": "مستوردة", "rejected": "مرفوضة"}
        W.fill_table(self.log_table, [
            [row["created_at"], row["direction_label"], row["source_unit_name"] or "—",
             labels.get(row["status"], row["status"]),
             _counts_text(row)] for row in log],
            stretch_column=4)

    def _run_export(self, method: str) -> None:
        password = ask_package_password(self, "تشفير حزمة USB", confirm=True)
        if not password:
            return
        try:
            result = self.client.call(method, password=password)
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"حُفظت الحزمة المشفرة:\n{result['path']}")
        self.refresh()

    def _export_data(self) -> None:
        self._run_export("sync.export_data")

    def _export_rules(self) -> None:
        self._run_export("sync.export_rules")

    def _import_data(self) -> None:
        self._import("sync.import", "حزمة مؤسسة")

    def _import_rules(self) -> None:
        self._import("sync.import_rules", "حزمة قواعد")

    def _import_results(self) -> None:
        self._import("sync.import_results", "نتائج الاعتماد")

    def _export_results(self) -> None:
        try:
            units = [unit for unit in self.client.call("units.list")["units"]
                     if not unit.get("is_center")]
        except ApiError as exc:
            error(self, str(exc))
            return
        if not units:
            info(self, "لا توجد مؤسسات.")
            return
        names = [f"{unit['name']} ({unit['code']})" for unit in units]
        choice, accepted = QInputDialog.getItem(self, "تصدير نتائج الاعتماد", "المؤسسة:",
                                                names, 0, False)
        if not accepted:
            return
        unit = units[names.index(choice)]
        password = ask_package_password(self, "تشفير حزمة النتائج", confirm=True)
        if not password:
            return
        try:
            result = self.client.call("sync.export_results", unit_id=unit["unit_id"],
                                      password=password)
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"حُفظت حزمة النتائج المشفرة:\n{result['path']}")
        self.refresh()

    def _import(self, method: str, title: str) -> None:
        folder = str(Path(self.meta.get("data_dir", ".")) / "exports")
        path, _filter = QFileDialog.getOpenFileName(self, title, folder,
                                                    "حزم (*.amdhpkg);;كل الملفات (*)")
        if not path:
            return
        password = ask_package_password(self, "فتح حزمة USB", confirm=False)
        if password is None:
            return
        try:
            preview = self.client.call("sync.preview", path=path, password=password)
        except ApiError as exc:
            error(self, str(exc))
            return
        counts = preview.get("counts", {})
        if preview.get("duplicate"):
            info(self, "هذه الحزمة سبق استيرادها.")
            return
        resolutions: dict[str, str] = {}
        if (preview["manifest"].get("direction") == "institution_data"
                and counts.get("conflicts")):
            try:
                conflicts = self.client.call("sync.conflicts", path=path,
                                             password=password)["conflicts"]
            except ApiError as exc:
                error(self, str(exc))
                return
            if conflicts:
                dialog = ConflictDialog(self, conflicts)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                resolutions = dialog.resolutions
        if preview["manifest"].get("direction") == "institution_data":
            message = (f"المؤسسة: {preview['manifest'].get('unit_name')}\n"
                       f"موظفون جدد: {counts.get('new_employees', 0)} — "
                       f"تحديثات: {counts.get('updated_employees', 0)}\n"
                       f"تعارضات رقم وظيفي: {counts.get('conflicts', 0)}\n"
                       f"كتب: {counts.get('new_letters', 0)} — أوامر: "
                       f"{counts.get('new_orders', 0)} — وثائق: "
                       f"{counts.get('new_documents', 0)}\n\n"
                       "سيتم أخذ نسخة احتياطية قبل الدمج. هل تريد المتابعة؟")
        elif preview["manifest"].get("direction") == "center_results":
            message = (f"نتائج الاعتماد للمؤسسة: "
                       f"{preview['manifest'].get('unit_name')}\n"
                       f"كتب معتمدة: {counts.get('letters', 0)} — "
                       f"أوامر معتمدة: {counts.get('orders', 0)}\n\nهل تريد الاستيراد؟")
        else:
            message = (f"حزم القواعد: {counts.get('packages', 0)} — جديدة: "
                       f"{counts.get('new_packages', 0)}\n\nهل تريد الاستيراد؟")
        if not confirm(self, message, "معاينة الحزمة"):
            return
        try:
            result = self.client.call(method, path=path, resolutions=resolutions,
                                      password=password)
        except ApiError as exc:
            error(self, str(exc))
            return
        if result.get("already_imported"):
            info(self, "هذه الحزمة سبق استيرادها.")
        else:
            info(self, "تم الاستيراد:\n" + "\n".join(
                f"{key}: {value}" for key, value in result.items()
                if key not in {"already_imported", "package_id"}))
        self.refresh()

    def _open_exports(self) -> None:
        folder = Path(self.meta.get("data_dir", ".")) / "exports"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _counts_text(row: dict) -> str:
    counts = (row.get("manifest_data") or {}).get("counts") or {}
    if not isinstance(counts, dict):
        return str(counts)
    labels = {"employees": "موظف", "letters": "كتاب", "orders": "أمر",
              "documents": "وثيقة", "packages": "حزمة", "rules": "قاعدة"}
    return "، ".join(f"{value} {labels.get(key, key)}" for key, value in counts.items())
