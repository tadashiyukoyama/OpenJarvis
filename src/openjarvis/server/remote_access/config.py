"""Configuration boundary for the authenticated remote-access gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _required_path(name: str, fallback: Path | None = None) -> Path:
    raw_value = os.environ.get(name, "").strip()
    if raw_value:
        return Path(raw_value).expanduser().resolve()
    if fallback is not None:
        return fallback.expanduser().resolve()
    raise RuntimeError(f"{name} must point to a private local file")


def _positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Validated gateway configuration with no embedded credential values."""

    origin: str
    credentials_file: Path
    access_log_file: Path
    session_ttl_seconds: int = 14_400
    continuation_ttl_seconds: int = 300
    secure_cookie: bool = True

    def __post_init__(self) -> None:
        parsed = urlparse(self.origin)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Gateway origin must use HTTP or HTTPS")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Gateway origin must remain on loopback")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Gateway origin must not contain credentials or a query")
        if self.session_ttl_seconds <= 0 or self.continuation_ttl_seconds <= 0:
            raise ValueError("Gateway token lifetimes must be positive")

    @classmethod
    def from_environment(cls) -> "GatewayConfig":
        """Load paths from explicit environment variables or managed roots."""

        workspace_raw = os.environ.get("OPENJARVIS_WORKSPACE_ROOT", "").strip()
        runtime_raw = os.environ.get("OPENJARVIS_RUNTIME_ROOT", "").strip()
        credential_fallback = (
            Path(workspace_raw) / ".private" / "env" / "cloudflare-quick-tunnel.env"
            if workspace_raw
            else None
        )
        access_log_fallback = (
            Path(runtime_raw) / "cloudflare" / "gateway-access.log"
            if runtime_raw
            else None
        )
        origin = os.environ.get("OJ_GATEWAY_ORIGIN", "http://127.0.0.1:8127").strip()
        return cls(
            origin=origin.rstrip("/"),
            credentials_file=_required_path(
                "OJ_GATEWAY_SECRET_FILE", credential_fallback
            ),
            access_log_file=_required_path(
                "OJ_GATEWAY_ACCESS_LOG", access_log_fallback
            ),
            session_ttl_seconds=_positive_int("OJ_GATEWAY_SESSION_TTL_SECONDS", 14_400),
            continuation_ttl_seconds=_positive_int(
                "OJ_GATEWAY_CONTINUATION_TTL_SECONDS", 300
            ),
            secure_cookie=_boolean("OJ_GATEWAY_SECURE_COOKIE", True),
        )


__all__ = ["GatewayConfig"]
