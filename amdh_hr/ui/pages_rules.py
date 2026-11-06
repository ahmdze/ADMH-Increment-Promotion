"""صفحة القواعد: الحزم، الإصدارات، نشر القواعد، وتحريرها."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

from ..server.client import ApiError
from . import widgets as W
from .dialogs_rule import PackageDialog, RuleDialog
from .notify import confirm, error, info
from .pages_base import BasePage


def _scope_text(row: dict) -> str:
    scope = row.get("scope_data") or {}
    parts = []
    if scope.get("grade"):
        parts.append(f"درجة {scope['grade']}")
    if scope.get("stage"):
        parts.append(f"مرحلة {scope['stage']}")
    if scope.get("issuer_type"):
        labels = {"president": "رئيس الجمهورية", "prime_minister": "رئيس الوزراء",
                  "minister": "الوزير المختص", "authority_head": "رئيس جهة",
                  "undersecretary": "الوكيل", "governor": "المحافظ",
                  "director_general": "المدير العام", "other": "أخرى"}
        parts.append(labels.get(scope["issuer_type"], scope["issuer_type"]))
    if scope.get("job_title"):
        parts.append(f"عنوان {scope['job_title']}")
    if scope.get("category"):
        parts.append(f"فئة {scope['category']}")
    return " · ".join(parts) or "عام"


def _params_text(row: dict) -> str:
    params = row.get("params_data") or {}
    if row["rule_type"] == "promotion":
        return (f"{params.get('required_months', '—')} شهراً"
                + (f" → {params.get('to_grade')}/{params.get('to_stage')}"
                   if params.get("to_grade") else ""))
    if row["rule_type"] == "increment":
        return f"كل {params.get('required_months', '—')} شهراً"
    if params.get("months"):
        text = f"{params['months']} أشهر"
        if params.get("cap_months"):
            text += f" (سقف {params['cap_months']} سنوياً)"
        return text
    return f"{params.get('days', 0)} يوماً" + (
        f" (سقف {params['cap_days']})" if params.get("cap_days") else "")


class RulesPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        self.new_btn = W.button("حزمة جديدة", "Accent", self._new_package, width=120)
        self.version_btn = W.button("إصدار جديد", "Ghost", self._new_version, width=120)
        self.publish_btn = W.button("نشر", "Ghost", self._publish, width=90)
        self.matrix_btn = W.button("المصفوفة المعتمدة", "Ghost", self._seed_matrix, width=160)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "القواعد", "مدد الترفيع والعلاوات وأثر كتب الشكر — بإصدارات مؤرخة وسند قانوني",
            [self.new_btn, self.version_btn, self.publish_btn, self.matrix_btn,
             self.refresh_btn]))

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(W.muted("الحزمة"))
        self.packages = QComboBox()
        self.packages.setMinimumWidth(360)
        self.packages.currentIndexChanged.connect(self._load)
        bar.addWidget(self.packages, 1)
        self.status = QLabel("")
        self.status.setObjectName("Chip")
        bar.addWidget(self.status)
        root.addLayout(bar)

        rows_bar = QHBoxLayout()
        rows_bar.addWidget(W.muted("قواعد الحزمة"))
        rows_bar.addStretch()
        self.add_row_btn = W.button("قاعدة جديدة", "Accent", self._add_row, width=120)
        self.edit_row_btn = W.button("تعديل", "Ghost", self._edit_row, width=90)
        self.delete_row_btn = W.button("حذف", "Danger", self._delete_row, width=80)
        for button in (self.add_row_btn, self.edit_row_btn, self.delete_row_btn):
            rows_bar.addWidget(button)
        root.addLayout(rows_bar)

        self.table = W.table(["النوع", "الاسم", "النطاق", "المعاملات", "الأولوية"])
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.doubleClicked.connect(lambda _index: self._edit_row())
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)

        self.package: dict | None = None
        self.titles: list[dict] = []
        self.new_btn.setVisible(self.can("edit_rules"))
        self.version_btn.setVisible(self.can("edit_rules"))
        self.add_row_btn.setVisible(self.can("edit_rules"))
        self.edit_row_btn.setVisible(self.can("edit_rules"))
        self.delete_row_btn.setVisible(self.can("edit_rules"))
        self.publish_btn.setVisible(self.can("publish_rules"))
        self._sync()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            packages = self.client.call("rules.packages")["packages"]
            self.titles = self.client.call("titles.list")["titles"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        current = self.package["package_id"] if self.package else ""
        self.packages.blockSignals(True)
        self.packages.clear()
        for package in packages:
            self.packages.addItem(f"{package['code']} — إصدار {package['version']} "
                                  f"({package['status_label']})", package["package_id"])
        index = self.packages.findData(current)
        self.packages.setCurrentIndex(max(0, index))
        self.packages.blockSignals(False)
        if packages:
            self._load()
        else:
            self.package = None
            self.table.setRowCount(0)
            self.status.setText("لا توجد حزم")
            self._sync()

    def _load(self) -> None:
        package_id = self.packages.currentData()
        if not package_id:
            return
        try:
            self.package = self.client.call("rules.get", package_id=package_id)["package"]
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        package = self.package
        self.status.setText(f"{package['status_label']} · نفاذ {package['effective_from']}")
        W.fill_table(self.table, [
            [row["type_label"], row["name"], _scope_text(row), _params_text(row),
             row["priority"]] for row in package["rows"]], stretch_column=2)
        self.note.setText(
            f"{len(package['rows'])} قاعدة. الحزمة المنشورة غير قابلة للتعديل؛ "
            "استخدم «إصدار جديد».")
        self._sync()

    def _sync(self) -> None:
        package = self.package
        draft = bool(package and package["status"] == "draft")
        editable = self.can("edit_rules")
        self.add_row_btn.setEnabled(draft and editable)
        self.edit_row_btn.setEnabled(draft and editable and bool(self._selected()))
        self.delete_row_btn.setEnabled(draft and editable and bool(self._selected()))
        self.publish_btn.setEnabled(draft and bool(package and package["rows"])
                                    and self.can("publish_rules"))
        self.version_btn.setEnabled(bool(package))

    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        rows = (self.package or {}).get("rows") or []
        return rows[row] if 0 <= row < len(rows) else None

    # ------------------------------------------------------------------
    def _new_package(self) -> None:
        if PackageDialog(self, self.client, self.user).exec():
            self.refresh()

    def _new_version(self) -> None:
        if not self.package:
            return
        if not confirm(self, f"إنشاء إصدار جديد من {self.package['code']}؟"):
            return
        try:
            result = self.client.call("rules.new_version",
                                      package_id=self.package["package_id"])["package"]
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()
        index = self.packages.findData(result["package_id"])
        if index >= 0:
            self.packages.setCurrentIndex(index)

    def _seed_matrix(self) -> None:
        if not confirm(self, "إنشاء حزمة المصفوفة القانونية المعتمدة ونشرها؟\n"
                             "لن تُكرر إن كانت موجودة."):
            return
        try:
            package = self.client.call("rules.seed_matrix")["package"]
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, f"المصفوفة جاهزة: {package['code']} إصدار {package['version']}")
        self.refresh()
        index = self.packages.findData(package["package_id"])
        if index >= 0:
            self.packages.setCurrentIndex(index)

    def _publish(self) -> None:
        if not self.package:
            return
        if not confirm(self, "نشر الحزمة؟ تصبح نافذة للاحتساب ولا تُعدّل بعدها."):
            return
        try:
            self.client.call("rules.publish", package_id=self.package["package_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        info(self, "نُشرت الحزمة.")
        self.refresh()

    def _add_row(self) -> None:
        if not self.package or self.package["status"] != "draft":
            return
        if RuleDialog(self, self.client, self.package["package_id"], self.titles).exec():
            self._load()

    def _edit_row(self) -> None:
        row = self._selected()
        if not row or not self.package or self.package["status"] != "draft":
            return
        if RuleDialog(self, self.client, self.package["package_id"], self.titles,
                      row=row).exec():
            self._load()

    def _delete_row(self) -> None:
        row = self._selected()
        if not row or not self.package or self.package["status"] != "draft":
            return
        if not confirm(self, f"حذف القاعدة «{row['name']}»؟"):
            return
        try:
            self.client.call("rules.delete_row", rule_id=row["rule_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        self._load()
