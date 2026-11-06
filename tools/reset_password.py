"""إعادة تعيين كلمة مرور مستخدم، أو فحصها — لحالات النسيان أو القفل.

أمثلة:
    python tools/reset_password.py --list
    python tools/reset_password.py --username admin
    python tools/reset_password.py --username admin --password "NewPass#2026"
    python tools/reset_password.py --username unit-1 --check --password "..."
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from amdh_hr import crypto, security as sec  # noqa: E402
from amdh_hr.config import APP_NAME, Paths  # noqa: E402
from amdh_hr.db import Database  # noqa: E402
from amdh_hr.services import audit  # noqa: E402
from amdh_hr.util import now_iso  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — إدارة كلمات المرور محلياً")
    parser.add_argument("--data-dir", default="", help="مجلد البيانات (افتراضياً مجلد المشروع)")
    parser.add_argument("--list", action="store_true", help="سرد المستخدمين")
    parser.add_argument("--username", default="", help="اسم المستخدم")
    parser.add_argument("--password", default="", help="كلمة المرور الجديدة أو المفحوصة")
    parser.add_argument("--check", action="store_true", help="فحص كلمة المرور بدل تعيينها")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    paths = Paths(args.data_dir or None)
    print(f"البيانات: {paths.data_dir}")
    if not paths.db_path.exists():
        print("قاعدة البيانات غير موجودة. شغّل البرنامج مرة واحدة أولاً.")
        return 1

    db_key = ""
    if crypto.key_path(paths.data_dir).exists():
        passphrase = crypto.read_env_passphrase() or getpass.getpass(
            "كلمة مرور تشفير قاعدة البيانات: ")
        try:
            db_key = crypto.key_for_passphrase(paths.data_dir, passphrase)
        except crypto.CryptoError as exc:
            print(str(exc))
            return 1

    db = Database(paths.db_path, db_key)
    try:
        rows = db.query(
            "SELECT username, display_name, role, active, failed_attempts, locked_until, "
            "last_login FROM users ORDER BY role, username")
        if args.list or not args.username:
            if not rows:
                print("لا يوجد مستخدمون بعد (النظام غير مُهيّأ).")
                return 0
            print(f"{'المستخدم':<16} {'الدور':<14} {'الحالة':<8} {'آخر دخول'}")
            for row in rows:
                state = "نشط" if row["active"] else "معطّل"
                if row["locked_until"]:
                    state = "مقفل"
                print(f"{row['username']:<16} {row['role']:<14} {state:<8} "
                      f"{row['last_login'] or '—'}")
            if not args.username:
                return 0

        row = db.one("SELECT * FROM users WHERE lower(username)=lower(?)", (args.username,))
        if row is None:
            print(f"لا يوجد مستخدم باسم: {args.username}")
            return 2

        if args.check:
            ok = sec.verify_password(args.password, row["password_hash"], row["salt"],
                                     row["iterations"])
            print("كلمة المرور صحيحة." if ok else "كلمة المرور غير صحيحة.")
            return 0 if ok else 3

        password = args.password
        if not password:
            password = getpass.getpass("كلمة المرور الجديدة: ")
            confirm = getpass.getpass("تأكيد كلمة المرور: ")
            if password != confirm:
                print("كلمتا المرور غير متطابقتين.")
                return 4
        ok, message = sec.password_strength(password)
        if not ok:
            print(message)
            return 4

        digest, salt, iterations = sec.hash_password(password)
        with db.write() as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, salt=?, iterations=?, must_change=0, "
                "failed_attempts=0, locked_until=NULL, updated_at=? WHERE user_id=?",
                (digest, salt, iterations, now_iso(), row["user_id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
            audit.log(db, {"user_id": row["user_id"], "username": "أداة الاستعادة"},
                      "إعادة تعيين كلمة مرور", "users", row["user_id"],
                      f"المستخدم: {row['username']}", conn=conn)
        print(f"تم تعيين كلمة مرور جديدة للمستخدم: {row['username']}")
        print("أعد تشغيل البرنامج إن كان مفتوحاً، ثم سجّل الدخول بالكلمة الجديدة.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
