"""أخطاء التطبيق: تُرفع من الخدمات وتُترجم إلى استجابة API موحّدة."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 200, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message, "status": self.status}
        payload.update(self.extra)
        return payload


def validation(message: str, **extra) -> AppError:
    return AppError("validation", message, **extra)


def forbidden(message: str = "لا تملك صلاحية تنفيذ هذه العملية.") -> AppError:
    return AppError("forbidden", message, status=403)


def unauthenticated(message: str = "انتهت الجلسة، سجّل الدخول من جديد.") -> AppError:
    return AppError("unauthenticated", message, status=401)


def not_found(message: str = "العنصر غير موجود.") -> AppError:
    return AppError("not_found", message, status=404)


def conflict(message: str) -> AppError:
    return AppError("conflict", message, status=409)
