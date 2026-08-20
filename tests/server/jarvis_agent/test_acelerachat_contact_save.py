from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from tests.server.jarvis_agent.test_acelerachat_adapter import (
    ApiDouble,
    _orchestrator,
)


def test_save_contact_creates_association_only_after_visual_approval(
    tmp_path: Path,
) -> None:
    api = ApiDouble(empty_contacts=True)
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-save-contact",
            tool_name="whatsapp_save_contact",
            arguments={
                "contact_name": "Novo contato",
                "phone_number": "+55 (11) 98888-7777",
            },
        )

        assert pending["state"] == "AWAITING_APPROVAL"
        assert pending["preview"]["target"] == "Novo contato"
        assert pending["preview"]["phone_number"] == "+5511988887777"
        assert "não envia mensagem" in pending["preview"]["risk"]
        assert api.posts == []

        completed = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert completed["state"] == "COMPLETED"
        assert completed["status"] == "completed"
        assert completed["result"]["data"]["message_sent"] is False
        assert completed["result"]["data"]["contact_preexisting"] is False
        assert completed["result"]["data"]["conversation_preexisting"] is False
        assert completed["result"]["references"]["contact"].startswith("war_")
        posted_paths = [
            request.url.path.rsplit("/openjarvis/", 1)[-1] for request in api.posts
        ]
        assert posted_paths == ["contacts", "conversations"]
        assert all(not path.endswith("/messages") for path in posted_paths)
        assert [request.headers["Idempotency-Key"] for request in api.posts] == [
            f"jarvis:{pending['action_id']}:contact-save",
            f"jarvis:{pending['action_id']}:contact-inbox",
        ]
    finally:
        orchestrator.close()


def test_save_contact_reuses_exact_phone_without_overwriting_or_sending(
    tmp_path: Path,
) -> None:
    api = ApiDouble(existing_phone_contact=True)
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-save-existing-contact",
            tool_name="whatsapp_save_contact",
            arguments={
                "contact_name": "Nome que não deve sobrescrever",
                "phone_number": "+5511988887777",
            },
        )
        completed = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert completed["result"]["data"]["contact_preexisting"] is True
        assert completed["result"]["data"]["conversation_preexisting"] is True
        assert completed["result"]["data"]["name"] == "Klaus Consultor"
        assert completed["result"]["data"]["message_sent"] is False
        assert api.posts == []
    finally:
        orchestrator.close()


def test_save_contact_requires_e164_before_creating_an_action(tmp_path: Path) -> None:
    api = ApiDouble(empty_contacts=True)
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        with pytest.raises(JarvisAgentError) as raised:
            orchestrator.propose(
                session_id=session["session_id"],
                generation=session["generation"],
                function_call_id="fc-save-invalid-contact",
                tool_name="whatsapp_save_contact",
                arguments={"contact_name": "Inválido", "phone_number": "1199999"},
            )

        assert raised.value.code == "INVALID_REQUEST"
        assert api.posts == []
    finally:
        orchestrator.close()


def test_split_voice_save_contact_reaches_one_approval_without_provider_post(
    tmp_path: Path,
) -> None:
    api = ApiDouble(empty_contacts=True)
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        orchestrator.commit_turn(
            session_id=session["session_id"],
            generation=session["generation"],
            turn_id="turn-save-contact-intent",
            transcript="Cadastre um novo contato do WhatsApp.",
        )
        orchestrator.commit_turn(
            session_id=session["session_id"],
            generation=session["generation"],
            turn_id="turn-save-contact-details",
            transcript="Nome Maria, número +5511988887777.",
        )

        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-split-save-contact",
            tool_name="whatsapp_save_contact",
            arguments={
                "contact_name": "Maria",
                "phone_number": "+5511988887777",
            },
            turn_id="turn-save-contact-details",
        )

        assert pending["state"] == "AWAITING_APPROVAL"
        assert api.posts == []
        assert (
            orchestrator.store.get_turn("turn-save-contact-intent")["transcript_text"]
            is None
        )
        assert (
            orchestrator.store.get_turn("turn-save-contact-details")["transcript_text"]
            is None
        )
    finally:
        orchestrator.close()


def test_save_contact_requires_exact_inbox_when_multiple_are_operational(
    tmp_path: Path,
) -> None:
    api = ApiDouble(multiple_whatsapp=True, empty_contacts=True)
    orchestrator = _orchestrator(tmp_path, api, whatsapp_inbox_id=None)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        with pytest.raises(JarvisAgentError) as raised:
            orchestrator.propose(
                session_id=session["session_id"],
                generation=session["generation"],
                function_call_id="fc-save-contact-no-inbox",
                tool_name="whatsapp_save_contact",
                arguments={"phone_number": "+5511988887777"},
            )
        assert raised.value.code == "INBOX_SELECTION_REQUIRED"

        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-save-contact-selected-inbox",
            tool_name="whatsapp_save_contact",
            arguments={
                "inbox_name": "Inbox 21",
                "contact_name": "Maria",
                "phone_number": "+5511988887777",
            },
        )
        assert pending["state"] == "AWAITING_APPROVAL"
        assert pending["preview"]["inbox"] == "Inbox 21"
        denied = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="deny",
        )
        assert denied["state"] == "DENIED"
        assert api.posts == []
    finally:
        orchestrator.close()
