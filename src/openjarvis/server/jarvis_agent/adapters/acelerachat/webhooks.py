"""Signed, idempotent AceleraChat webhook and backfill reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import (
    AceleraChatConfig,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import WebhookEnvelope
from openjarvis.server.jarvis_agent.adapters.acelerachat.reconciliation import (
    AceleraChatReconciler,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.states import ActionState
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService

_MAX_BODY_BYTES = 1024 * 1024
_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60
_EVENTS = frozenset(
    {
        "message.created",
        "message.updated",
        "conversation.created",
        "conversation.updated",
        "conversation.status_changed",
        "contact.created",
        "contact.updated",
        "integration.test",
        "resource.snapshot",
    }
)


class AceleraChatWebhookService:
    def __init__(
        self,
        *,
        config: AceleraChatConfig,
        client: AceleraChatClient,
        store: JarvisAgentStore,
        events: EventService,
        context: ContextService,
    ) -> None:
        self._config = config
        self._store = store
        self._events = events
        self._context = context
        self._reconciler = AceleraChatReconciler(
            client=client,
            events=events,
            processor=self._process,
        )

    def receive(
        self,
        body: bytes,
        *,
        delivery_id: str,
        timestamp: str,
        signature: str,
        previous_signature: str = "",
    ) -> dict[str, Any]:
        self._verify_request(
            body,
            delivery_id=delivery_id,
            timestamp=timestamp,
            signatures=(signature, previous_signature),
        )
        envelope = self._parse(body)
        return self._process(envelope, delivery_id=delivery_id)

    def reconcile(self, resource: str, *, max_pages: int = 10) -> dict[str, int]:
        return self._reconciler.reconcile(resource, max_pages=max_pages)

    def schedule_all(self) -> None:
        if not self._config.api_enabled:
            return
        self._reconciler.schedule_all()

    def close(self) -> None:
        self._reconciler.close()

    def _verify_request(
        self,
        body: bytes,
        *,
        delivery_id: str,
        timestamp: str,
        signatures: tuple[str, str],
    ) -> None:
        if len(body) > _MAX_BODY_BYTES:
            raise JarvisAgentError(
                "WEBHOOK_INVALID_PAYLOAD",
                "Webhook excedeu o limite seguro.",
                status_code=400,
            )
        if not self._config.webhook_enabled:
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED",
                "O segredo de webhook do AceleraChat não está configurado.",
                status_code=503,
            )
        try:
            uuid.UUID(delivery_id)
            timestamp_value = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise JarvisAgentError(
                "WEBHOOK_INVALID_PAYLOAD", "Cabeçalhos do webhook são inválidos."
            ) from exc
        if abs(time.time() - timestamp_value) > _TIMESTAMP_TOLERANCE_SECONDS:
            raise JarvisAgentError(
                "WEBHOOK_INVALID_SIGNATURE", "Webhook expirado.", status_code=401
            )
        signed = timestamp.encode("ascii") + b"." + body
        configured = (
            self._config.webhook_secret_current,
            self._config.webhook_secret_previous,
        )
        expected = [
            "sha256="
            + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            for secret in configured
            if secret
        ]
        presented = [value.strip() for value in signatures if value.strip()]
        if not any(
            hmac.compare_digest(candidate, value)
            for candidate in presented
            for value in expected
        ):
            raise JarvisAgentError(
                "WEBHOOK_INVALID_SIGNATURE",
                "Assinatura do webhook inválida.",
                status_code=401,
            )

    @staticmethod
    def _parse(body: bytes) -> WebhookEnvelope:
        try:
            value = json.loads(body)
            envelope = WebhookEnvelope.model_validate(value)
        except (UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise JarvisAgentError(
                "WEBHOOK_INVALID_PAYLOAD", "Payload do webhook inválido."
            ) from exc
        if envelope.schema_version != "1.0" or envelope.event not in _EVENTS:
            raise JarvisAgentError(
                "WEBHOOK_INVALID_PAYLOAD", "Versão ou evento do webhook não suportado."
            )
        return envelope

    def _process(
        self, envelope: WebhookEnvelope, *, delivery_id: str
    ) -> dict[str, Any]:
        state, summary, error_code, delivery = self._delivery_state(envelope)
        result = self._store.record_provider_event(
            delivery_id=delivery_id,
            event_id=envelope.event_id,
            provider="acelerachat",
            event_name=envelope.event,
            resource_type=envelope.resource.type,
            resource_id=str(envelope.resource.id),
            resource_sequence=envelope.resource.sequence,
            resource_version=envelope.resource.version,
            occurred_at=envelope.occurred_at,
            received_at=time.time(),
            next_state=state.value,
            result={"status": delivery, "provider": "acelerachat"},
            summary=summary,
            error_code=error_code,
        )
        action = result.get("action")
        if result["disposition"] == "accepted_with_gap":
            resource = {
                "Contact": "contacts",
                "Conversation": "conversations",
                "Message": "messages",
            }.get(envelope.resource.type)
            if resource:
                self._reconciler.schedule(resource)
        self._events.emit(
            "provider_event_received",
            session_id=action.get("session_id") if action else None,
            action_id=action.get("action_id") if action else None,
            payload={
                "provider": "acelerachat",
                "event": envelope.event,
                "disposition": result["disposition"],
                "state": action.get("state") if action else None,
            },
        )
        if (
            result.get("transitioned")
            and action
            and action.get("state")
            in {
                ActionState.COMPLETED.value,
                ActionState.FAILED.value,
            }
        ):
            self._remember_reconciled(action, summary, delivery)
            self._events.emit(
                "dispatch_completed"
                if action["state"] == ActionState.COMPLETED.value
                else "dispatch_failed",
                session_id=action["session_id"],
                action_id=action["action_id"],
                payload={
                    "tool_id": action["tool_id"],
                    "status": delivery,
                    "source": "acelerachat_webhook",
                },
            )
        return {
            "status": "accepted",
            "disposition": result["disposition"],
            "event_id": envelope.event_id,
        }

    def _remember_reconciled(
        self, action: Mapping[str, Any], summary: str, delivery: str
    ) -> None:
        session = self._store.get_session(str(action["session_id"]))
        if session is None:
            return
        persisted = action.get("result") or {}
        references = (
            persisted.get("references") if isinstance(persisted, Mapping) else {}
        )
        self._context.merge_result(
            project_key=str(session["project_key"]),
            codex_thread_id=str(session.get("codex_thread_id") or ""),
            tool_id=str(action["tool_id"]),
            summary=summary,
            status=delivery,
            trust="external_untrusted_data",
            references=references if isinstance(references, Mapping) else {},
        )

    @staticmethod
    def _delivery_state(
        envelope: WebhookEnvelope,
    ) -> tuple[ActionState, str, str | None, str]:
        if envelope.resource.type != "Message":
            return (
                ActionState.ACCEPTED,
                "Evento AceleraChat registrado.",
                None,
                "pending",
            )
        delivery = envelope.data.get("delivery")
        delivery = delivery if isinstance(delivery, Mapping) else {}
        status = str(envelope.data.get("status") or delivery.get("status") or "sent")
        result_state = str(delivery.get("result_state") or "unknown")
        if status == "failed" or result_state == "failed":
            return (
                ActionState.FAILED,
                "O AceleraChat confirmou falha na entrega.",
                "PROVIDER_DELIVERY_FAILED",
                "failed",
            )
        if status in {"delivered", "read"} or result_state == "confirmed":
            return (
                ActionState.COMPLETED,
                "O AceleraChat confirmou a entrega.",
                None,
                status,
            )
        return (
            ActionState.ACCEPTED,
            "A operação continua aguardando confirmação de entrega.",
            None,
            "pending",
        )
