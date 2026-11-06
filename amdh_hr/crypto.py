"""تشفير قاعدة البيانات عبر SQLCipher مع مفتاح مشتق من كلمة مرور."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
from pathlib import Path

from .util import stamp

KEY_FILE = "db.key.json"
ITERATIONS = 260_000
PLAIN_HEADER = b"SQLite format 3\x00"
PACKAGE_MAGIC = b"AMDHENC1"


class CryptoError(Exception):
    """خطأ في التشفير أو المفتاح."""


def is_encrypted_package(path: Path | str) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(PACKAGE_MAGIC)) == PACKAGE_MAGIC
    except OSError:
        return False


def _package_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=ITERATIONS).derive(password.encode("utf-8"))


def encrypt_package(source: Path | str, target: Path | str, password: str) -> Path:
    """يشفّر حزمة .amdhpkg (ZIP) بكلمة مرور AES-256-GCM."""
    if len(password) < 8:
        raise CryptoError("كلمة مرور الحزمة يجب ألا تقل عن 8 أحرف.")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    source, target = Path(source), Path(target)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _package_key(password, salt)
    payload = source.read_bytes()
    encrypted = AESGCM(key).encrypt(nonce, payload, PACKAGE_MAGIC + salt)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(PACKAGE_MAGIC + salt + nonce + encrypted)
    temporary.replace(target)
    return target


def decrypt_package(source: Path | str, target: Path | str, password: str) -> Path:
    """يفكّ تشفير الحزمة، ويدعم الحزم النصية القديمة عند ترك كلمة المرور فارغة."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    if not raw.startswith(PACKAGE_MAGIC):
        target.write_bytes(raw)
        return target
    if not password:
        raise CryptoError("هذه حزمة مشفرة؛ أدخل كلمة مرور الحزمة.")
    body = raw[len(PACKAGE_MAGIC):]
    if len(body) < 28:
        raise CryptoError("ملف الحزمة المشفرة تالف.")
    salt, nonce, ciphertext = body[:16], body[16:28], body[28:]
    key = _package_key(password, salt)
    try:
        payload = AESGCM(key).decrypt(nonce, ciphertext, PACKAGE_MAGIC + salt)
    except InvalidTag as exc:
        raise CryptoError("كلمة مرور الحزمة غير صحيحة أو الملف تالف.") from exc
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(target)
    return target


def available() -> bool:
    try:
        import sqlcipher3  # noqa: F401
        return True
    except ImportError:
        return False


def db_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "amdh_hr.db"


def key_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / KEY_FILE


def is_encrypted(path: Path | str) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(16) != PLAIN_HEADER
    except OSError:
        return False


def derive_key(passphrase: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt,
                               ITERATIONS, 32).hex()


def _verifier(key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(key_hex) + b"amdh-verify").hexdigest()


def _write_key(data_dir: Path | str, key: str, salt: bytes) -> None:
    payload = {
        "version": 1, "cipher": "sqlcipher", "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "verifier": _verifier(key),
    }
    path = key_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_key_file(data_dir: Path | str, passphrase: str) -> str:
    salt = secrets.token_bytes(16)
    key = derive_key(passphrase, salt)
    _write_key(data_dir, key, salt)
    return key


def load_key_file(data_dir: Path | str) -> dict | None:
    path = key_path(data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CryptoError("ملف مفتاح التشفير تالف.") from exc


def key_for_passphrase(data_dir: Path | str, passphrase: str) -> str:
    meta = load_key_file(data_dir)
    if not meta:
        raise CryptoError("لا يوجد مفتاح تشفير مثبت.")
    try:
        salt = base64.b64decode(meta["salt"])
        key = derive_key(passphrase, salt)
        if not hmac.compare_digest(_verifier(key), str(meta.get("verifier") or "")):
            raise CryptoError("كلمة مرور التشفير غير صحيحة.")
        return key
    except (KeyError, ValueError) as exc:
        raise CryptoError("ملف مفتاح التشفير تالف.") from exc


def key_literal(key_hex: str) -> str:
    return f"x'{key_hex}'"


def connect(path: Path | str, key: str = ""):
    if key:
        from sqlcipher3 import dbapi2 as driver
    else:
        driver = sqlite3
    connection = driver.connect(str(path), timeout=30, isolation_level=None,
                                check_same_thread=False)
    connection.row_factory = driver.Row
    if key:
        connection.execute(f'PRAGMA key = "{key_literal(key)}"')
        connection.execute("PRAGMA cipher_memory_security = ON")
    return connection


def verify_key(path: Path | str, key: str) -> None:
    connection = connect(path, key)
    try:
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        connection.close()


def _checkpoint(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink()
        except OSError:
            pass


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def encrypt_database(path: Path | str, passphrase: str,
                     backup_dir: Path | str | None = None) -> Path:
    """يشفّر قاعدة نصية قائمة، ويعيد مسار نسخة ما قبل التشفير."""
    path = Path(path)
    if not path.exists():
        raise CryptoError("قاعدة البيانات غير موجودة.")
    if is_encrypted(path):
        raise CryptoError("قاعدة البيانات مشفرة مسبقاً.")
    if not available():
        raise CryptoError("مكوّن SQLCipher غير مثبت.")
    salt = secrets.token_bytes(16)
    key = derive_key(passphrase, salt)
    _checkpoint(path)
    temp = path.with_name(path.name + ".enc.tmp")
    if temp.exists():
        temp.unlink()
    from sqlcipher3 import dbapi2 as sqlcipher
    source = sqlcipher.connect(str(path))
    try:
        source.execute(
            f"ATTACH DATABASE '{_quote_path(temp)}' AS enc KEY \"{key_literal(key)}\"")
        source.execute("SELECT sqlcipher_export('enc')")
        source.execute("DETACH DATABASE enc")
    finally:
        source.close()
    verify_key(temp, key)
    folder = Path(backup_dir) if backup_dir else path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / f"pre_encryption_{stamp()}.db"
    shutil.copy2(temp, backup)
    path.unlink()
    temp.replace(path)
    _write_key(path.parent, key, salt)
    return backup


def export_plaintext(path: Path | str, key: str, dest: Path | str) -> Path:
    """ينشئ نسخة نصية (لحزم USB) من قاعدة مشفرة."""
    path, dest = Path(path), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    connection = connect(path, key)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute(f"ATTACH DATABASE '{_quote_path(dest)}' AS plain KEY ''")
        connection.execute("SELECT sqlcipher_export('plain')")
        connection.execute("DETACH DATABASE plain")
    finally:
        connection.close()
    return dest


def change_passphrase(path: Path | str, old_key: str, new_passphrase: str) -> str:
    salt = secrets.token_bytes(16)
    new_key = derive_key(new_passphrase, salt)
    connection = connect(path, old_key)
    try:
        connection.execute(f'PRAGMA rekey = "{key_literal(new_key)}"')
    finally:
        connection.close()
    _write_key(Path(path).parent, new_key, salt)
    return new_key


def read_env_passphrase() -> str:
    return os.environ.get("AMDH_HR_DB_PASSPHRASE", "")
