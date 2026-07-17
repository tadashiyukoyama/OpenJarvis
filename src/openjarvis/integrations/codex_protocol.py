"""Typed, sanitized protocol values for the local Codex app-server client."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, TypeAlias

JsonRpcId: TypeAlias = int | str
JsonObject: TypeAlias = Mapping[str, object]


class CodexAppServerState(str, Enum):
    """Lifecycle states of a :class:`CodexAppServerClient`."""

    NEW = "NEW"
    STARTING = "STARTING"
    READY = "READY"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class CodexAppServerError(RuntimeError):
    """Base error for the Codex app-server transport."""


class CodexProcessStartError(CodexAppServerError):
    """The configured Codex process could not be started."""


class CodexProcessExitedError(CodexAppServerError):
    """The Codex process exited while the client was using it."""


class CodexProtocolError(CodexAppServerError):
    """The app-server emitted invalid JSON-RPC."""


class CodexRequestError(CodexAppServerError):
    """The app-server returned a JSON-RPC error."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CodexRequestTimeout(CodexAppServerError):
    """A request did not receive a response before its deadline."""


class CodexInvalidStateError(CodexAppServerError):
    """An operation was requested in an incompatible lifecycle state."""


DEFAULT_CODEX_COMMAND: tuple[str, ...] = (
    "codex",
    "app-server",
    "--listen",
    "stdio://",
)


@dataclass(frozen=True, slots=True)
class CodexAppServerConfig:
    """Configuration for one explicitly-started Codex app-server process."""

    command: tuple[str, ...] = DEFAULT_CODEX_COMMAND
    cwd: Path | None = None
    environment_overrides: Mapping[str, str] = field(default_factory=dict)
    request_timeout_seconds: float = 30.0
    startup_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 5.0
    stderr_max_lines: int = 100
    client_name: str = "openjarvis"
    client_title: str = "OpenJarvis"
    client_version: str = "0.1.0"

    def __post_init__(self) -> None:
        command = tuple(self.command)
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("command must be a non-empty tuple of non-empty strings")
        object.__setattr__(self, "command", command)
        object.__setattr__(
            self,
            "environment_overrides",
            MappingProxyType(dict(self.environment_overrides)),
        )
        for name in (
            "request_timeout_seconds",
            "startup_timeout_seconds",
            "shutdown_timeout_seconds",
        ):
            value = float(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if self.stderr_max_lines <= 0:
            raise ValueError("stderr_max_lines must be positive")
        if not self.client_name or not self.client_title or not self.client_version:
            raise ValueError("client information must be non-empty")


class CodexHomeStatus(str, Enum):
    """Sanitized classification of the server's Codex home path."""

    EXPECTED = "EXPECTED"
    UNEXPECTED = "UNEXPECTED"
    ABSENT = "ABSENT"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class JsonRpcError:
    """A JSON-RPC error without retaining an untrusted raw envelope."""

    code: int
    message: str
    data: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class JsonRpcResponse:
    """A JSON-RPC response correlated by ID."""

    request_id: JsonRpcId
    result: object | None = None
    error: JsonRpcError | None = None


@dataclass(frozen=True, slots=True)
class JsonRpcNotification:
    """A server-to-client notification with no request ID."""

    method: str
    params: object | None = None


@dataclass(frozen=True, slots=True)
class JsonRpcServerRequest:
    """A server-to-client request that requires a response."""

    request_id: JsonRpcId
    method: str
    params: object | None = None


@dataclass(frozen=True, slots=True)
class CodexHandshakeInfo:
    """Sanitized initialize response metadata."""

    codex_home_status: CodexHomeStatus
    platform_family: str | None
    platform_os: str | None
    user_agent_present: bool
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodexAccountInfo:
    """Sanitized account/read result; no personal or credential fields."""

    authenticated: bool | None
    auth_mode: str | None
    plan_type_present: bool
    rate_limits_present: bool


@dataclass(frozen=True, slots=True)
class CodexModelInfo:
    """Public model catalog metadata, excluding credentials and runtime state."""

    model_id: str
    metadata: JsonObject


def parse_jsonrpc_envelope(
    payload: object,
) -> JsonRpcResponse | JsonRpcNotification | JsonRpcServerRequest:
    """Classify and validate one decoded JSON-RPC envelope."""

    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise CodexProtocolError("invalid JSON-RPC envelope")

    has_id = "id" in payload
    has_method = "method" in payload
    if has_method:
        method = payload["method"]
        if not isinstance(method, str) or not method:
            raise CodexProtocolError("invalid JSON-RPC method")
        if "result" in payload or "error" in payload:
            raise CodexProtocolError("request cannot contain result or error")
        params = payload.get("params")
        if has_id:
            request_id = payload["id"]
            if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
                raise CodexProtocolError("invalid JSON-RPC request ID")
            return JsonRpcServerRequest(request_id, method, params)
        return JsonRpcNotification(method, params)

    if not has_id or ("result" not in payload and "error" not in payload):
        raise CodexProtocolError("invalid JSON-RPC response")
    request_id = payload["id"]
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        raise CodexProtocolError("invalid JSON-RPC response ID")
    has_result = "result" in payload
    has_error = "error" in payload
    if has_result == has_error:
        raise CodexProtocolError("response must contain exactly one of result or error")
    if has_error:
        raw_error = payload["error"]
        if not isinstance(raw_error, dict):
            raise CodexProtocolError("invalid JSON-RPC error")
        code = raw_error.get("code")
        message = raw_error.get("message")
        if not isinstance(code, int) or isinstance(code, bool) or not isinstance(message, str):
            raise CodexProtocolError("invalid JSON-RPC error fields")
        data = raw_error.get("data")
        if data is not None and not isinstance(data, dict):
            data = None
        return JsonRpcResponse(request_id, error=JsonRpcError(code, message, data))
    return JsonRpcResponse(request_id, result=payload.get("result"))


def encode_jsonrpc(message: JsonObject) -> str:
    """Encode one message as compact UTF-8-safe JSONL text."""

    return json.dumps(dict(message), ensure_ascii=False, separators=(",", ":")) + "\n"


__all__ = [
    "CodexAccountInfo",
    "CodexAppServerConfig",
    "CodexAppServerError",
    "CodexAppServerState",
    "CodexHandshakeInfo",
    "CodexHomeStatus",
    "CodexInvalidStateError",
    "CodexModelInfo",
    "CodexProcessExitedError",
    "CodexProcessStartError",
    "CodexProtocolError",
    "CodexRequestError",
    "CodexRequestTimeout",
    "DEFAULT_CODEX_COMMAND",
    "JsonRpcError",
    "JsonRpcNotification",
    "JsonRpcResponse",
    "JsonRpcServerRequest",
    "parse_jsonrpc_envelope",
]
