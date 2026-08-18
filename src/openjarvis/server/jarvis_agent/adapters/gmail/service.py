"""Gmail adapter selecting OAuth or IMAP according to real capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    max_results: int = Field(default=10, ge=1, le=25)
    message_ref: str = Field(default="", max_length=256)
    thread_ref: str = Field(default="", max_length=256)
    to: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=20_000)
    cc: str = Field(default="", max_length=2_000)


class GmailAdapter:
    adapter_id = "gmail"

    def __init__(
        self,
        references: ReferenceService,
        *,
        injected_connector: Callable[[], Any | None] | None = None,
        oauth_factory: Callable[[], Any] | None = None,
        imap_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._references = references
        self._injected_connector = injected_connector or (lambda: None)
        self._oauth_factory = oauth_factory or self._new_oauth
        self._imap_factory = imap_factory or self._new_imap

    @staticmethod
    def _new_oauth() -> Any:
        from openjarvis.connectors.gmail import GmailConnector

        return GmailConnector()

    @staticmethod
    def _new_imap() -> Any:
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector

        return GmailIMAPConnector()

    @staticmethod
    def _connected(connector: Any | None) -> bool:
        try:
            return bool(connector is not None and connector.is_connected())
        except Exception:
            return False

    def _connectors(self) -> tuple[Any, Any]:
        injected = self._injected_connector()
        oauth = injected if getattr(injected, "connector_id", "") == "gmail" else None
        imap = (
            injected if getattr(injected, "connector_id", "") == "gmail_imap" else None
        )
        return oauth or self._oauth_factory(), imap or self._imap_factory()

    def _selected(self, *, mutation: bool = False) -> Any:
        oauth, imap = self._connectors()
        if self._connected(oauth):
            return oauth
        if not mutation and self._connected(imap):
            return imap
        raise JarvisAgentError(
            "CAPABILITY_NOT_AVAILABLE" if mutation else "SOURCE_DISCONNECTED",
            (
                "Esta ação exige Gmail OAuth conectado."
                if mutation
                else "Nenhum Data Source Gmail está conectado."
            ),
            status_code=409,
        )

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        oauth, imap = self._connectors()
        oauth_connected = self._connected(oauth)
        imap_connected = self._connected(imap)
        oauth_caps = {
            "gmail.search",
            "gmail.read",
            "gmail.send",
            "gmail.archive",
            "gmail.trash",
        }
        if callable(getattr(oauth, "read_thread", None)):
            oauth_caps.add("gmail.thread")
        imap_caps = {"gmail.search", "gmail.read"}
        if callable(getattr(imap, "read_thread", None)):
            imap_caps.add("gmail.thread")
        active = (
            oauth_caps if oauth_connected else imap_caps if imap_connected else set()
        )
        return {
            "gmail": ProviderCapabilities(
                "gmail",
                "connected" if active else "disconnected",
                frozenset(active),
                bool(active),
                None if active else "source_disconnected",
            ),
            "gmail_oauth": ProviderCapabilities(
                "gmail_oauth",
                "connected" if oauth_connected else "disconnected",
                frozenset(oauth_caps if oauth_connected else ()),
                oauth_connected,
                None if oauth_connected else "oauth_disconnected",
            ),
            "gmail_imap": ProviderCapabilities(
                "gmail_imap",
                "connected" if imap_connected else "disconnected",
                frozenset(imap_caps if imap_connected else ()),
                imap_connected,
                None if imap_connected else "imap_disconnected",
            ),
        }

    @staticmethod
    def _parse(arguments: Mapping[str, Any]) -> _Arguments:
        try:
            return _Arguments.model_validate(dict(arguments))
        except ValidationError as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Os argumentos da ferramenta Gmail são inválidos."
            ) from exc

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        args = self._parse(arguments)
        payload = args.model_dump()
        if tool_id == "gmail.send":
            if not args.to.strip() or not args.body.strip():
                raise JarvisAgentError(
                    "INVALID_REQUEST", "Destinatário e corpo são obrigatórios."
                )
            self._selected(mutation=True)
            preview = {
                "destination": args.to.strip(),
                "subject": args.subject.strip(),
                "body": args.body.strip(),
                "cc": args.cc.strip(),
                "risk": "Envia um e-mail externo.",
            }
        elif tool_id in {"gmail.archive", "gmail.trash"}:
            self._selected(mutation=True)
            reference = self._references.resolve(
                args.message_ref,
                partition_key=context.partition_key,
                source="gmail",
                kind="message",
            )
            payload = {"message_id": reference["provider_value"]}
            preview = {
                "message_ref": args.message_ref,
                "subject": reference["metadata"].get("subject", ""),
                "operation": "archive" if tool_id.endswith("archive") else "trash",
                "risk": "Altera o estado de um e-mail externo.",
            }
        else:
            preview = {}
        return PreparedToolCall(payload, preview)

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        mutation = tool_id in {"gmail.send", "gmail.archive", "gmail.trash"}
        connector = self._selected(mutation=mutation)
        try:
            if mutation:
                return self._execute_mutation(tool_id, arguments, connector)
            return self._execute_read(tool_id, arguments, connector, context)
        except JarvisAgentError:
            raise
        except Exception as exc:
            raise JarvisAgentError(
                "EXTERNAL_RESULT_UNKNOWN" if mutation else "SOURCE_DISCONNECTED",
                "O Gmail não confirmou a operação.",
                status_code=502,
            ) from exc

    def _execute_read(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        connector: Any,
        context: AdapterContext,
    ) -> AdapterResult:
        args = self._parse(arguments)
        if tool_id in {"gmail.search", "gmail.list_unread"}:
            query = args.query if tool_id == "gmail.search" else "is:unread"
            summary = (
                "Busca Gmail concluída."
                if tool_id == "gmail.search"
                else "E-mails não lidos listados."
            )
            return self._messages_result(
                connector.search_messages(query, args.max_results), context, summary
            )
        if tool_id in {"gmail.read_message", "gmail.read_thread"}:
            is_thread = tool_id == "gmail.read_thread"
            reference = self._references.resolve(
                args.thread_ref if is_thread else args.message_ref,
                partition_key=context.partition_key,
                source="gmail",
                kind="thread" if is_thread else "message",
            )
            value = (
                connector.read_thread(reference["provider_value"])
                if is_thread
                else [connector.read_message(reference["provider_value"])]
            )
            return self._messages_result(
                value, context, "Conversa Gmail lida." if is_thread else "E-mail lido."
            )
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta Gmail desconhecida.")

    @staticmethod
    def _execute_mutation(
        tool_id: str, arguments: Mapping[str, Any], connector: Any
    ) -> AdapterResult:
        if tool_id == "gmail.send":
            sent = connector.send_message(
                to=str(arguments["to"]),
                subject=str(arguments.get("subject", "")),
                body=str(arguments["body"]),
                cc=str(arguments.get("cc", "")),
            )
            return AdapterResult("completed", "E-mail enviado.", {"sent": bool(sent)})
        if tool_id == "gmail.archive":
            connector.archive_message(str(arguments["message_id"]))
            return AdapterResult("completed", "E-mail arquivado.")
        if tool_id == "gmail.trash":
            connector.delete_message(str(arguments["message_id"]))
            return AdapterResult("completed", "E-mail movido para a lixeira.")
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta Gmail desconhecida.")

    def _messages_result(
        self,
        messages: list[dict[str, Any]],
        context: AdapterContext,
        summary: str,
    ) -> AdapterResult:
        public: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        for index, message in enumerate(messages[:25]):
            message_id = str(message.get("id") or message.get("message_id") or "")
            if not message_id:
                continue
            metadata = {
                "subject": str(message.get("subject", ""))[:998],
                "from": str(message.get("from", ""))[:320],
            }
            message_ref = self._references.create(
                partition_key=context.partition_key,
                source="gmail",
                kind="message",
                provider_value=message_id,
                metadata=metadata,
            )
            item = {
                key: value
                for key, value in message.items()
                if key not in {"id", "message_id", "thread_id"}
            }
            item["message_ref"] = message_ref
            thread_id = str(message.get("thread_id") or "")
            if thread_id:
                item["thread_ref"] = self._references.create(
                    partition_key=context.partition_key,
                    source="gmail",
                    kind="thread",
                    provider_value=thread_id,
                    metadata={"subject": metadata["subject"]},
                )
            public.append(item)
            refs[f"message_{index + 1}"] = message_ref
        return AdapterResult(
            "completed", summary, {"messages": public, "count": len(public)}, refs
        )
