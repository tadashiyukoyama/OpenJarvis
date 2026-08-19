"""Fail-closed environment configuration for the Windows Edge Worker."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import urlparse


def _positive(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, "").strip()
    result = float(raw) if raw else default
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, "").strip()
    result = int(raw) if raw else default
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _edge_url(value: str) -> str:
    parsed = urlparse(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "wss" and not (parsed.scheme == "ws" and loopback):
        raise ValueError("Edge URL must use wss://, except for loopback tests")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Edge URL is invalid")
    return value


def _app_server_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "ws"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Codex app-server must be an unauthenticated loopback URL")
    return value


@dataclass(frozen=True, slots=True)
class EdgeWorkerConfig:
    edge_url: str
    device_id: str
    token: str
    app_server_url: str
    state_path: Path
    binding_path: Path
    project_roots: tuple[str, ...]
    heartbeat_seconds: float = 15.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    approval_timeout_seconds: float = 300.0
    job_timeout_seconds: float = 600.0
    spool_max_frames: int = 10_000
    spool_max_bytes: int = 64 * 1024 * 1024
    replay_batch_size: int = 100

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "EdgeWorkerConfig":
        values = os.environ if environment is None else environment
        runtime_root = Path(
            values.get("OPENJARVIS_RUNTIME_ROOT", r"D:\dev\runtime\openjarvis")
        ).expanduser()
        edge_root = runtime_root / "edge-worker"
        roots = tuple(
            str(PureWindowsPath(item.strip()))
            for item in values.get(
                "OPENJARVIS_EDGE_PROJECT_ROOTS", r"D:\dev\workspaces"
            ).split(";")
            if item.strip()
        )
        config = cls(
            edge_url=_edge_url(values.get("OPENJARVIS_EDGE_WSS_URL", "").strip()),
            device_id=values.get("OPENJARVIS_EDGE_DEVICE_ID", "").strip(),
            token=values.get("OPENJARVIS_EDGE_TOKEN_CURRENT", "").strip(),
            app_server_url=_app_server_url(
                values.get(
                    "OPENJARVIS_CODEX_APP_SERVER_URL", "ws://127.0.0.1:8131"
                ).strip()
            ),
            state_path=edge_root / "edge-worker.sqlite3",
            binding_path=edge_root / "codex-bindings.sqlite3",
            project_roots=roots,
            heartbeat_seconds=_positive(
                values, "OPENJARVIS_EDGE_HEARTBEAT_SECONDS", 15.0
            ),
            reconnect_min_seconds=_positive(
                values, "OPENJARVIS_EDGE_RECONNECT_MIN_SECONDS", 1.0
            ),
            reconnect_max_seconds=_positive(
                values, "OPENJARVIS_EDGE_RECONNECT_MAX_SECONDS", 30.0
            ),
            approval_timeout_seconds=_positive(
                values, "OPENJARVIS_EDGE_APPROVAL_TIMEOUT_SECONDS", 300.0
            ),
            job_timeout_seconds=_positive(
                values, "OPENJARVIS_EDGE_JOB_TIMEOUT_SECONDS", 600.0
            ),
            spool_max_frames=_positive_int(
                values, "OPENJARVIS_EDGE_SPOOL_MAX_FRAMES", 10_000
            ),
            spool_max_bytes=_positive_int(
                values, "OPENJARVIS_EDGE_SPOOL_MAX_BYTES", 64 * 1024 * 1024
            ),
            replay_batch_size=_positive_int(
                values, "OPENJARVIS_EDGE_REPLAY_BATCH_SIZE", 100
            ),
        )
        if not config.device_id or not config.token or not config.project_roots:
            raise ValueError("Edge device, token and project roots are required")
        if len(config.token) < 32:
            raise ValueError("Edge device token is too short")
        if config.reconnect_max_seconds < config.reconnect_min_seconds:
            raise ValueError("Edge reconnect maximum is smaller than minimum")
        return config


__all__ = ["EdgeWorkerConfig"]
