"""Read-only AceleraChat backfill reconciliation and scheduling."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Any, Protocol

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import WebhookEnvelope
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.services.events import EventService

_RESOURCES = ("contacts", "conversations", "messages")
_MAX_PAGES = 10


class EnvelopeProcessor(Protocol):
    def __call__(
        self, envelope: WebhookEnvelope, *, delivery_id: str
    ) -> dict[str, Any]: ...


class AceleraChatReconciler:
    """Serializes bounded, read-only recovery of provider event gaps."""

    def __init__(
        self,
        *,
        client: AceleraChatClient,
        events: EventService,
        processor: EnvelopeProcessor,
    ) -> None:
        self._client = client
        self._events = events
        self._processor = processor
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="acelerachat-reconcile"
        )
        self._scheduled: set[str] = set()
        self._lock = Lock()
        self._closing = Event()

    def reconcile(
        self, resource: str, *, max_pages: int = _MAX_PAGES
    ) -> dict[str, int]:
        self._validate_resource(resource)
        cursor: str | None = None
        counts = {"accepted": 0, "duplicate": 0, "out_of_order": 0}
        for _ in range(max_pages):
            if self._closing.is_set():
                return counts
            payload = self._client.backfill(resource, cursor=cursor, limit=100)
            values = payload.get("data")
            meta = payload.get("meta")
            if not isinstance(values, list) or not isinstance(meta, Mapping):
                raise self._invalid("O backfill retornou contrato inválido.")
            for value in values:
                envelope = self._envelope(value)
                outcome = self._processor(
                    envelope, delivery_id=f"backfill:{envelope.event_id}"
                )
                disposition = str(outcome["disposition"])
                key = disposition if disposition in counts else "accepted"
                counts[key] += 1
            if not meta.get("has_more"):
                return counts
            cursor = self._next_cursor(meta)
        raise self._invalid("O backfill excedeu o limite operacional.")

    def schedule_all(self) -> None:
        for resource in _RESOURCES:
            self.schedule(resource)

    def schedule(self, resource: str) -> None:
        self._validate_resource(resource)
        with self._lock:
            if self._closing.is_set() or resource in self._scheduled:
                return
            self._scheduled.add(resource)
        self._pool.submit(self._run, resource)

    def close(self) -> None:
        self._closing.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, resource: str) -> None:
        try:
            counts = self.reconcile(resource)
            if self._closing.is_set():
                return
            self._events.emit(
                "provider_reconciliation_completed",
                payload={"provider": "acelerachat", "resource": resource, **counts},
            )
        except JarvisAgentError as exc:
            self._events.emit(
                "provider_reconciliation_failed",
                payload={
                    "provider": "acelerachat",
                    "resource": resource,
                    "code": exc.code,
                },
            )
        finally:
            with self._lock:
                self._scheduled.discard(resource)

    @staticmethod
    def _validate_resource(resource: str) -> None:
        if resource not in _RESOURCES:
            raise JarvisAgentError("INVALID_REQUEST", "Recurso de backfill inválido.")

    @classmethod
    def _envelope(cls, value: Any) -> WebhookEnvelope:
        try:
            return WebhookEnvelope.model_validate(value)
        except ValidationError as exc:
            raise cls._invalid("O backfill retornou um item inválido.") from exc

    @classmethod
    def _next_cursor(cls, meta: Mapping[str, Any]) -> str:
        value = meta.get("next_cursor")
        if not isinstance(value, str) or not value:
            raise cls._invalid("Cursor de backfill inválido.")
        return value

    @staticmethod
    def _invalid(message: str) -> JarvisAgentError:
        return JarvisAgentError("PROVIDER_RESPONSE_INVALID", message)
