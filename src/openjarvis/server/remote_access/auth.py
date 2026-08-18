"""Credential parsing and short-lived browser session management."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal

from fastapi import Request
from starlette.responses import Response

from openjarvis.server.remote_access.config import GatewayConfig

SESSION_COOKIE = "oj_tunnel_session"
_ALLOWED_KEYS = {"OJ_GATEWAY_USER", "OJ_GATEWAY_PASSWORD"}


@dataclass(frozen=True, slots=True)
class GatewayCredentials:
    username: str
    password: str

    @classmethod
    def from_file(cls, path: Path) -> "GatewayCredentials":
        if not path.is_file():
            raise RuntimeError(f"Gateway credential file not found: {path}")
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or name not in _ALLOWED_KEYS or name in values:
                raise RuntimeError("Invalid gateway credential file")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values[name] = value
        if set(values) != _ALLOWED_KEYS or not all(values.values()):
            raise RuntimeError("Gateway username and password must be configured")
        return cls(
            username=values["OJ_GATEWAY_USER"],
            password=values["OJ_GATEWAY_PASSWORD"],
        )


class GatewayAuth:
    """Own in-memory sessions; no browser token is persisted to disk."""

    def __init__(self, credentials: GatewayCredentials, config: GatewayConfig) -> None:
        self._credentials = credentials
        self._config = config
        self._sessions: dict[str, float] = {}
        self._continuations: dict[str, tuple[float, str]] = {}
        self._lock = Lock()

    def credentials_match(self, username: str, password: str) -> bool:
        return secrets.compare_digest(
            username, self._credentials.username
        ) and secrets.compare_digest(password, self._credentials.password)

    def authorization_kind(self, request: Request) -> Literal["cookie", "basic"] | None:
        session_token = request.cookies.get(SESSION_COOKIE, "")
        if session_token and self._valid_session(session_token):
            return "cookie"

        authorization = request.headers.get("authorization", "")
        scheme, _, encoded = authorization.partition(" ")
        if scheme.lower() != "basic" or not encoded:
            return None
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        username, separator, password = decoded.partition(":")
        if separator and self.credentials_match(username, password):
            return "basic"
        return None

    def set_session_cookie(self, response: Response) -> None:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._sessions[token] = monotonic() + self._config.session_ttl_seconds
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=self._config.session_ttl_seconds,
            path="/",
            secure=self._config.secure_cookie,
            httponly=True,
            samesite="lax",
        )

    def issue_continuation(self, request: Request) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._continuations[token] = (
                monotonic() + self._config.continuation_ttl_seconds,
                self.client_identity(request),
            )
        return token

    def consume_continuation(self, request: Request, token: str) -> bool:
        with self._lock:
            self._prune_locked()
            record = self._continuations.pop(token, None)
        if record is None:
            return False
        expires_at, identity = record
        return expires_at > monotonic() and secrets.compare_digest(
            identity, self.client_identity(request)
        )

    @staticmethod
    def client_identity(request: Request) -> str:
        client_ip = request.headers.get("cf-connecting-ip")
        if not client_ip and request.client:
            client_ip = request.client.host
        user_agent = request.headers.get("user-agent", "unknown")
        return f"{client_ip or 'unknown'}\0{user_agent}"

    def _valid_session(self, token: str) -> bool:
        with self._lock:
            self._prune_locked()
            expires_at = self._sessions.get(token)
        return expires_at is not None and expires_at > monotonic()

    def _prune_locked(self) -> None:
        now = monotonic()
        self._sessions = {
            token: expires_at
            for token, expires_at in self._sessions.items()
            if expires_at > now
        }
        self._continuations = {
            token: record
            for token, record in self._continuations.items()
            if record[0] > now
        }


__all__ = ["GatewayAuth", "GatewayCredentials", "SESSION_COOKIE"]
