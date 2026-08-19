"""Typed e-mail operations implemented by AceleraChat conversations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import Message
from openjarvis.server.jarvis_agent.adapters.acelerachat.presentation import (
    present_message,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    ExternalOperation,
    PreparedToolCall,
)
from openjarvis.server.jarvis_agent.domain.states import ActionState


class AceleraChatEmailTools:
    def __init__(
        self,
        client: AceleraChatClient,
        capabilities: AceleraChatCapabilities,
        references: AceleraChatReferences,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._references = references

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        if tool_id in {"email.search", "email.list_unread"}:
            payload = dict(arguments)
            preview = {"source": "AceleraChat e-mail", "operation": tool_id}
            return PreparedToolCall(payload, preview)
        reference_name = (
            "message_ref" if tool_id == "email.read_message" else "conversation_ref"
        )
        kind = "message" if reference_name == "message_ref" else "conversation"
        resolved = self._references.resolve(
            str(arguments[reference_name]),
            partition_key=context.partition_key,
            source="email",
            kind=kind,
        )
        conversation_id = resolved["conversation_id"] or resolved["resource_id"]
        payload: dict[str, Any] = {
            "inbox_id": resolved["inbox_id"],
            "conversation_id": conversation_id,
        }
        if tool_id == "email.read_message":
            payload["message_id"] = resolved["resource_id"]
        if tool_id == "email.read_conversation":
            payload["limit"] = int(arguments.get("limit", 25))
        if tool_id == "email.reply":
            payload.update(
                body=str(arguments["body"]).strip(),
                to=list(arguments.get("to") or []),
                cc=list(arguments.get("cc") or []),
                bcc=list(arguments.get("bcc") or []),
            )
            conversation = self._client.get_conversation(int(conversation_id))
            contact = (conversation.get("contact") or {}).get("name") or "conversa"
            preview = {
                "provider": "AceleraChat",
                "channel": "email",
                "target": contact,
                "body": payload["body"],
                "to": payload["to"],
                "cc": payload["cc"],
                "bcc": payload["bcc"],
                "risk": "resposta externa assíncrona",
            }
            return PreparedToolCall(payload, preview)
        return PreparedToolCall(payload, {"source": "AceleraChat e-mail"})

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        if tool_id == "email.search":
            return self._search(
                str(arguments["query"]),
                int(arguments.get("limit", 10)),
                context,
                inbox_id=self._optional_inbox_id(arguments),
                inbox_name=str(arguments.get("inbox_name") or ""),
            )
        if tool_id == "email.list_unread":
            return self._search(
                None,
                int(arguments.get("limit", 10)),
                context,
                unread=True,
                inbox_id=self._optional_inbox_id(arguments),
                inbox_name=str(arguments.get("inbox_name") or ""),
            )
        if tool_id in {"email.read_message", "email.read_conversation"}:
            return self._read(tool_id, arguments, context)
        if tool_id == "email.reply":
            return self._reply(arguments, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta de e-mail indisponível.")

    def _search(
        self,
        query: str | None,
        limit: int,
        context: AdapterContext,
        *,
        unread: bool | None = None,
        inbox_id: int | None = None,
        inbox_name: str = "",
    ) -> AdapterResult:
        inbox_id = self._inbox_id(force=False, expected=inbox_id, inbox_name=inbox_name)
        raw = self._client.search_messages(
            inbox_id=inbox_id, query=query, unread=unread, limit=min(limit, 25)
        )
        messages = self._messages(raw)
        values, references = self._present(messages, inbox_id, context)
        return AdapterResult(
            "completed",
            f"{len(values)} mensagem(ns) de e-mail encontrada(s).",
            {"messages": values, "untrusted_external_data": True},
            references,
        )

    def _read(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        inbox_id = self._inbox_id(force=False, expected=int(arguments["inbox_id"]))
        messages = self._messages(
            self._client.list_messages(
                int(arguments["conversation_id"]),
                min(int(arguments.get("limit", 100)), 100),
            )
        )
        if tool_id == "email.read_message":
            wanted = int(arguments["message_id"])
            messages = [message for message in messages if message.id == wanted]
            if not messages:
                raise JarvisAgentError(
                    "INVALID_REQUEST", "A mensagem não está mais disponível."
                )
        values, references = self._present(messages, inbox_id, context)
        return AdapterResult(
            "completed",
            f"{len(values)} mensagem(ns) lida(s).",
            {"messages": values, "untrusted_external_data": True},
            references,
        )

    def _reply(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        self._inbox_id(force=True, expected=int(arguments["inbox_id"]))
        message: dict[str, Any] = {"content": str(arguments["body"]), "private": False}
        for source, target in (
            ("to", "to_emails"),
            ("cc", "cc_emails"),
            ("bcc", "bcc_emails"),
        ):
            values = [
                str(value).strip()
                for value in arguments.get(source, [])
                if str(value).strip()
            ]
            if values:
                message[target] = ",".join(values)
        response = self._client.create_message(
            int(arguments["conversation_id"]),
            message,
            idempotency_key=f"jarvis:{context.request_id}",
        )
        return self._accepted(
            response,
            context,
            source="email",
            inbox_id=int(arguments["inbox_id"]),
        )

    def _accepted(
        self,
        response: Mapping[str, Any],
        context: AdapterContext,
        *,
        source: str,
        inbox_id: int,
    ) -> AdapterResult:
        result = response.get("result")
        data = response.get("data")
        if not isinstance(result, Mapping) or not isinstance(data, Mapping):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O aceite do AceleraChat é inválido."
            )
        if result.get("state") != "accepted":
            raise JarvisAgentError(
                "PROVIDER_UNAVAILABLE", "O AceleraChat recusou a mensagem."
            )
        try:
            message = Message.model_validate(data)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O aceite do AceleraChat retornou mensagem inválida.",
            ) from exc
        message_ref = self._references.create(
            partition_key=context.partition_key,
            source=source,
            kind="message",
            resource_id=message.id,
            inbox_id=inbox_id,
            conversation_id=message.conversation_id,
        )
        return AdapterResult(
            "accepted",
            "Mensagem aceita pelo AceleraChat; entrega aguardando confirmação.",
            {"message_ref": message_ref, "delivery": "pending"},
            {"message": message_ref},
            ActionState.ACCEPTED,
            ExternalOperation("acelerachat", "Message", str(message.id)),
        )

    def _inbox_id(
        self,
        *,
        force: bool,
        expected: int | None = None,
        inbox_name: str = "",
    ) -> int:
        snapshot = self._capabilities.select(
            "acelerachat_email",
            inbox_id=expected,
            inbox_name=inbox_name,
            force=force,
        )
        if snapshot.inbox is None or not (
            snapshot.inbox.connection.operational or snapshot.inbox.connection.connected
        ):
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED",
                "A caixa de e-mail do AceleraChat está indisponível.",
            )
        return snapshot.inbox.id

    @staticmethod
    def _optional_inbox_id(arguments: Mapping[str, Any]) -> int | None:
        value = arguments.get("inbox_id")
        return int(value) if value is not None else None

    @staticmethod
    def _messages(values: list[dict[str, Any]]) -> list[Message]:
        try:
            return [Message.model_validate(value) for value in values]
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou mensagens inválidas.",
            ) from exc

    def _present(
        self, messages: list[Message], inbox_id: int, context: AdapterContext
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        values: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        for index, message in enumerate(messages):
            value, created = present_message(
                message,
                source="email",
                inbox_id=inbox_id,
                partition_key=context.partition_key,
                references=self._references,
            )
            values.append(value)
            refs[f"message_{index + 1}"] = created["message"]
        return values, refs
