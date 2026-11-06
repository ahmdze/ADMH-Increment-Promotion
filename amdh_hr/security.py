"""تجزئة كلمات المرور، توليدها، والجلسات."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

ITERATIONS = 260_000
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
COMMON = {"admin", "admin123", "12345678", "password", "123456789", "qwertyui",
          "احمد1996", "ahmed1996"}


def normalize(password: str) -> str:
    """يوحّد كلمة المرور: يزيل المسافات الطرفية الناتجة عن اللصق فقط."""
    return str(password or "").strip()


def hash_password(password: str, salt: str | None = None,
                  iterations: int = ITERATIONS) -> tuple[str, str, int]:
    password = normalize(password)
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), iterations)
    return digest.hex(), salt, iterations


def verify_password(password: str, stored: str, salt: str, iterations: int = ITERATIONS) -> bool:
    if not stored or not salt:
        return False
    try:
        candidate, _salt, _it = hash_password(password, salt, iterations)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, stored)


def password_strength(password: str) -> tuple[bool, str]:
    password = normalize(password)
    if len(password) < 8:
        return False, "كلمة المرور قصيرة (8 أحرف على الأقل)."
    if password.lower() in COMMON:
        return False, "كلمة المرور شائعة جداً، اختر غيرها."
    if password.isdigit():
        return False, "لا تستخدم أرقاماً فقط."
    if len(set(password)) < 4:
        return False, "كلمة المرور ضعيفة (تنويع قليل)."
    return True, ""


def generate_password(length: int = 10) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def unique_password(existing: set[str], length: int = 10) -> str:
    for _ in range(50):
        candidate = generate_password(length)
        if candidate not in existing:
            return candidate
    return generate_password(length + 2)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
