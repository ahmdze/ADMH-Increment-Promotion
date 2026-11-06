"""عميل API: يتصل بالخدمة المحلية عبر HTTP/JSON."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class ApiError(Exception):
    def __init__(self, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def __str__(self) -> str:
        return self.message


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = timeout
        self.token = ""

    # ------------------------------------------------------------------
    def call(self, method: str, **params):
        if not self.base_url:
            raise ApiError("connection", "لم يُحدَّد عنوان الخدمة.")
        payload = json.dumps({"method": method, "params": params},
                             ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/rpc", data=payload, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            data = _safe_json(raw)
            error = data.get("error") or {}
            raise ApiError(str(error.get("code") or "http_error"),
                           str(error.get("message") or f"خطأ اتصال ({exc.code})")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError("connection",
                           "تعذّر الاتصال بالخدمة. تأكد من تشغيل الخدمة على الجهاز "
                           f"وعنوان الشبكة.\n{exc}") from None
        data = _safe_json(raw)
        if not data.get("ok"):
            error = data.get("error") or {}
            raise ApiError(str(error.get("code") or "error"),
                           str(error.get("message") or "خطأ غير معروف"))
        return data.get("result")

    # ------------------------------------------------------------------
    def health(self) -> dict:
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - عرض رسالة مبسّطة
            raise ApiError("connection", f"الخدمة غير متاحة: {exc}") from None

    def bootstrap_status(self) -> dict:
        return self.call("bootstrap.status")

    def create_admin(self, username: str, password: str, display_name: str = "") -> dict:
        return self.call("bootstrap.create_admin", username=username, password=password,
                         display_name=display_name)

    def login(self, username: str, password: str) -> dict:
        result = self.call("auth.login", username=username, password=password)
        self.token = result.get("token", "")
        return result

    def logout(self) -> None:
        try:
            if self.token:
                self.call("auth.logout")
        finally:
            self.token = ""

    def me(self) -> dict:
        return self.call("auth.me")["user"]


def _safe_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
