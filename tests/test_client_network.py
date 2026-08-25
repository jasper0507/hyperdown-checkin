"""Network seam tests for HyperdownClient.request().

Exercises real urllib against a local HTTP server that can drop the
connection (the GitHub Actions failure mode) or return JSON errors.
"""

from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from client import APIError, HyperdownClient


class _ControlHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.server.hits += 1  # type: ignore[attr-defined]
        if self.server.hits <= self.server.drop_first:  # type: ignore[attr-defined]
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        payload = self.server.payload  # type: ignore[attr-defined]
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ControlServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, drop_first: int = 0, payload: dict[str, Any] | None = None) -> None:
        super().__init__(("127.0.0.1", 0), _ControlHandler)
        self.drop_first = drop_first
        self.hits = 0
        self.payload = payload or {"ok": True, "data": {"nickname": "t"}}


def _serve(server: _ControlServer) -> None:
    server.serve_forever(poll_interval=0.05)


def _start(drop_first: int = 0, payload: dict[str, Any] | None = None) -> _ControlServer:
    server = _ControlServer(drop_first=drop_first, payload=payload)
    thread = threading.Thread(target=_serve, args=(server,), daemon=True)
    thread.start()
    server.thread = thread  # type: ignore[attr-defined]
    return server


def _stop(server: _ControlServer) -> None:
    server.shutdown()
    server.server_close()


def _client(server: _ControlServer, **kwargs: Any) -> HyperdownClient:
    host, port = server.server_address[:2]
    defaults = {
        "base_url": f"http://{host}:{port}/api/v1",
        "timeout": 2.0,
        "retry_backoff_s": 0.0,
    }
    defaults.update(kwargs)
    return HyperdownClient(**defaults)


class RequestNetworkTests(unittest.TestCase):
    def test_dropped_connection_is_network_error(self) -> None:
        server = _start(drop_first=99)
        self.addCleanup(lambda: _stop(server))
        client = _client(server, max_attempts=1)
        with self.assertRaises(APIError) as ctx:
            client.request("POST", "/auth/login", body={}, auth=False, secure=False)
        self.assertEqual(ctx.exception.code, "network_error")

    def test_recovers_after_transient_disconnects(self) -> None:
        server = _start(drop_first=2)
        self.addCleanup(lambda: _stop(server))
        client = _client(server, max_attempts=3)
        data = client.request("POST", "/auth/login", body={}, auth=False, secure=False)
        self.assertEqual(data, {"nickname": "t"})
        self.assertEqual(server.hits, 3)

    def test_business_error_is_not_retried(self) -> None:
        server = _start(
            drop_first=0,
            payload={"ok": False, "error": {"code": "invalid_password", "message": "bad"}},
        )
        self.addCleanup(lambda: _stop(server))
        client = _client(server, max_attempts=3)
        with self.assertRaises(APIError) as ctx:
            client.request("POST", "/auth/login", body={}, auth=False, secure=False)
        self.assertEqual(ctx.exception.code, "invalid_password")
        self.assertEqual(server.hits, 1)

    def test_exhausted_retries_stay_network_error(self) -> None:
        server = _start(drop_first=99)
        self.addCleanup(lambda: _stop(server))
        client = _client(server, max_attempts=3)
        with self.assertRaises(APIError) as ctx:
            client.request("POST", "/auth/login", body={}, auth=False, secure=False)
        self.assertEqual(ctx.exception.code, "network_error")
        self.assertEqual(server.hits, 3)

    def test_secure_checkin_retries_and_succeeds(self) -> None:
        server = _start(drop_first=1)
        self.addCleanup(lambda: _stop(server))
        client = _client(server, max_attempts=3)
        client.tokens.access_token = "test-token"
        data = client.request(
            "POST", "/me/checkins", body={}, auth=True, secure=True
        )
        self.assertEqual(data, {"nickname": "t"})
        self.assertEqual(server.hits, 2)


if __name__ == "__main__":
    unittest.main()
