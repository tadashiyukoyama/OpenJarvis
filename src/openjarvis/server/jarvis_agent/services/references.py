"""Opaque references that keep provider identifiers away from the model."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore

_REFERENCE_TTL_SECONDS = 30 * 24 * 60 * 60


class ReferenceService:
    def __init__(self, store: JarvisAgentStore) -> None:
        self._store = store

    def create(
        self,
        *,
        partition_key: str,
        source: str,
        kind: str,
        provider_value: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if not provider_value.strip():
            raise ValueError("provider reference value is required")
        now = time.time()
        value_hash = hashlib.sha256(provider_value.encode("utf-8")).hexdigest()
        prefix = {"email": "emr", "gmail": "gmr", "whatsapp": "war"}.get(source, "ref")
        reference_id = f"{prefix}_{secrets.token_urlsafe(18)}"
        return self._store.put_reference(
            {
                "reference_id": reference_id,
                "partition_key": partition_key,
                "source": source,
                "kind": kind,
                "value_hash": value_hash,
                "provider_value": provider_value,
                "metadata": dict(metadata or {}),
                "created_at": now,
                "expires_at": now + _REFERENCE_TTL_SECONDS,
            }
        )

    def resolve(
        self,
        reference_id: str,
        *,
        partition_key: str,
        source: str,
        kind: str | tuple[str, ...],
    ) -> dict[str, Any]:
        record = self._store.get_reference(reference_id, partition_key, time.time())
        kinds = {kind} if isinstance(kind, str) else set(kind)
        if record is None or record["source"] != source or record["kind"] not in kinds:
            raise JarvisAgentError(
                "INVALID_REQUEST",
                "A referência informada é inválida ou expirou.",
                status_code=409,
            )
        return record
