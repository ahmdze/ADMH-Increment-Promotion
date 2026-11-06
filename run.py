"""مشغّل النظام.

الوضع الافتراضي: خدمة + واجهة في عملية واحدة (مستخدم واحد) — يعمل بلا أي إعداد.

أمثلة:
    python run.py                          # مستخدم واحد (الافتراضي)
    python run.py --server --host 0.0.0.0  # جهاز الخدمة للمؤسسة/المركز
    python run.py --client --server-url http://192.168.1.10:8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

from amdh_hr import crypto
from amdh_hr.config import APP_NAME, APP_VERSION, DEFAULT_PORT, Paths
from amdh_hr.logging_setup import setup_logging
from amdh_hr.server.app import ServiceApp
from amdh_hr.server.http_api import ApiServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="AMDH-HR",
        description=f"{APP_NAME} — التشغيل الافتراضي: مستخدم واحد بلا إعداد.")
    parser.add_argument("--server", action="store_true",
                        help="تشغيل الخدمة المحلية فقط (لمشاركة عدة مستخدمين)")
    parser.add_argument("--client", action="store_true",
                        help="تشغيل عميل يتصل بخدمة قائمة")
    parser.add_argument("--standalone", action="store_true",
                        help="خدمة + واجهة في عملية واحدة (الوضع الافتراضي)")
    parser.add_argument("--server-url", default="",
                        help="عنوان الخدمة (مثال: http://192.168.1.10:8765)")
    parser.add_argument("--data-dir", default="", help="مجلد البيانات")
    parser.add_argument("--host", default="", help="عنوان الاستماع للخدمة")
    parser.add_argument("--port", type=int, default=0,
                        help="منفذ الخدمة (0 = تلقائي في وضع المستخدم الواحد)")
    parser.add_argument("--theme", default="", choices=["", "auto", "dark", "light"])
    return parser


def _load_ui():
    try:
        from amdh_hr.ui.app import run as run_ui
        return run_ui
    except ImportError as exc:  # pragma: no cover - بيئة ناقصة
        print("تعذّر تحميل الواجهة:", exc)
        print("مفسّر بايثون الحالي:", sys.executable)
        print("ثبّت المتطلبات: python -m pip install -r requirements.txt")
        return None


def _qt_app():
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    from amdh_hr.config import asset_path
    app = QApplication.instance() or QApplication(sys.argv)
    icon = asset_path("icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def _ensure_key(paths: Paths, headless: bool) -> str | None:
    """يفعّل/يفكّ مفتاح التشفير قبل فتح قاعدة البيانات. None = إلغاء."""
    if not crypto.available():
        print("تنبيه: مكوّن SQLCipher غير متاح — ستعمل القاعدة بلا تشفير.")
        return ""
    db = paths.db_path
    try:
        meta = crypto.load_key_file(paths.data_dir)
    except crypto.CryptoError as exc:
        print(str(exc))
        if not headless:
            from amdh_hr.ui.dialogs_crypto import show_error
            show_error(None, str(exc))
        return None
    env = crypto.read_env_passphrase()
    if meta:
        if headless:
            if not env:
                print("قاعدة البيانات مشفرة. عيّن AMDH_HR_DB_PASSPHRASE لتشغيل الخدمة.")
                return None
            try:
                return crypto.key_for_passphrase(paths.data_dir, env)
            except crypto.CryptoError as exc:
                print(str(exc))
                return None
        from amdh_hr.ui.dialogs_crypto import ask_passphrase, show_error
        passphrase = env or ask_passphrase(None)
        if not passphrase:
            return None
        try:
            return crypto.key_for_passphrase(paths.data_dir, passphrase)
        except crypto.CryptoError as exc:
            show_error(None, str(exc))
            return None
    if db.exists() and crypto.is_encrypted(db):
        message = "قاعدة البيانات مشفرة لكن ملف المفتاح مفقود. استعد نسخة احتياطية."
        print(message)
        if not headless:
            from amdh_hr.ui.dialogs_crypto import show_error
            show_error(None, message)
        return None
    if db.exists():
        if headless:
            if not env:
                print("قاعدة البيانات غير مشفرة. شغّل الواجهة مرة لتفعيل التشفير، "
                      "أو عيّن AMDH_HR_DB_PASSPHRASE.")
                return None
            passphrase = env
        else:
            from amdh_hr.ui.dialogs_crypto import (
                ask_new_passphrase, confirm_enable, show_error,
            )
            if not confirm_enable(None, True):
                return None
            passphrase = ask_new_passphrase(None)
            if not passphrase:
                return None
        try:
            crypto.encrypt_database(db, passphrase, paths.backups_dir)
            return crypto.key_for_passphrase(paths.data_dir, passphrase)
        except Exception as exc:  # noqa: BLE001 - عرض سبب فشل التشفير للمستخدم
            print(str(exc))
            if not headless:
                from amdh_hr.ui.dialogs_crypto import show_error
                show_error(None, f"تعذّر تشفير قاعدة البيانات:\n{exc}")
            return None
    # قاعدة جديدة
    if headless:
        if not env:
            print("قاعدة جديدة مشفرة تحتاج AMDH_HR_DB_PASSPHRASE.")
            return None
        try:
            return crypto.write_key_file(paths.data_dir, env)
        except OSError as exc:
            print(f"تعذّر إنشاء مفتاح التشفير: {exc}")
            return None
    from amdh_hr.ui.dialogs_crypto import ask_new_passphrase, confirm_enable, show_error
    if not confirm_enable(None, False):
        return None
    passphrase = ask_new_passphrase(None)
    if not passphrase:
        return None
    try:
        return crypto.write_key_file(paths.data_dir, passphrase)
    except OSError as exc:
        show_error(None, f"تعذّر إنشاء مفتاح التشفير:\n{exc}")
        return None


def _running_service(url: str) -> bool:
    """هل توجد خدمة AMDH-HR عاملة على العنوان؟"""
    if not url:
        return False
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=1.2) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("app") == "AMDH-HR"
    except Exception:  # noqa: BLE001 - أي فشل يعني «لا خدمة»
        return False


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    paths = Paths(args.data_dir or None)
    setup_logging(paths.logs_dir)

    if args.server:
        host = args.host or "0.0.0.0"
        key = _ensure_key(paths, headless=True)
        if key is None:
            return 1
        app = ServiceApp(paths, key)
        server = ApiServer(app, host, args.port or DEFAULT_PORT)
        print(f"{APP_NAME} {APP_VERSION}")
        print(f"الخدمة: {server.url}")
        print(f"عنوان الشبكة: {server.lan_url}")
        print(f"البيانات: {paths.data_dir}")
        print("أوقف بـ Ctrl+C")
        try:
            server.serve_forever()
        finally:
            app.close()
        return 0

    run_ui = _load_ui()
    if run_ui is None:
        return 1

    if args.server_url or args.client:
        return run_ui(args.server_url, args.theme, local_mode=False)

    qt_app = _qt_app()  # noqa: F841 - يجب إبقاء مرجع QApplication حياً

    # إن كانت هناك خدمة عاملة (سابقة أو --server)، اتصل بها بدل تشغيل نسخة ثانية.
    marker = paths.data_dir / "server.url"
    candidates = []
    if marker.exists():
        try:
            candidates.append(marker.read_text(encoding="utf-8").strip())
        except OSError:
            pass
    candidates.append(f"http://127.0.0.1:{DEFAULT_PORT}")
    for candidate in candidates:
        if _running_service(candidate):
            print(f"وُجدت خدمة عاملة — الاتصال بها: {candidate}")
            return run_ui(candidate, args.theme, local_mode=False)

    # الافتراضي: مستخدم واحد — الخدمة داخل العملية نفسها.
    key = _ensure_key(paths, headless=False)
    if key is None:
        return 0
    app = ServiceApp(paths, key)
    server = ApiServer(app, "127.0.0.1", args.port or 0).start(background=True)
    try:
        marker.write_text(server.url, encoding="utf-8")
    except OSError:
        pass
    print(f"وضع المستخدم الواحد — {server.url}")
    print(f"البيانات: {paths.data_dir}")
    try:
        return run_ui(server.url, args.theme, local_mode=True)
    finally:
        server.stop()
        app.close()
        try:
            if marker.read_text(encoding="utf-8").strip() == server.url:
                marker.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
