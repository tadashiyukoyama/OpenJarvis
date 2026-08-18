"""Opaque AceleraChat references scoped to a Jarvis context partition."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class AceleraChatReferences:
    def __init__(self, references: ReferenceService) -> None:
        self._references = references

    def create(
        self,
        *,
        partition_key: str,
        source: str,
        kind: str,
        resource_id: int,
        inbox_id: int,
        conversation_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        value = {
            "resource_id": resource_id,
            "inbox_id": inbox_id,
            "conversation_id": conversation_id,
        }
        return self._references.create(
            partition_key=partition_key,
            source=source,
            kind=kind,
            provider_value=json.dumps(value, separators=(",", ":"), sort_keys=True),
            metadata=metadata,
        )

    def resolve(
        self,
        reference_id: str,
        *,
        partition_key: str,
        source: str,
        kind: str | tuple[str, ...],
    ) -> dict[str, int | None]:
        record = self._references.resolve(
            reference_id,
            partition_key=partition_key,
            source=source,
            kind=kind,
        )
        try:
            value = json.loads(str(record["provider_value"]))
            resource_id = int(value["resource_id"])
            inbox_id = int(value["inbox_id"])
            conversation = value.get("conversation_id")
            conversation_id = int(conversation) if conversation is not None else None
            if (
                resource_id <= 0
                or inbox_id <= 0
                or (conversation_id is not None and conversation_id <= 0)
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST",
                "A referência do AceleraChat está corrompida ou expirou.",
                status_code=409,
            ) from exc
        return {
            "resource_id": resource_id,
            "inbox_id": inbox_id,
            "conversation_id": conversation_id,
        }
