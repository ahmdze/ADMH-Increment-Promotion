"""شاشة الدخول والتهيئة الأولى."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .. import __version__
from ..config import APP_NAME, asset_path
from ..server.client import ApiClient, ApiError
from . import theme, widgets as W
from .app_settings import AppSettings


class LoginDialog(QDialog):
    def __init__(self, client: ApiClient, settings: AppSettings, parent=None,
                 local_mode: bool = False) -> None:
        super().__init__(parent)
        self.client = client
        self.settings = settings
        self.local_mode = local_mode
        self.user: dict | None = None
        self._initialized = False
        self._setup_started = False
        self.setWindowTitle("الدخول — " + APP_NAME)
        self.setMinimumSize(560, 660)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()
        QTimer.singleShot(60, self._probe)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        logo = asset_path("logo_small.png")
        if logo.exists():
            mark = QLabel()
            mark.setPixmap(QPixmap(str(logo)).scaled(
                56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            top.addWidget(mark)
        else:
            top.addWidget(W.badge("HR"))
        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel(APP_NAME)
        name.setObjectName("Brand")
        name.setWordWrap(True)
        titles.addWidget(name)
        titles.addWidget(W.muted(f"الإصدار {__version__} — سجل وظيفي وعلاوات وترفيعات"))
        top.addLayout(titles, 1)
        self.theme_btn = W.button("", "Ghost", self._toggle_theme, width=40)
        self.theme_btn.setToolTip("تبديل الثيم")
        top.addWidget(self.theme_btn)
        root.addLayout(top)

        # -------------------------------------------------------------
        connection = W.card()
        conn_layout = QVBoxLayout(connection)
        conn_layout.setContentsMargins(16, 14, 16, 14)
        conn_layout.setSpacing(8)
        conn_layout.addWidget(W.muted(
            "الخدمة المحلية (تعمل على هذا الجهاز)" if self.local_mode
            else "عنوان الخدمة"))
        row = QHBoxLayout()
        self.server = QLineEdit(self.client.base_url or self.settings.server_url)
        self.server.setPlaceholderText("http://192.168.1.10:8765")
        if self.local_mode:
            self.server.setReadOnly(True)
        row.addWidget(self.server, 1)
        self.connect_btn = W.button("إعادة المحاولة" if self.local_mode else "اتصال",
                                    "Ghost", self._probe,
                                    width=110 if self.local_mode else 80)
        row.addWidget(self.connect_btn)
        conn_layout.addLayout(row)
        self.status = QLabel("جارٍ الاتصال…")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        conn_layout.addWidget(self.status)
        root.addWidget(connection)

        # -------------------------------------------------------------
        form_card = W.card()
        form = QVBoxLayout(form_card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        form.addWidget(W.muted("اسم المستخدم"))
        self.username = QLineEdit(self.settings.last_username)
        self.username.setPlaceholderText("مثال: admin أو h1-1")
        form.addWidget(self.username)
        form.addWidget(W.muted("كلمة المرور"))
        pass_row = QHBoxLayout()
        pass_row.setSpacing(6)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("أدخل كلمة المرور")
        self.password.returnPressed.connect(self._login)
        pass_row.addWidget(self.password, 1)
        self.show_btn = W.button("إظهار", "Ghost", self._toggle_password, width=70)
        pass_row.addWidget(self.show_btn)
        form.addLayout(pass_row)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        form.addWidget(self.error)
        self.login_btn = W.button("دخول", "Accent", self._login)
        self.login_btn.setMinimumHeight(42)
        self.login_btn.setDefault(True)
        form.addWidget(self.login_btn)
        root.addWidget(form_card)

        self.setup_btn = W.button("تهيئة أولى: إنشاء مدير المركز", "Ghost", self._setup)
        self.setup_btn.setVisible(False)
        root.addWidget(self.setup_btn)

        root.addStretch()
        footer = W.muted("البيانات محلية على جهازك — لا يعمل النظام عبر الإنترنت.")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)
        self._sync_theme_text()

    # ------------------------------------------------------------------
    def _sync_theme_text(self) -> None:
        self.theme_btn.setText("☀" if theme.resolve(self.settings.theme) == "light" else "☾")

    def _toggle_theme(self) -> None:
        self.settings.theme = theme.next_theme(self.settings.theme)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(self.settings.theme))
        self._sync_theme_text()

    def _toggle_password(self) -> None:
        shown = self.password.echoMode() == QLineEdit.EchoMode.Normal
        self.password.setEchoMode(
            QLineEdit.EchoMode.Password if shown else QLineEdit.EchoMode.Normal)
        self.show_btn.setText("إظهار" if shown else "إخفاء")

    def _set_status(self, text: str, ok: bool) -> None:
        colors = theme.palette(self.settings.theme)
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colors['success'] if ok else colors['danger']};")

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    # ------------------------------------------------------------------
    def _probe(self) -> None:
        url = self.server.text().strip() or self.settings.server_url
        self.client.base_url = url
        self.connect_btn.setEnabled(False)
        self._set_status("جارٍ الاتصال…", True)
        try:
            info = self.client.health()
            status = self.client.bootstrap_status()
            self._initialized = bool(status.get("initialized"))
            self._set_status(f"متصل — {info.get('app', '')} {info.get('app_version') or ''}".strip(),
                             True)
            if not self._initialized:
                self._set_status("متصل — النظام غير مُهيّأ بعد. أنشئ مدير المركز.", True)
            self.setup_btn.setVisible(not self._initialized)
            self.login_btn.setEnabled(self._initialized)
            if not self.local_mode:
                self.settings.server_url = url
            if not self._initialized and self.isVisible() and not self._setup_started:
                self._setup_started = True
                QTimer.singleShot(0, self._setup)
        except ApiError as exc:
            if self.local_mode:
                message = ("تعذّر بدء الخدمة المحلية. تأكد من عدم تشغيل نسخة أخرى من "
                           "البرنامج على الجهاز نفسه، ثم اضغط «إعادة المحاولة».")
            else:
                message = (
                    "تعذّر الاتصال بالخدمة.\n"
                    "• لمستخدم واحد: أغلق البرنامج وشغّله بلا وسائط (python run.py).\n"
                    "• لخدمة مشتركة: شغّل على جهاز الخدمة (python run.py --server) "
                    "ثم أدخل عنوانه أعلاه واضغط «اتصال».\n"
                    f"التفصيل: {exc}")
            self._set_status(message, False)
            self.login_btn.setEnabled(False)
            self.setup_btn.setVisible(False)
        finally:
            self.connect_btn.setEnabled(True)

    def _login(self) -> None:
        if not self._initialized:
            return
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self._show_error("أدخل اسم المستخدم وكلمة المرور.")
            return
        self.login_btn.setEnabled(False)
        self.login_btn.setText("جارٍ الدخول…")
        self._show_error("")
        try:
            result = self.client.login(username, password)
        except ApiError as exc:
            message = str(exc)
            if exc.code == "bad_credentials":
                message = (message + "\nتأكد من اسم المستخدم كما هو في البطاقة (مثل unit-1)، "
                           "ومن حالة الأحرف (A/a) وعدم وجود مسافة زائدة. "
                           "استخدم زر «إظهار» للتحقق مما كتبته.")
            self._show_error(message)
            self.login_btn.setEnabled(True)
            self.login_btn.setText("دخول")
            return
        self.settings.last_username = username
        if not self.local_mode:
            self.settings.server_url = self.client.base_url
        self.user = result.get("user")
        self.accept()

    def _setup(self) -> None:
        dialog = SetupDialog(self.client, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.user:
            self.user = dialog.user
            self.settings.last_username = self.user.get("username", "")
            self.accept()


class SetupDialog(QDialog):
    """إنشاء مدير المركز الأول."""

    def __init__(self, client: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.user: dict | None = None
        self.setWindowTitle("التهيئة الأولى")
        self.setMinimumWidth(480)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        root.addWidget(W.title("إنشاء مدير المركز", 16))
        root.addWidget(W.muted(
            "هذا الحساب يدير المؤسسات والمستخدمين والقواعد، ويعتمد النتائج نهائياً. "
            "اختر كلمة مرور قوية واحفظها في مكان آمن."))

        root.addWidget(W.muted("اسم المستخدم"))
        self.username = QLineEdit("admin")
        root.addWidget(self.username)
        root.addWidget(W.muted("الاسم الظاهر"))
        self.display = QLineEdit("مدير المركز")
        root.addWidget(self.display)
        root.addWidget(W.muted("كلمة المرور (8 أحرف على الأقل)"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(self.password)
        root.addWidget(W.muted("تأكيد كلمة المرور"))
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.returnPressed.connect(self._create)
        root.addWidget(self.confirm)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        create = W.button("إنشاء ودخول", "Accent", self._create, width=160)
        create.setMinimumHeight(38)
        buttons.addWidget(create)
        buttons.addStretch()
        buttons.addWidget(W.button("إلغاء", "Ghost", self.reject, width=100))
        root.addLayout(buttons)

    def _create(self) -> None:
        password = self.password.text()
        if password != self.confirm.text():
            self._fail("كلمتا المرور غير متطابقتين.")
            return
        try:
            self.client.create_admin(self.username.text().strip(), password,
                                     self.display.text().strip())
            result = self.client.login(self.username.text().strip(), password)
        except ApiError as exc:
            self._fail(str(exc))
            return
        self.user = result.get("user")
        self.accept()

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)
