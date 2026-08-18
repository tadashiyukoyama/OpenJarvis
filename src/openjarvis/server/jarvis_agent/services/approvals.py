"""Visual, single-use approval state transitions."""

from __future__ import annotations

import sqlite3
import time
import uuid

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


class ApprovalService:
    def __init__(self, store: JarvisAgentStore) -> None:
        self._store = store

    def decide(
        self,
        *,
        action_id: str,
        session_id: str,
        payload_hash: str,
        decision: str,
    ) -> dict:
        if decision not in {"approve", "deny"}:
            raise JarvisAgentError(
                "INVALID_REQUEST", "A decisão deve ser approve ou deny."
            )
        try:
            action = self._store.decide_action(
                approval_id=f"apr_{uuid.uuid4().hex}",
                action_id=action_id,
                session_id=session_id,
                payload_hash=payload_hash,
                decision=decision,
                now=time.time(),
            )
        except sqlite3.IntegrityError as exc:
            raise JarvisAgentError(
                "APPROVAL_PAYLOAD_MISMATCH",
                "A aprovação não corresponde ao payload exibido.",
                status_code=409,
            ) from exc
        if action is None:
            raise JarvisAgentError(
                "ACTION_NOT_FOUND", "A ação não existe.", status_code=404
            )
        return action
