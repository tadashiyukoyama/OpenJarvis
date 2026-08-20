"""Live inbox selection and fail-closed capability projection."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import (
    AceleraChatConfig,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import Inbox
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    provider_id: str
    inbox: Inbox | None
    status: str
    connected: bool
    operational: bool
    capabilities: frozenset[str]
    reason: str | None
    inboxes: tuple[Inbox, ...] = ()

    @property
    def operational_inboxes(self) -> tuple[Inbox, ...]:
        return tuple(
            inbox
            for inbox in self.inboxes
            if inbox.connection.operational or inbox.connection.connected
        )

    def public_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            self.provider_id,
            self.status,
            self.capabilities,
            self.connected,
            self.reason,
            self.operational,
        )


class AceleraChatCapabilities:
    def __init__(
        self,
        config: AceleraChatConfig,
        client: AceleraChatClient,
        *,
        ttl_seconds: float = 5.0,
    ) -> None:
        self._config = config
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cache: dict[str, ChannelSnapshot] = {}

    def all(self, *, force: bool = False) -> dict[str, ChannelSnapshot]:
        with self._lock:
            if (
                not force
                and self._cache
                and time.monotonic() - self._cached_at < self._ttl_seconds
            ):
                return dict(self._cache)
            self._cache = self._load()
            self._cached_at = time.monotonic()
            return dict(self._cache)

    def channel(self, provider_id: str, *, force: bool = False) -> ChannelSnapshot:
        return self.all(force=force).get(provider_id) or self._unavailable(
            provider_id, "provider_unavailable"
        )

    def select(
        self,
        provider_id: str,
        *,
        inbox_id: int | None = None,
        inbox_name: str = "",
        required_capability: str = "",
        force: bool = False,
    ) -> ChannelSnapshot:
        snapshot = self.channel(provider_id, force=force)
        operational_inboxes = snapshot.operational_inboxes
        eligible_inboxes = tuple(
            inbox
            for inbox in operational_inboxes
            if self._supports(inbox, required_capability)
        )
        if inbox_id is not None and inbox_name.strip():
            raise JarvisAgentError(
                "INVALID_REQUEST", "Selecione a caixa por ID ou nome, não ambos."
            )
        if inbox_id is not None:
            requested = [inbox for inbox in snapshot.inboxes if inbox.id == inbox_id]
        elif inbox_name.strip():
            wanted = inbox_name.strip().casefold()
            requested = [
                inbox for inbox in snapshot.inboxes if inbox.name.casefold() == wanted
            ]
        else:
            requested = []

        if requested:
            inbox = requested[0]
            if inbox not in operational_inboxes:
                self._raise_source_disconnected()
            if not self._supports(inbox, required_capability):
                self._raise_capability_unavailable(required_capability)
            return self._selected_snapshot(snapshot, inbox)
        if inbox_id is not None or inbox_name.strip():
            self._raise_source_disconnected()

        if snapshot.inbox is not None and snapshot.inbox in eligible_inboxes:
            matches = [snapshot.inbox]
        else:
            matches = list(eligible_inboxes)

        if len(matches) == 1:
            return self._selected_snapshot(snapshot, matches[0])
        if not matches:
            if operational_inboxes and required_capability:
                self._raise_capability_unavailable(required_capability)
            self._raise_source_disconnected()
        raise JarvisAgentError(
            "INBOX_SELECTION_REQUIRED",
            "Há mais de uma caixa disponível; informe o ID ou o nome exato.",
            status_code=409,
        )

    @staticmethod
    def _supports(inbox: Inbox, capability: str) -> bool:
        if not capability:
            return True
        value = inbox.capabilities.get(capability)
        return bool(value and value.supported)

    @staticmethod
    def _selected_snapshot(snapshot: ChannelSnapshot, inbox: Inbox) -> ChannelSnapshot:
        return replace(
            snapshot,
            inbox=inbox,
            status=inbox.connection.state,
            connected=inbox.connection.connected,
            operational=True,
            reason=None,
        )

    @staticmethod
    def _raise_source_disconnected() -> None:
        raise JarvisAgentError(
            "SOURCE_DISCONNECTED",
            "A caixa solicitada não existe, não está autorizada ou está desconectada.",
        )

    @staticmethod
    def _raise_capability_unavailable(capability: str) -> None:
        raise JarvisAgentError(
            "CAPABILITY_NOT_AVAILABLE",
            f"A caixa não oferece a capacidade {capability}.",
        )

    def invalidate(self) -> None:
        with self._lock:
            self._cache = {}
            self._cached_at = 0.0

    def _load(self) -> dict[str, ChannelSnapshot]:
        if not self._config.api_enabled:
            reason = self._config.unavailable_reason
            return {
                "acelerachat_inboxes": self._unavailable(
                    "acelerachat_inboxes", reason, status_capability=True
                ),
                "acelerachat_email": self._unavailable("acelerachat_email", reason),
                "acelerachat_whatsapp": self._unavailable(
                    "acelerachat_whatsapp", reason, status_capability=True
                ),
            }
        try:
            inboxes = [
                Inbox.model_validate(value) for value in self._client.list_inboxes()
            ]
        except JarvisAgentError as exc:
            reason = exc.code.lower()
            return {
                "acelerachat_inboxes": self._unavailable(
                    "acelerachat_inboxes",
                    reason,
                    status="error",
                    status_capability=True,
                ),
                "acelerachat_email": self._unavailable(
                    "acelerachat_email", reason, status="error"
                ),
                "acelerachat_whatsapp": self._unavailable(
                    "acelerachat_whatsapp",
                    reason,
                    status="error",
                    status_capability=True,
                ),
            }
        except ValidationError:
            return {
                "acelerachat_inboxes": self._unavailable(
                    "acelerachat_inboxes",
                    "provider_response_invalid",
                    status="error",
                    status_capability=True,
                ),
                "acelerachat_email": self._unavailable(
                    "acelerachat_email", "provider_response_invalid", status="error"
                ),
                "acelerachat_whatsapp": self._unavailable(
                    "acelerachat_whatsapp",
                    "provider_response_invalid",
                    status="error",
                    status_capability=True,
                ),
            }
        return {
            "acelerachat_inboxes": self._select(
                "acelerachat_inboxes",
                inboxes,
                channel_type=None,
                configured_id=None,
                status_capability=True,
            ),
            "acelerachat_email": self._select(
                "acelerachat_email",
                inboxes,
                channel_type="Channel::Email",
                configured_id=self._config.email_inbox_id,
            ),
            "acelerachat_whatsapp": self._select(
                "acelerachat_whatsapp",
                inboxes,
                channel_type="Channel::Whatsapp",
                configured_id=self._config.whatsapp_inbox_id,
                status_capability=True,
            ),
        }

    def _select(
        self,
        provider_id: str,
        inboxes: list[Inbox],
        *,
        channel_type: str | None,
        configured_id: int | None,
        status_capability: bool = False,
    ) -> ChannelSnapshot:
        candidates = [
            item
            for item in inboxes
            if channel_type is None or item.channel_type == channel_type
        ]
        if not candidates:
            return self._unavailable(
                provider_id,
                "configured_inbox_not_found" if configured_id else "inbox_not_found",
                status_capability=status_capability,
            )
        operational_inboxes = [
            inbox
            for inbox in candidates
            if inbox.connection.operational or inbox.connection.connected
        ]
        configured = next(
            (inbox for inbox in operational_inboxes if inbox.id == configured_id), None
        )
        inbox = configured or (
            operational_inboxes[0] if len(operational_inboxes) == 1 else None
        )
        operational = bool(operational_inboxes)
        capabilities = frozenset(
            key
            for candidate in operational_inboxes
            for key, value in candidate.capabilities.items()
            if value.supported
        )
        if status_capability:
            capabilities = frozenset({*capabilities, "connection.inspect"})
        connected = any(candidate.connection.connected for candidate in candidates)
        status = (
            inbox.connection.state
            if inbox is not None
            else "multiple_available"
            if operational
            else candidates[0].connection.state
        )
        reason = None
        if not operational:
            reason = candidates[0].connection.error_code or "source_disconnected"
        elif inbox is None:
            reason = "inbox_selection_required"
        return ChannelSnapshot(
            provider_id,
            inbox,
            status,
            connected,
            operational,
            capabilities,
            reason,
            tuple(candidates),
        )

    @staticmethod
    def _unavailable(
        provider_id: str,
        reason: str,
        *,
        status: str = "disconnected",
        status_capability: bool = False,
    ) -> ChannelSnapshot:
        capabilities = (
            frozenset({"connection.inspect"}) if status_capability else frozenset()
        )
        return ChannelSnapshot(
            provider_id,
            None,
            status,
            False,
            False,
            capabilities,
            reason,
        )
