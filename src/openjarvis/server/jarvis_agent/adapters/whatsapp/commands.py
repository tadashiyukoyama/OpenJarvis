"""Exact WhatsApp command preparation kept separate from execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.whatsapp.arguments import (
    WhatsAppArguments,
)
from openjarvis.server.jarvis_agent.adapters.whatsapp.references import (
    WhatsAppReferences,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import PreparedToolCall


class WhatsAppCommandBuilder:
    def __init__(self, references: WhatsAppReferences) -> None:
        self._references = references

    def prepare(
        self,
        tool_id: str,
        args: WhatsAppArguments,
        *,
        channel: Any,
        context: AdapterContext,
    ) -> PreparedToolCall:
        if tool_id in {"whatsapp.send_text", "whatsapp.send_media", "whatsapp.poll"}:
            target = self._references.resolve_destination(
                channel=channel,
                partition_key=context.partition_key,
                contact_name=args.contact_name,
                chat_ref=args.chat_ref,
            )
            return self._destination_command(tool_id, args, target)
        if tool_id in {"whatsapp.reply", "whatsapp.react"}:
            return self._message_command(tool_id, args, channel)
        if tool_id == "whatsapp.mark_read":
            return self._mark_read(args, channel, context)
        if tool_id in {"whatsapp.archive", "whatsapp.pin", "whatsapp.mute"}:
            return self._chat_modify(tool_id, args, context)
        if tool_id == "whatsapp.group_create":
            return self._group_create(args, channel, context)
        if tool_id == "whatsapp.group_subject":
            return self._group_subject(args, context)
        if tool_id == "whatsapp.privacy_update":
            return self._privacy_update(args)
        if tool_id == "whatsapp.profile_status":
            return self._profile_status(args)
        if tool_id == "whatsapp.broadcast":
            return self._broadcast(args, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp desconhecida.")

    @staticmethod
    def _destination_command(
        tool_id: str, args: WhatsAppArguments, target: Mapping[str, Any]
    ) -> PreparedToolCall:
        if tool_id == "whatsapp.send_text":
            return WhatsAppCommandBuilder._send_text(args, target)
        if tool_id == "whatsapp.send_media":
            return WhatsAppCommandBuilder._send_media(args, target)
        return WhatsAppCommandBuilder._poll(args, target)

    @staticmethod
    def _send_text(
        args: WhatsAppArguments, target: Mapping[str, Any]
    ) -> PreparedToolCall:
        if not args.text.strip():
            raise JarvisAgentError("INVALID_REQUEST", "A mensagem não pode ser vazia.")
        command = {
            "type": "send",
            "kind": "text",
            "jid": target["provider_value"],
            "text": args.text.strip(),
        }
        return PreparedToolCall(
            command,
            {
                "destination": target["metadata"].get("display_name", ""),
                "text": args.text.strip(),
                "risk": "Envia conteúdo externo pelo WhatsApp.",
            },
        )

    @staticmethod
    def _send_media(
        args: WhatsAppArguments, target: Mapping[str, Any]
    ) -> PreparedToolCall:
        if not args.url.startswith("https://") or args.media_type not in {
            "image",
            "video",
            "audio",
            "document",
        }:
            raise JarvisAgentError(
                "INVALID_REQUEST", "A mídia exige tipo válido e URL HTTPS."
            )
        command = {
            "type": "send",
            "kind": "media",
            "jid": target["provider_value"],
            "mediaType": args.media_type,
            "url": args.url,
            "caption": args.caption,
            "mimetype": args.mimetype,
            "fileName": args.file_name,
        }
        preview = {
            "destination": target["metadata"].get("display_name", ""),
            "media_type": args.media_type,
            "url": args.url,
            "caption": args.caption,
            "risk": "Envia conteúdo externo pelo WhatsApp.",
        }
        return PreparedToolCall(command, preview)

    @staticmethod
    def _poll(args: WhatsAppArguments, target: Mapping[str, Any]) -> PreparedToolCall:
        if len(args.options) < 2 or not args.question.strip():
            raise JarvisAgentError(
                "INVALID_REQUEST", "A enquete exige pergunta e duas opções."
            )
        command = {
            "type": "send",
            "kind": "poll",
            "jid": target["provider_value"],
            "text": args.question.strip(),
            "values": args.options,
            "selectableCount": args.selectable_count,
        }
        preview = {
            "destination": target["metadata"].get("display_name", ""),
            "question": args.question.strip(),
            "options": args.options,
            "risk": "Envia conteúdo externo pelo WhatsApp.",
        }
        return PreparedToolCall(command, preview)

    @staticmethod
    def _message_command(
        tool_id: str, args: WhatsAppArguments, channel: Any
    ) -> PreparedToolCall:
        try:
            target = channel.resolve_message_reference(args.message_ref)
        except ValueError as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST", str(exc), status_code=409
            ) from exc
        if tool_id == "whatsapp.react":
            if not args.reaction.strip():
                raise JarvisAgentError("INVALID_REQUEST", "A reação é obrigatória.")
            command = {
                "message_ref": args.message_ref,
                "reaction": args.reaction.strip(),
            }
            preview = {
                "operation": "reaction",
                "reaction": args.reaction.strip(),
                "message_preview": str(target.get("text") or "")[:160],
                "risk": "Envia uma reação externa pelo WhatsApp.",
            }
            return PreparedToolCall(command, preview)
        if not args.text.strip():
            raise JarvisAgentError("INVALID_REQUEST", "A resposta não pode ser vazia.")
        command = {
            "type": "send",
            "kind": "reply",
            "jid": target["jid"],
            "text": args.text.strip(),
            "messageId": target["message_id"],
            "participant": target.get("participant", ""),
            "fromMe": bool(target.get("from_me")),
            "quotedText": str(target.get("text") or "")[:4000],
        }
        preview = {
            "operation": "reply",
            "message_preview": str(target.get("text") or "")[:160],
            "text": args.text.strip(),
            "risk": "Envia uma resposta externa pelo WhatsApp.",
        }
        return PreparedToolCall(command, preview)

    def _mark_read(
        self, args: WhatsAppArguments, channel: Any, context: AdapterContext
    ) -> PreparedToolCall:
        target = self._references.resolve_chat(args.chat_ref, context.partition_key)
        message_ids = []
        for reference in args.message_refs:
            try:
                message = channel.resolve_message_reference(reference)
            except ValueError as exc:
                raise JarvisAgentError(
                    "INVALID_REQUEST", str(exc), status_code=409
                ) from exc
            if message["jid"] != target["provider_value"]:
                raise JarvisAgentError(
                    "INVALID_REQUEST", "A mensagem não pertence à conversa aprovada."
                )
            message_ids.append(message["message_id"])
        return PreparedToolCall(
            {"jid": target["provider_value"], "message_ids": message_ids},
            {
                "operation": "mark_read",
                "conversation": target["metadata"].get("display_name", ""),
                "message_count": len(message_ids),
                "risk": "Altera o estado de leitura no WhatsApp.",
            },
        )

    def _chat_modify(
        self, tool_id: str, args: WhatsAppArguments, context: AdapterContext
    ) -> PreparedToolCall:
        target = self._references.resolve_chat(args.chat_ref, context.partition_key)
        operation = tool_id.rsplit(".", 1)[-1]
        return PreparedToolCall(
            {
                "type": "chat_modify",
                "operation": operation,
                "jid": target["provider_value"],
                "enabled": args.enabled,
            },
            {
                "operation": operation,
                "conversation": target["metadata"].get("display_name", ""),
                "enabled": args.enabled,
                "risk": "Altera a organização de uma conversa WhatsApp.",
            },
        )

    def _group_subject(
        self, args: WhatsAppArguments, context: AdapterContext
    ) -> PreparedToolCall:
        target = self._references.resolve_chat(args.chat_ref, context.partition_key)
        if not args.subject.strip():
            raise JarvisAgentError("INVALID_REQUEST", "O novo assunto é obrigatório.")
        return PreparedToolCall(
            {
                "type": "group_subject",
                "jid": target["provider_value"],
                "subject": args.subject.strip(),
            },
            {
                "operation": "group_subject",
                "group": target["metadata"].get("display_name", ""),
                "subject": args.subject.strip(),
                "risk": "Altera o assunto de um grupo WhatsApp.",
            },
        )

    @staticmethod
    def _privacy_update(args: WhatsAppArguments) -> PreparedToolCall:
        if not args.setting.strip() or not args.value.strip():
            raise JarvisAgentError(
                "INVALID_REQUEST", "Configuração e valor são obrigatórios."
            )
        return PreparedToolCall(
            {
                "type": "privacy",
                "operation": "update",
                "setting": args.setting.strip(),
                "value": args.value.strip(),
            },
            {
                "operation": "privacy_update",
                "setting": args.setting.strip(),
                "value": args.value.strip(),
                "risk": "Altera uma configuração de privacidade WhatsApp.",
            },
        )

    @staticmethod
    def _profile_status(args: WhatsAppArguments) -> PreparedToolCall:
        if not args.text.strip():
            raise JarvisAgentError("INVALID_REQUEST", "O recado não pode ser vazio.")
        return PreparedToolCall(
            {"type": "profile_status", "text": args.text.strip()},
            {
                "operation": "profile_status",
                "text": args.text.strip(),
                "risk": "Altera o recado público do perfil WhatsApp.",
            },
        )

    def _group_create(
        self, args: WhatsAppArguments, channel: Any, context: AdapterContext
    ) -> PreparedToolCall:
        if not args.subject.strip() or not args.contact_names:
            raise JarvisAgentError(
                "INVALID_REQUEST", "O grupo exige assunto e participantes."
            )
        participants = []
        names = []
        for name in args.contact_names:
            target = self._references.resolve_destination(
                channel=channel,
                partition_key=context.partition_key,
                contact_name=name,
                chat_ref="",
            )
            participants.append(target["provider_value"])
            names.append(target["metadata"].get("display_name", name))
        return PreparedToolCall(
            {
                "type": "group_create",
                "subject": args.subject.strip(),
                "participants": participants,
            },
            {
                "operation": "group_create",
                "subject": args.subject.strip(),
                "participants": names,
                "risk": "Cria um grupo externo no WhatsApp.",
            },
        )

    def _broadcast(
        self, args: WhatsAppArguments, context: AdapterContext
    ) -> PreparedToolCall:
        if not args.text.strip():
            raise JarvisAgentError("INVALID_REQUEST", "O status não pode ser vazio.")
        audiences = [
            self._references.resolve_chat(reference, context.partition_key)[
                "provider_value"
            ]
            for reference in args.audience_refs
        ]
        return PreparedToolCall(
            {
                "type": "send",
                "kind": "text",
                "jid": "status@broadcast",
                "text": args.text.strip(),
                "statusJids": audiences,
            },
            {
                "operation": "broadcast",
                "text": args.text.strip(),
                "audience_count": len(audiences),
                "risk": "Publica conteúdo em status/broadcast WhatsApp.",
            },
        )
