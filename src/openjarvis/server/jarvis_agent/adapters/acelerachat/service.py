"""Single Jarvis adapter facade for AceleraChat email and WhatsApp."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import (
    AceleraChatConfig,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.email import (
    AceleraChatEmailTools,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp import (
    AceleraChatWhatsAppTools,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class AceleraChatAdapter:
    adapter_id = "acelerachat"

    def __init__(
        self,
        references: ReferenceService,
        *,
        config: AceleraChatConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        capability_ttl_seconds: float = 5.0,
    ) -> None:
        self.config = config or AceleraChatConfig.from_env()
        self.client = AceleraChatClient(self.config, transport=transport)
        self.capabilities = AceleraChatCapabilities(
            self.config,
            self.client,
            ttl_seconds=capability_ttl_seconds,
        )
        opaque = AceleraChatReferences(references)
        self._email = AceleraChatEmailTools(self.client, self.capabilities, opaque)
        self._whatsapp = AceleraChatWhatsAppTools(
            self.client, self.capabilities, opaque
        )

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        return {
            key: value.public_capabilities()
            for key, value in self.capabilities.all().items()
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        return self._handler(tool_id).prepare(tool_id, arguments, context)

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        return self._handler(tool_id).execute(tool_id, arguments, context)

    def close(self) -> None:
        self.client.close()

    def _handler(
        self, tool_id: str
    ) -> AceleraChatEmailTools | AceleraChatWhatsAppTools:
        if tool_id.startswith("email."):
            return self._email
        if tool_id.startswith("whatsapp."):
            return self._whatsapp
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta AceleraChat inválida.")
