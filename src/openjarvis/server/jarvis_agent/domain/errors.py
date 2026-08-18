"""Stable public errors for the Jarvis agent API."""

from __future__ import annotations

from typing import Any

PUBLIC_ERROR_CODES = frozenset(
    {
        "MANIFEST_STALE",
        "TOOL_UNAVAILABLE",
        "SOURCE_DISCONNECTED",
        "CAPABILITY_NOT_AVAILABLE",
        "ACTION_PENDING",
        "APPROVAL_REQUIRED",
        "APPROVAL_EXPIRED",
        "APPROVAL_PAYLOAD_MISMATCH",
        "DUPLICATE_ACTION",
        "SESSION_CLOSED",
        "LATE_CALLBACK",
        "CODEX_BUSY",
        "CODEX_THREAD_INVALID",
        "CODEX_THREAD_RESUME_TIMEOUT",
        "CODEX_DISPATCH_TIMEOUT",
        "DEVICE_OFFLINE",
        "DEVICE_REVOKED",
        "EDGE_AUTH_FAILED",
        "EDGE_FRAME_INVALID",
        "EDGE_SEQUENCE_INVALID",
        "EDGE_JOB_INVALID",
        "EDGE_JOB_TIMEOUT",
        "EDGE_APPROVAL_NOT_FOUND",
        "EDGE_APPROVAL_EXPIRED",
        "PROVIDER_CONFLICT",
        "PROVIDER_LOGGED_OUT",
        "PROVIDER_AUTH_FAILED",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_RESPONSE_INVALID",
        "PROVIDER_TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "PROVIDER_DELIVERY_FAILED",
        "WEBHOOK_INVALID_SIGNATURE",
        "WEBHOOK_INVALID_PAYLOAD",
        "EXTERNAL_RESULT_UNKNOWN",
        "INVALID_REQUEST",
        "ACTION_NOT_FOUND",
        "SESSION_NOT_FOUND",
        "JOB_NOT_FOUND",
        "INTERNAL_ERROR",
    }
)


class JarvisAgentError(RuntimeError):
    """Sanitized exception carrying a stable public code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in PUBLIC_ERROR_CODES:
            raise ValueError(f"Unsupported Jarvis error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result
