"""النافذة الرئيسية: الشريط الجانبي، الرأس، والصفحات."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..config import APP_NAME, asset_path
from ..server.client import ApiClient, ApiError
from . import theme, widgets as W
from .app_settings import AppSettings
from .dialogs_login import LoginDialog
from .pages_about import AboutPage
from .pages_calc import CalcPage
from .pages_dashboard import DashboardPage
from .pages_employees import EmployeesPage
from .pages_letters import LettersPage
from .pages_orders import OrdersPage
from .pages_reports import ReportsPage
from .pages_rules import RulesPage
from .pages_settings import SettingsPage
from .pages_sync import SyncPage
from .pages_units import UnitsPage
from .pages_users import UsersPage


class MainWindow(QMainWindow):
    def __init__(self, client: ApiClient, user: dict, settings: AppSettings,
                 meta: dict, local_mode: bool = False) -> None:
        super().__init__()
        self.client = client
        self.user = user
        self.settings = settings
        self.meta = meta
        self.local_mode = local_mode
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle(f"{APP_NAME} — {user.get('display_name') or user.get('username')}")
        width, height = settings.window_size
        self.resize(width, height)
        self.setMinimumSize(1060, 700)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()
        self.show_page("dashboard")

    # ------------------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(286)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = asset_path("logo_small.png")
        if logo.exists():
            mark = QLabel()
            mark.setPixmap(QPixmap(str(logo)).scaled(
                46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            brand.addWidget(mark)
        else:
            brand.addWidget(W.badge("HR"))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel("السجل الوظيفي")
        name.setObjectName("Brand")
        titles.addWidget(name)
        titles.addWidget(W.muted("علاوات وترفيعات"))
        brand.addLayout(titles, 1)
        layout.addLayout(brand)
        layout.addSpacing(6)
        layout.addWidget(W.divider())
        layout.addSpacing(4)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        specs = [
            ("dashboard", "لوحة المؤشرات", None),
            ("employees", "الموظفون", "view_employees"),
            ("letters", "كتب الشكر", "view_letters"),
            ("orders", "الأوامر", "view_orders"),
            ("calc", "الاحتساب", "view_employees"),
            ("reports", "التقارير", "export_reports"),
            ("sync", "المزامنة", "export_package"),
            ("units", "المؤسسات", "manage_units"),
            ("users", "المستخدمون", "manage_users"),
            ("rules", "القواعد", "view_settings"),
            ("settings", "الإعدادات", "view_settings"),
            ("about", "حول النظام", None),
        ]
        for code, label, permission in specs:
            if permission and not self._can(permission):
                continue
            button = QPushButton(label)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=code: self.show_page(key))
            self.group.addButton(button)
            self.nav_buttons[code] = button
            layout.addWidget(button)

        layout.addStretch()
        layout.addWidget(W.divider())
        footer = QVBoxLayout()
        footer.setSpacing(1)
        who = QLabel(self.user.get("display_name") or self.user.get("username", ""))
        who.setStyleSheet("font-weight: 700;")
        footer.addWidget(who)
        footer.addWidget(W.muted(f"{self.user.get('role_label', '')} · "
                                 f"{self.user.get('unit_name') or 'كل المؤسسات'}"))
        footer.addWidget(W.muted(f"الإصدار {__version__} — المرحلة 1"))
        layout.addLayout(footer)
        return sidebar

    # ------------------------------------------------------------------
    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(62)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 0, 22, 0)
        header_layout.setSpacing(10)
        self.header_title = QLabel(self.meta.get("center") or "مركز الدائرة")
        self.header_title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        header_layout.addWidget(self.header_title)
        header_layout.addStretch()
        header_layout.addWidget(W.chip(self.user.get("unit_name") or "كل المؤسسات"))
        header_layout.addWidget(W.chip(
            self.user.get("display_name") or self.user.get("username", "")))
        self.theme_btn = W.button("", "Ghost", self.toggle_theme, width=40)
        self.theme_btn.setToolTip("تبديل الثيم")
        header_layout.addWidget(self.theme_btn)
        self.logout_btn = W.button("تبديل المستخدم", "Ghost", self._logout, width=130)
        self.logout_btn.setToolTip("تسجيل الخروج والدخول بحساب آخر")
        header_layout.addWidget(self.logout_btn)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.pages["dashboard"] = DashboardPage(self.client, self.user, self.meta, self.settings)
        if self._can("view_employees"):
            self.pages["employees"] = EmployeesPage(self.client, self.user, self.meta,
                                                    self.settings)
            self.pages["calc"] = CalcPage(self.client, self.user, self.meta, self.settings)
        if self._can("view_letters"):
            self.pages["letters"] = LettersPage(self.client, self.user, self.meta, self.settings)
        if self._can("view_orders"):
            self.pages["orders"] = OrdersPage(self.client, self.user, self.meta, self.settings)
        if self._can("export_reports"):
            self.pages["reports"] = ReportsPage(self.client, self.user, self.meta, self.settings)
        if self._can("export_package") or self._can("import_package") or \
                self._can("import_rules") or self._can("publish_rules"):
            self.pages["sync"] = SyncPage(self.client, self.user, self.meta, self.settings)
        if self._can("manage_units"):
            self.pages["units"] = UnitsPage(self.client, self.user, self.meta, self.settings)
        if self._can("manage_users"):
            self.pages["users"] = UsersPage(self.client, self.user, self.meta, self.settings)
        if self._can("view_settings"):
            self.pages["rules"] = RulesPage(self.client, self.user, self.meta, self.settings)
            self.pages["settings"] = SettingsPage(self.client, self.user, self.meta, self.settings)
        self.pages["about"] = AboutPage(self.client, self.user, self.meta, self.settings)
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.sync_theme_button()
        return content

    # ------------------------------------------------------------------
    def _can(self, permission: str) -> bool:
        return permission in (self.user.get("permissions") or [])

    def show_page(self, code: str) -> None:
        page = self.pages.get(code)
        if page is None:
            return
        self.current_code = code
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(code)
        if button is not None:
            button.setChecked(True)
        try:
            page.refresh()
        except Exception:  # pragma: no cover - لا تُسقط الواجهة بسبب خطأ عرض
            pass

    def refresh_all(self) -> None:
        self.show_page(getattr(self, "current_code", "dashboard"))

    def sync_theme_button(self) -> None:
        self.theme_btn.setText("☀" if theme.resolve(self.settings.theme) == "light" else "☾")

    def toggle_theme(self) -> None:
        self.settings.theme = theme.next_theme(self.settings.theme)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(self.settings.theme))
        self.sync_theme_button()
        if "settings" in self.pages:
            combo = getattr(self.pages["settings"], "theme_combo", None)
            if combo is not None:
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(self.settings.theme)))
                combo.blockSignals(False)

    # ------------------------------------------------------------------
    def _logout(self) -> None:
        self.client.logout()
        self.hide()
        dialog = LoginDialog(self.client, self.settings, local_mode=self.local_mode)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.user:
            try:
                meta = self.client.call("meta.info")
            except ApiError:
                meta = self.meta
            window = MainWindow(self.client, dialog.user, self.settings, meta,
                                local_mode=self.local_mode)
            window.show()
            self.deleteLater()
        else:
            self.close()
            QApplication.quit()

    def closeEvent(self, event):  # noqa: N802 - توقيع Qt
        try:
            self.settings.save_window_size(self.width(), self.height())
            self.client.logout()
        finally:
            super().closeEvent(event)
