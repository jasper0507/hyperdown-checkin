"""Minimal Hyperdown REST client."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from secure_api import is_sensitive_path, normalize_api_path, seal_json

DEFAULT_UA = "Mozilla/5.0 Hyperdown/3.0"
DEFAULT_BASE = "https://hyperdown.net/api/v1"


class APIError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None, raw: Any = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.raw = raw


@dataclass
class TokenPair:
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenPair":
        data = data or {}
        return cls(
            access_token=str(data.get("access_token") or data.get("access") or ""),
            refresh_token=str(data.get("refresh_token") or data.get("refresh") or ""),
            expires_in=int(data.get("expires_in") or 0),
        )


@dataclass
class HyperdownClient:
    base_url: str = DEFAULT_BASE
    user_agent: str = DEFAULT_UA
    proxy: str = ""
    tokens: TokenPair = field(default_factory=TokenPair)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.base_url.endswith("/api/v1"):
            pass
        elif self.base_url.endswith("/api"):
            self.base_url = self.base_url + "/v1"
        elif "://" in self.base_url and "/api/" not in self.base_url:
            self.base_url = self.base_url.rstrip("/") + "/api/v1"

    def _opener(self) -> urllib.request.OpenerDirector:
        handlers: list[urllib.request.BaseHandler] = []
        if self.proxy:
            handlers.append(
                urllib.request.ProxyHandler(
                    {"http": self.proxy, "https": self.proxy}
                )
            )
        # Default SSL context
        ctx = ssl.create_default_context()
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
        return urllib.request.build_opener(*handlers)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | bytes | None = None,
        auth: bool = True,
        secure: bool | None = None,
    ) -> Any:
        method = method.upper()
        path = path if path.startswith("/") else "/" + path
        url = self.base_url + path

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if auth and self.tokens.access_token:
            headers["Authorization"] = f"Bearer {self.tokens.access_token}"

        raw_body: bytes | None = None
        # Client seals against full paths like /api/v1/me/checkins.
        full_path = path if path.startswith("/api/") else "/api/v1" + (
            path if path.startswith("/") else "/" + path
        )
        use_secure = (
            is_sensitive_path(method, normalize_api_path(full_path))
            if secure is None
            else secure
        )

        if use_secure:
            envelope, extra = seal_json(method, full_path, body)
            headers.update(extra)
            raw_body = json.dumps(envelope, separators=(",", ":")).encode()
        elif body is not None:
            if isinstance(body, (bytes, bytearray)):
                raw_body = bytes(body)
            else:
                raw_body = json.dumps(body, separators=(",", ":")).encode()

        req = urllib.request.Request(url, data=raw_body, method=method, headers=headers)
        opener = self._opener()
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                text = resp.read().decode()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            status = e.code
        except urllib.error.URLError as e:
            raise APIError("network_error", str(e.reason or e), None) from e

        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError as e:
            raise APIError("invalid_json", text[:200], status) from e

        if isinstance(payload, dict) and payload.get("ok") is False:
            err = payload.get("error") or {}
            raise APIError(
                str(err.get("code") or "error"),
                str(err.get("message") or text),
                status,
                payload,
            )
        if status >= 400:
            raise APIError("http_error", text[:200], status, payload)

        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def login(self, email: str, password: str) -> dict[str, Any]:
        data = self.request(
            "POST",
            "/auth/login",
            body={"email": email, "password": password},
            auth=False,
            secure=False,
        )
        self._absorb_tokens(data)
        return data if isinstance(data, dict) else {"raw": data}

    def refresh(self) -> dict[str, Any]:
        if not self.tokens.refresh_token:
            raise APIError("no_refresh_token", "缺少 refresh_token，请重新登录")
        # Client POSTs refresh without Bearer; token in body is common.
        # Try body first; fall back to empty body + cookie-like patterns if needed.
        body: dict[str, Any] = {"refresh_token": self.tokens.refresh_token}
        try:
            data = self.request(
                "POST",
                "/auth/refresh",
                body=body,
                auth=False,
                secure=False,
            )
        except APIError:
            # Some deployments accept only the refresh token as Bearer
            old = self.tokens.access_token
            self.tokens.access_token = self.tokens.refresh_token
            try:
                data = self.request(
                    "POST",
                    "/auth/refresh",
                    body={},
                    auth=True,
                    secure=False,
                )
            finally:
                self.tokens.access_token = old
        self._absorb_tokens(data)
        return data if isinstance(data, dict) else {"raw": data}

    def me(self) -> dict[str, Any]:
        data = self.request("GET", "/me/", auth=True, secure=False)
        if isinstance(data, dict) and "user" in data and isinstance(data["user"], dict):
            return data["user"]
        return data if isinstance(data, dict) else {}

    def check_in(self) -> dict[str, Any]:
        # Client path string is /api/v1/me/checkins; our base already includes /api/v1.
        data = self.request("POST", "/me/checkins", body={}, auth=True, secure=True)
        return data if isinstance(data, dict) else {"raw": data}

    def _absorb_tokens(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        # Nested token pair
        for key in ("tokens", "token", "auth"):
            nested = data.get(key)
            if isinstance(nested, dict):
                if nested.get("access_token") or nested.get("refresh_token"):
                    self.tokens = TokenPair.from_dict(nested)
                    return
        if data.get("access_token") or data.get("refresh_token"):
            pair = TokenPair.from_dict(data)
            if not pair.refresh_token:
                pair.refresh_token = self.tokens.refresh_token
            if not pair.access_token:
                pair.access_token = self.tokens.access_token
            self.tokens = pair
