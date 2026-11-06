"""الخدمة المحلية: HTTP + JSON فوق الشبكة الداخلية."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..logging_setup import get_logger
from ..util import now_iso
from ..config import APP_VERSION

LOG = get_logger("http")
MAX_BODY = 4 * 1024 * 1024


def lan_ip() -> str:
    """أفضل تخمين لعنوان الجهاز على الشبكة الداخلية."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))
        address = probe.getsockname()[0]
        probe.close()
        return address
    except OSError:
        return "127.0.0.1"


class ApiServer:
    def __init__(self, app, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.app = app
        self.host = host
        self.port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return f"http://{host}:{self.port}"

    @property
    def lan_url(self) -> str:
        return f"http://{lan_ip()}:{self.port}"

    def start(self, background: bool = True) -> "ApiServer":
        handler = _make_handler(self.app)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        self._httpd.allow_reuse_address = True
        self.port = self._httpd.server_address[1]
        if background:
            self._thread = threading.Thread(target=self._httpd.serve_forever,
                                            name="amdh-api", daemon=True)
            self._thread.start()
            LOG.info("الخدمة تعمل على %s", self.url)
        return self

    def serve_forever(self) -> None:
        if self._httpd is None:
            self.start(background=False)
        assert self._httpd is not None
        LOG.info("الخدمة تعمل على %s (شبكة: %s)", self.url, self.lan_url)
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:  # pragma: no cover
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None


def _make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AMDH-HR/0.1"
        protocol_version = "HTTP/1.1"

        # --------------------------------------------------------------
        def log_message(self, fmt, *args):  # noqa: A003 - توقيع المكتبة
            LOG.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _token(self) -> str:
            header = self.headers.get("Authorization", "")
            if header.lower().startswith("bearer "):
                return header[7:].strip()
            return ""

        def _ip(self) -> str:
            return self.client_address[0] if self.client_address else ""

        # --------------------------------------------------------------
        def do_GET(self):  # noqa: N802 - توقيع المكتبة
            if self.path.split("?")[0] in {"/health", "/"}:
                self._send(200, {"ok": True, "app": "AMDH-HR", "app_version": APP_VERSION,
                                 "time": now_iso()})
                return
            self._send(404, {"ok": False, "error": {"code": "not_found",
                                                    "message": "مسار غير معروف"}})

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != "/rpc":
                self._send(404, {"ok": False, "error": {"code": "not_found",
                                                        "message": "مسار غير معروف"}})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"ok": False, "error": {"code": "bad_request",
                                                        "message": "حجم الطلب غير صالح"}})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                method = str(payload.get("method") or "")
                params = payload.get("params") or {}
                if not isinstance(params, dict):
                    raise ValueError("params")
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"ok": False, "error": {"code": "bad_request",
                                                        "message": "طلب غير صالح"}})
                return
            result = app.dispatch(method, params, self._token(), self._ip())
            status = 200
            if not result.get("ok"):
                status = int(result.get("error", {}).get("status", 200) or 200)
            self._send(status, result)

    return Handler


def serve(app, paths: Path, host: str, port: int) -> None:
    server = ApiServer(app, host, port)
    server.serve_forever()
