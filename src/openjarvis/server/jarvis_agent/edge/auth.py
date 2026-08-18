"""Constant-time, per-device Edge authentication without secret logging."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig


@dataclass(frozen=True, slots=True)
class EdgeIdentity:
    device_id: str
    credential_slot: str


class EdgeAuthenticator:
    def __init__(self, config: EdgeCoreConfig) -> None:
        self._config = config

    @staticmethod
    def bearer_token(authorization: str) -> str:
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            return ""
        return value.strip()

    def authenticate(
        self, *, device_id: str, authorization: str, now: float | None = None
    ) -> EdgeIdentity | None:
        if not self._config.configured or device_id != self._config.device_id:
            return None
        token = self.bearer_token(authorization)
        if not token:
            return None
        if secrets.compare_digest(token, self._config.token_current):
            return EdgeIdentity(device_id, "current")
        timestamp = time.time() if now is None else now
        previous_valid = bool(
            self._config.token_previous
            and self._config.token_previous_expires_at is not None
            and timestamp < self._config.token_previous_expires_at
        )
        if previous_valid and secrets.compare_digest(
            token, self._config.token_previous
        ):
            return EdgeIdentity(device_id, "previous")
        return None


__all__ = ["EdgeAuthenticator", "EdgeIdentity"]
