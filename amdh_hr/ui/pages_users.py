"""صفحة المستخدمين."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout

from .. import permissions as P
from ..exporters import html as H
from ..server.client import ApiError
from ..util import stamp
from . import widgets as W
from .dialogs_users import PasswordDialog, UserDialog
from .notify import confirm, error, info
from .pages_base import BasePage


class UsersPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        self.add_btn = W.button("مستخدم جديد", "Accent", self._add, width=150)
        self.print_btn = W.button("طباعة القائمة", "Ghost", self._print_list, width=130)
        self.refresh_btn = W.button("تحديث", "Ghost", self.refresh, width=100)
        root.addWidget(W.page_header(
            "المستخدمون", "حسابات المركز والمؤسسات، الأدوار، وصلاحيات الدخول",
            [self.add_btn, self.print_btn, self.refresh_btn]))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.edit_btn = W.button("تعديل", "Ghost", self._edit, width=100)
        self.reset_btn = W.button("تصفير كلمة المرور", "Ghost", self._reset, width=170)
        self.toggle_btn = W.button("تعطيل", "Ghost", self._toggle, width=110)
        for button in (self.edit_btn, self.reset_btn, self.toggle_btn):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو المؤسسة…")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)

        self.table = W.table(["المستخدم", "الاسم الظاهر", "الدور", "المؤسسة",
                              "الحالة", "آخر دخول"])
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(lambda _index: self._edit())
        root.addWidget(self.table, 1)
        self.note = W.muted("")
        root.addWidget(self.note)

        self.users: list[dict] = []
        self.visible: list[dict] = []
        self.units: list[dict] = []
        self._sync_buttons()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self.users = self.client.call("users.list").get("users", [])
            self.units = self.client.call("units.list").get("units", [])
        except ApiError as exc:
            self.note.setText(str(exc))
            return
        self._apply_filter()
        self.note.setText(f"{len(self.users)} حساب. تُدار كلمات المرور من هنا؛ "
                          "ولا تُخزَّن نصاً صريحاً.")

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        self.visible = [user for user in self.users
                        if not text
                        or text in str(user.get("username", "")).lower()
                        or text in str(user.get("display_name", "")).lower()
                        or text in str(user.get("unit_name") or "").lower()]
        rows = [[user.get("username"), user.get("display_name") or "—",
                 user.get("role_label") or P.ROLE_LABELS.get(user.get("role"), ""),
                 user.get("unit_name") or "كل المؤسسات",
                 "نشط" if user.get("active") else "معطّل",
                 user.get("last_login") or "—"] for user in self.visible]
        W.fill_table(self.table, rows, stretch_column=1)
        self._sync_buttons()

    def _selected(self) -> dict | None:
        row = W.selected_row(self.table)
        return self.visible[row] if 0 <= row < len(self.visible) else None

    def _sync_buttons(self) -> None:
        user = self._selected()
        has = user is not None
        self.edit_btn.setEnabled(has)
        self.reset_btn.setEnabled(has)
        self.toggle_btn.setEnabled(has and user.get("username") != self.user.get("username"))
        if has:
            self.toggle_btn.setText("تفعيل" if not user.get("active") else "تعطيل")

    # ------------------------------------------------------------------
    def _print_list(self) -> None:
        if not self.users:
            info(self, "لا توجد حسابات لطباعتها.", "طباعة القائمة")
            return
        rows = [[user.get("username"), user.get("display_name") or "—",
                 user.get("role_label") or P.ROLE_LABELS.get(user.get("role"), ""),
                 user.get("unit_name") or "كل المؤسسات",
                 "نشط" if user.get("active") else "معطّل",
                 user.get("last_login") or "—"] for user in self.users]
        document = H.table_page(
            "قائمة المستخدمين",
            ["المستخدم", "الاسم الظاهر", "الدور", "المؤسسة", "الحالة", "آخر دخول"],
            rows, subtitle=f"{len(self.users)} حساب",
            center_name=self.meta.get("center", ""))
        path = H.save(document, self.reports_dir, f"قائمة_المستخدمين_{stamp()}.html")
        H.open_in_browser(path)
        info(self, f"فُتحت القائمة في المتصفح للطباعة:\n{path}", "طباعة القائمة")

    # ------------------------------------------------------------------
    def _add(self) -> None:
        dialog = UserDialog(self, self.client, self.units)
        if not dialog.exec() or not dialog.result:
            return
        self.refresh()
        password = dialog.result.get("password")
        if password:
            username = (dialog.result.get("user") or {}).get("username", "")
            PasswordDialog(self, username, password).exec()
        else:
            info(self, "أُنشئ المستخدم. عيّن كلمة مروره من «تصفير كلمة المرور».")

    def _edit(self) -> None:
        user = self._selected()
        if not user:
            return
        dialog = UserDialog(self, self.client, self.units, user=user)
        if dialog.exec():
            self.refresh()

    def _reset(self) -> None:
        user = self._selected()
        if not user:
            return
        if not confirm(self, f"تصفير كلمة مرور «{user['username']}» وإظهار كلمة جديدة مرة واحدة؟"):
            return
        try:
            result = self.client.call("users.reset_password", user_id=user["user_id"])
        except ApiError as exc:
            error(self, str(exc))
            return
        PasswordDialog(self, user["username"], result.get("password", ""),
                       user.get("role_label", "")).exec()

    def _toggle(self) -> None:
        user = self._selected()
        if not user:
            return
        active = not user.get("active")
        action = "تفعيل" if active else "تعطيل"
        if not confirm(self, f"{action} حساب «{user['username']}»؟"):
            return
        try:
            self.client.call("users.set_active", user_id=user["user_id"], active=active)
        except ApiError as exc:
            error(self, str(exc))
            return
        self.refresh()
