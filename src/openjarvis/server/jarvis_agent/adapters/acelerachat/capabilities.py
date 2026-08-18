"""Live inbox selection and fail-closed capability projection."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

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
    capabilities: frozenset[str]
    reason: str | None

    def public_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            self.provider_id,
            self.status,
            self.capabilities,
            self.connected,
            self.reason,
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

    def invalidate(self) -> None:
        with self._lock:
            self._cache = {}
            self._cached_at = 0.0

    def _load(self) -> dict[str, ChannelSnapshot]:
        if not self._config.api_enabled:
            reason = self._config.unavailable_reason
            return {
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
        channel_type: str,
        configured_id: int | None,
        status_capability: bool = False,
    ) -> ChannelSnapshot:
        candidates = [item for item in inboxes if item.channel_type == channel_type]
        if configured_id is not None:
            candidates = [item for item in candidates if item.id == configured_id]
        if not candidates:
            return self._unavailable(
                provider_id,
                "configured_inbox_not_found" if configured_id else "inbox_not_found",
                status_capability=status_capability,
            )
        if len(candidates) > 1:
            return self._unavailable(
                provider_id,
                "inbox_selection_required",
                status="selection_required",
                status_capability=status_capability,
            )
        inbox = candidates[0]
        operational = inbox.connection.operational or inbox.connection.connected
        declared = frozenset(
            key for key, value in inbox.capabilities.items() if value.supported
        )
        capabilities = declared if operational else frozenset()
        if status_capability:
            capabilities = frozenset({*capabilities, "connection.inspect"})
        return ChannelSnapshot(
            provider_id,
            inbox,
            inbox.connection.state,
            inbox.connection.connected,
            capabilities,
            None
            if operational
            else (inbox.connection.error_code or "source_disconnected"),
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
        return ChannelSnapshot(provider_id, None, status, False, capabilities, reason)
