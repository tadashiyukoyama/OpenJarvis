"""Environment-backed Core configuration for the Edge boundary."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


def _bounded_float(
    values: Mapping[str, str], name: str, default: float, low: float, high: float
) -> float:
    raw = values.get(name, "").strip()
    result = float(raw) if raw else default
    if result < low or result > high:
        raise ValueError(f"{name} is outside its safe range")
    return result


def _expiry_epoch(value: str) -> float | None:
    if not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("previous credential expiry must include a timezone")
    return parsed.timestamp()


def credential_fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class EdgeCoreConfig:
    device_id: str
    token_current: str
    token_previous: str
    token_previous_expires_at: float | None
    heartbeat_interval_seconds: float = 15.0
    heartbeat_timeout_seconds: float = 45.0
    offer_accept_timeout_seconds: float = 10.0
    lease_seconds: float = 120.0
    result_timeout_seconds: float = 600.0
    max_frame_bytes: int = 256 * 1024

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "EdgeCoreConfig":
        values = os.environ if environment is None else environment
        interval = _bounded_float(
            values, "OPENJARVIS_EDGE_HEARTBEAT_SECONDS", 15.0, 5.0, 300.0
        )
        timeout = _bounded_float(
            values, "OPENJARVIS_EDGE_TIMEOUT_SECONDS", 45.0, 10.0, 900.0
        )
        if timeout < interval * 2:
            raise ValueError("Edge timeout must cover at least two heartbeats")
        device_id = values.get("OPENJARVIS_EDGE_DEVICE_ID", "").strip()
        current = values.get("OPENJARVIS_EDGE_TOKEN_CURRENT", "").strip()
        previous = values.get("OPENJARVIS_EDGE_TOKEN_PREVIOUS", "").strip()
        previous_expiry = _expiry_epoch(
            values.get("OPENJARVIS_EDGE_TOKEN_PREVIOUS_EXPIRES_AT", "")
        )
        if bool(device_id) != bool(current):
            raise ValueError("Edge device configuration is incomplete")
        if current and len(current) < 32:
            raise ValueError("Edge current credential is too short")
        if previous and (len(previous) < 32 or previous_expiry is None):
            raise ValueError("Edge previous credential requires strength and expiry")
        return cls(
            device_id=device_id,
            token_current=current,
            token_previous=previous,
            token_previous_expires_at=previous_expiry,
            heartbeat_interval_seconds=interval,
            heartbeat_timeout_seconds=timeout,
            offer_accept_timeout_seconds=_bounded_float(
                values, "OPENJARVIS_EDGE_ACCEPT_TIMEOUT_SECONDS", 10.0, 2.0, 60.0
            ),
            lease_seconds=_bounded_float(
                values, "OPENJARVIS_EDGE_LEASE_SECONDS", 120.0, 30.0, 3_600.0
            ),
            result_timeout_seconds=_bounded_float(
                values, "OPENJARVIS_EDGE_JOB_TIMEOUT_SECONDS", 600.0, 30.0, 3_600.0
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(self.device_id and self.token_current)

    def credential_metadata(self) -> dict[str, str | float | None]:
        return {
            "current_credential_fingerprint": credential_fingerprint(
                self.token_current
            ),
            "previous_credential_fingerprint": credential_fingerprint(
                self.token_previous
            ),
            "previous_credential_expires_at": self.token_previous_expires_at,
        }


__all__ = ["EdgeCoreConfig", "credential_fingerprint"]
