"""Bounded, structured cross-session context without transcript retention."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore

_RETENTION_SECONDS = 30 * 24 * 60 * 60
_MAX_ITEMS = 20
_MAX_TEXT = 2_000


def context_partition(project_key: str, codex_thread_id: str) -> str:
    canonical = f"{project_key.strip().casefold()}\x00{codex_thread_id.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bounded_text(value: object) -> str:
    return " ".join(str(value or "").split())[:_MAX_TEXT]


class ContextService:
    def __init__(self, store: JarvisAgentStore) -> None:
        self._store = store

    def read(self, project_key: str, codex_thread_id: str) -> dict[str, Any]:
        key = context_partition(project_key, codex_thread_id)
        record = self._store.get_context(key, time.time())
        if record is None:
            return self.empty()
        context = dict(record["context"])
        pending = list(context.get("pending") or [])
        active = []
        for item in pending:
            action_id = str(item.get("action_id") or "")
            action = self._store.get_action(action_id) if action_id else None
            if action and action.get("state") in {
                "PROPOSED",
                "AWAITING_APPROVAL",
                "APPROVED",
            }:
                active.append(item)
        if active != pending:
            context["pending"] = active
            self.write(project_key, codex_thread_id, context)
        return context

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "objective": "",
            "decisions": [],
            "pending": [],
            "results": [],
            "references": [],
        }

    def merge_result(
        self,
        *,
        project_key: str,
        codex_thread_id: str,
        tool_id: str,
        summary: str,
        status: str,
        trust: str,
        references: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        context = self.read(project_key, codex_thread_id)
        results = list(context.get("results") or [])[-(_MAX_ITEMS - 1) :]
        results.append(
            {
                "tool_id": tool_id,
                "status": status,
                "summary": _bounded_text(summary),
                "trust": trust,
                "at": int(time.time()),
            }
        )
        context["results"] = results
        if references:
            saved = list(context.get("references") or [])[-(_MAX_ITEMS - 1) :]
            saved.append({"tool_id": tool_id, "values": dict(references)})
            context["references"] = saved
        self.write(project_key, codex_thread_id, context)
        return context

    def set_objective(
        self,
        *,
        project_key: str,
        codex_thread_id: str,
        tool_id: str,
        action_id: str,
    ) -> None:
        """Persist a safe intent label, never the spoken or approved payload."""

        context = self.read(project_key, codex_thread_id)
        context["objective"] = _bounded_text(f"{tool_id} ({action_id})")
        self.write(project_key, codex_thread_id, context)

    def record_decision(
        self,
        *,
        project_key: str,
        codex_thread_id: str,
        action_id: str,
        tool_id: str,
        decision: str,
    ) -> None:
        """Remember only decision metadata; exact external payloads stay transient."""

        context = self.read(project_key, codex_thread_id)
        decisions = [
            item
            for item in list(context.get("decisions") or [])
            if item.get("action_id") != action_id
        ][-(_MAX_ITEMS - 1) :]
        decisions.append(
            {
                "action_id": action_id,
                "tool_id": tool_id,
                "decision": decision,
                "at": int(time.time()),
            }
        )
        context["decisions"] = decisions
        self.write(project_key, codex_thread_id, context)

    def set_pending(
        self,
        *,
        project_key: str,
        codex_thread_id: str,
        action_id: str,
        tool_id: str,
        status: str,
    ) -> None:
        """Persist only safe action metadata, never its external payload."""

        context = self.read(project_key, codex_thread_id)
        pending = [
            item
            for item in list(context.get("pending") or [])
            if item.get("action_id") != action_id
        ]
        pending.append(
            {
                "action_id": action_id,
                "tool_id": tool_id,
                "status": status,
                "at": int(time.time()),
            }
        )
        context["pending"] = pending[-_MAX_ITEMS:]
        self.write(project_key, codex_thread_id, context)

    def clear_pending(
        self, project_key: str, codex_thread_id: str, action_id: str
    ) -> None:
        context = self.read(project_key, codex_thread_id)
        context["pending"] = [
            item
            for item in list(context.get("pending") or [])
            if item.get("action_id") != action_id
        ]
        self.write(project_key, codex_thread_id, context)

    def write(
        self,
        project_key: str,
        codex_thread_id: str,
        context: Mapping[str, Any],
    ) -> None:
        now = time.time()
        self._store.put_context(
            {
                "partition_key": context_partition(project_key, codex_thread_id),
                "project_key": project_key,
                "codex_thread_id": codex_thread_id,
                "context": dict(context),
                "updated_at": now,
                "expires_at": now + _RETENTION_SECONDS,
            }
        )

    def delete(self, project_key: str, codex_thread_id: str) -> bool:
        return self._store.delete_context(
            context_partition(project_key, codex_thread_id)
        )
