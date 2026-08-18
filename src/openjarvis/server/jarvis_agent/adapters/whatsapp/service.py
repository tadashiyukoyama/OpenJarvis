"""Granular WhatsApp adapter backed by the existing Baileys channel."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from openjarvis.channels.whatsapp.bridge_commands import (
    BridgeCommandError,
    BridgeCommandTimeout,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.whatsapp.arguments import (
    WhatsAppArguments,
)
from openjarvis.server.jarvis_agent.adapters.whatsapp.commands import (
    WhatsAppCommandBuilder,
)
from openjarvis.server.jarvis_agent.adapters.whatsapp.references import (
    WhatsAppReferences,
    public_messages,
    scrub_provider_ids,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities
from openjarvis.server.jarvis_agent.services.references import ReferenceService

_LOCAL_READ_CAPABILITIES = {
    "whatsapp.status",
    "whatsapp.contacts",
    "whatsapp.chats",
    "whatsapp.messages",
    "whatsapp.summary",
}
_CONNECTED_READ_CAPABILITIES = {
    "whatsapp.group_metadata",
    "whatsapp.privacy_read",
}
_MUTATION_CAPABILITIES = {
    "whatsapp.send",
    "whatsapp.reply",
    "whatsapp.react",
    "whatsapp.mark_read",
    "whatsapp.media",
    "whatsapp.poll",
    "whatsapp.archive",
    "whatsapp.pin",
    "whatsapp.mute",
    "whatsapp.group_create",
    "whatsapp.group_subject",
    "whatsapp.privacy_update",
    "whatsapp.profile_status",
    "whatsapp.broadcast",
}


class WhatsAppAdapter:
    adapter_id = "whatsapp"

    def __init__(
        self,
        references: ReferenceService,
        channel_getter: Callable[[], Any],
    ) -> None:
        self._channel_getter = channel_getter
        self._references = WhatsAppReferences(references)
        self._commands = WhatsAppCommandBuilder(self._references)

    def _channel(self) -> Any:
        try:
            return self._channel_getter()
        except Exception as exc:
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED",
                "O provedor WhatsApp Baileys está indisponível.",
                status_code=503,
            ) from exc

    def _snapshot(self) -> dict[str, Any]:
        channel = self._channel()
        snapshot = getattr(channel, "status_snapshot", None)
        if callable(snapshot):
            return dict(snapshot())
        status = channel.status()
        value = getattr(status, "value", str(status))
        return {"status": value, "send_available": value == "connected"}

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        try:
            snapshot = self._snapshot()
        except JarvisAgentError:
            snapshot = {"status": "failed", "send_available": False}
        status = str(snapshot.get("status") or "disconnected")
        connected = bool(status == "connected" and snapshot.get("send_available"))
        capabilities = set(_LOCAL_READ_CAPABILITIES)
        if connected:
            capabilities.update(_CONNECTED_READ_CAPABILITIES)
            capabilities.update(_MUTATION_CAPABILITIES)
        reason = None if connected else status
        return {
            "whatsapp_baileys": ProviderCapabilities(
                "whatsapp_baileys",
                status,
                frozenset(capabilities),
                connected,
                reason,
            ),
            "whatsapp_meta": ProviderCapabilities(
                "whatsapp_meta",
                "unavailable",
                frozenset(),
                False,
                "not_implemented",
            ),
            "whatsapp_export": ProviderCapabilities(
                "whatsapp_export",
                "import_only",
                frozenset(),
                False,
                "historical_ingestion_only",
            ),
        }

    @staticmethod
    def _parse(arguments: Mapping[str, Any]) -> WhatsAppArguments:
        try:
            return WhatsAppArguments.model_validate(dict(arguments))
        except ValidationError as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Os argumentos da ferramenta WhatsApp são inválidos."
            ) from exc

    def _require_connected(self) -> None:
        snapshot = self._snapshot()
        status = str(snapshot.get("status") or "disconnected")
        if status == "conflict":
            raise JarvisAgentError(
                "PROVIDER_CONFLICT",
                "O WhatsApp Baileys está em conflito com outra sessão.",
                status_code=409,
            )
        if status == "logged_out":
            raise JarvisAgentError(
                "PROVIDER_LOGGED_OUT",
                "O WhatsApp Baileys exige nova autenticação por QR.",
                status_code=409,
            )
        if status != "connected" or not snapshot.get("send_available"):
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED",
                "O WhatsApp Baileys não está conectado para esta ação.",
                status_code=409,
            )

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        args = self._parse(arguments)
        if tool_id in {
            "whatsapp.status",
            "whatsapp.search_contacts",
            "whatsapp.search_chats",
            "whatsapp.read_conversation",
            "whatsapp.summarize_conversation",
            "whatsapp.group_metadata",
            "whatsapp.privacy_read",
        }:
            return PreparedToolCall(args.model_dump(), {})
        self._require_connected()
        return self._commands.prepare(
            tool_id, args, channel=self._channel(), context=context
        )

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        channel = self._channel()
        if tool_id in {
            "whatsapp.status",
            "whatsapp.search_contacts",
            "whatsapp.search_chats",
            "whatsapp.read_conversation",
            "whatsapp.summarize_conversation",
            "whatsapp.group_metadata",
            "whatsapp.privacy_read",
        }:
            return self._execute_read(tool_id, self._parse(arguments), channel, context)
        self._require_connected()
        try:
            if tool_id == "whatsapp.react":
                result = channel.react_to_message(
                    str(arguments["message_ref"]),
                    str(arguments["reaction"]),
                    timeout=20.0,
                )
            elif tool_id == "whatsapp.mark_read":
                accepted = channel.mark_read(
                    str(arguments["jid"]), list(arguments.get("message_ids") or [])
                )
                if not accepted:
                    raise BridgeCommandError(
                        "As mensagens não estavam disponíveis para marcação."
                    )
                result = {"accepted": True}
            else:
                result = channel.execute_action_and_wait(dict(arguments), timeout=20.0)
            return AdapterResult(
                "completed",
                "Ação WhatsApp concluída.",
                scrub_provider_ids(result),
            )
        except BridgeCommandTimeout as exc:
            raise JarvisAgentError(
                "EXTERNAL_RESULT_UNKNOWN",
                (
                    "O WhatsApp não confirmou o resultado no prazo; "
                    "não haverá repetição automática."
                ),
                status_code=504,
            ) from exc
        except (BridgeCommandError, ValueError) as exc:
            raise JarvisAgentError(
                "EXTERNAL_RESULT_UNKNOWN",
                "O WhatsApp recusou ou não confirmou a ação.",
                status_code=502,
            ) from exc

    def _execute_read(
        self,
        tool_id: str,
        args: WhatsAppArguments,
        channel: Any,
        context: AdapterContext,
    ) -> AdapterResult:
        if tool_id == "whatsapp.status":
            return AdapterResult(
                "completed",
                "Estado WhatsApp consultado.",
                scrub_provider_ids(self._snapshot()),
            )
        if tool_id == "whatsapp.search_contacts":
            values = self._references.contacts(
                channel.search_contacts(args.query, min(args.limit, 100)),
                context.partition_key,
            )
            return AdapterResult(
                "completed", "Contatos WhatsApp encontrados.", {"contacts": values}
            )
        if tool_id == "whatsapp.search_chats":
            values = self._references.chats(
                channel.search_chats(args.query, min(args.limit, 100)),
                context.partition_key,
            )
            return AdapterResult(
                "completed", "Conversas WhatsApp encontradas.", {"chats": values}
            )
        if tool_id in {
            "whatsapp.read_conversation",
            "whatsapp.summarize_conversation",
            "whatsapp.group_metadata",
        }:
            return self._execute_conversation_read(tool_id, args, channel, context)
        self._require_connected()
        result = channel.execute_action_and_wait(
            {"type": "privacy", "operation": "read"}, timeout=10.0
        )
        return AdapterResult(
            "completed", "Privacidade WhatsApp consultada.", scrub_provider_ids(result)
        )

    def _execute_conversation_read(
        self,
        tool_id: str,
        args: WhatsAppArguments,
        channel: Any,
        context: AdapterContext,
    ) -> AdapterResult:
        target = self._references.resolve_chat(args.chat_ref, context.partition_key)
        jid = target["provider_value"]
        if tool_id == "whatsapp.read_conversation":
            messages = channel.list_messages(
                jid, query=args.query, limit=min(args.limit, 200)
            )
            return AdapterResult(
                "completed",
                "Conversa WhatsApp lida.",
                {"messages": public_messages(messages)},
            )
        if tool_id == "whatsapp.summarize_conversation":
            summary = channel.conversation_summary(jid, limit=min(args.limit, 200))
            return AdapterResult(
                "completed",
                "Contexto da conversa WhatsApp carregado.",
                {
                    "message_count": int(summary.get("message_count") or 0),
                    "first_message_at": int(summary.get("first_message_at") or 0),
                    "last_message_at": int(summary.get("last_message_at") or 0),
                    "messages": public_messages(summary.get("messages") or []),
                },
            )
        self._require_connected()
        result = channel.execute_action_and_wait(
            {"type": "group_metadata", "jid": jid}, timeout=10.0
        )
        return AdapterResult(
            "completed", "Metadados de grupo consultados.", scrub_provider_ids(result)
        )
