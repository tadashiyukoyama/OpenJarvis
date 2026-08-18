"""Safe frame ledger and cross-thread delivery for the Edge protocol."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import (
    PUBLIC_ERROR_CODES,
    JarvisAgentError,
)
from openjarvis.server.jarvis_agent.domain.models import payload_digest
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame, make_edge_frame
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


class EdgeProtocol:
    """Own sequence allocation, safe audit metadata, and frame delivery."""

    def __init__(self, store: JarvisAgentStore) -> None:
        self.store = store

    def record_inbound(self, frame: EdgeFrame, *, metadata: Mapping[str, Any]) -> bool:
        try:
            return self.store.record_edge_event(
                event_id=str(frame.event_id),
                device_id=frame.device_id,
                direction="inbound",
                sequence=frame.sequence,
                event_type=frame.type,
                job_id=frame.job_id,
                payload_hash=payload_digest(frame.payload),
                metadata=metadata,
                occurred_at=frame.occurred_at.isoformat().replace("+00:00", "Z"),
                received_at=time.time(),
            )
        except sqlite3.IntegrityError as exc:
            raise JarvisAgentError(
                "EDGE_SEQUENCE_INVALID",
                "A sequência de eventos Edge é inválida.",
                status_code=409,
            ) from exc

    def outbound_frame(
        self,
        device_id: str,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str | None = None,
    ) -> EdgeFrame:
        now = time.time()
        sequence = self.store.next_edge_outbound_sequence(device_id, now=now)
        frame = make_edge_frame(
            frame_type=frame_type,
            device_id=device_id,
            sequence=sequence,
            payload=payload,
            job_id=job_id,
            from_client=False,
        )
        self.store.record_edge_event(
            event_id=str(frame.event_id),
            device_id=device_id,
            direction="outbound",
            sequence=sequence,
            event_type=frame_type,
            job_id=job_id,
            payload_hash=payload_digest(frame.payload),
            metadata=self.safe_metadata(frame, payload),
            occurred_at=frame.occurred_at.isoformat().replace("+00:00", "Z"),
            received_at=now,
        )
        return frame

    @staticmethod
    def safe_metadata(frame: EdgeFrame, payload: Mapping[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {"type": frame.type}
        if "capabilities" in payload:
            metadata["capability_count"] = len(payload.get("capabilities") or [])
        if "active_job_ids" in payload:
            metadata["active_job_count"] = len(payload.get("active_job_ids") or [])
        for key in ("attempt_id", "stage", "code", "status", "kind", "approval_id"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)):
                metadata[key] = value
        if "summary" in payload:
            metadata["summary_length"] = len(str(payload.get("summary") or ""))
        return metadata

    @staticmethod
    def safe_error_code(code: str) -> str:
        return code if code in PUBLIC_ERROR_CODES else "EXTERNAL_RESULT_UNKNOWN"

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def send_from_thread(connection: EdgeConnection, frame: EdgeFrame) -> None:
        future = asyncio.run_coroutine_threadsafe(
            connection.send(frame), connection.loop
        )
        try:
            future.result(timeout=5.0)
        except Exception as exc:
            raise JarvisAgentError(
                "DEVICE_OFFLINE",
                "Não foi possível alcançar o worker Edge.",
                status_code=503,
            ) from exc


__all__ = ["EdgeProtocol"]
