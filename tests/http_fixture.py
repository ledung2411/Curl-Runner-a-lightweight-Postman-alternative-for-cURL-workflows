"""Local HTTP server used by the tests (no network access needed)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _ApiHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/health":
            self._send_json(200, {"ok": True, "items": [{"id": 1}, {"id": 2}]})
        elif self.path == "/me":
            if self.headers.get("Authorization") == "Bearer tok-123":
                self._send_json(200, {"user": "dung"})
            else:
                self._send_json(401, {"error": "unauthorized"})
        elif self.path.startswith("/users/"):
            self._send_json(200, {"id": self.path.rsplit("/", 1)[-1]})
        else:
            self._send_json(500, {"error": "boom"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        body = self._read_body()
        if self.path == "/login":
            self._send_json(200, {"data": {"token": "tok-123"}}, {"X-Request-Id": "req-1"})
        else:
            self._send_json(200, {
                "content_type": self.headers.get("Content-Type", ""),
                "body": body.decode("utf-8", errors="replace"),
            })

    def log_message(self, *_args) -> None:
        pass


class LocalApi:
    """Context manager: `with LocalApi() as base_url: ...`."""

    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
