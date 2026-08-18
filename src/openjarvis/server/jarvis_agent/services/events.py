"""Canonical, sanitized event writer used by SSE and diagnostics."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


class EventService:
    def __init__(self, store: JarvisAgentStore) -> None:
        self._store = store

    def emit(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        action_id: str | None = None,
        job_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        return self._store.append_event(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "session_id": session_id,
                "action_id": action_id,
                "job_id": job_id,
                "payload": dict(payload or {}),
                "created_at": time.time(),
            }
        )

    def after(self, sequence: int, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list_events(sequence, limit)
