from __future__ import annotations

from openjarvis.server.jarvis_agent.registry.catalog import (
    JarvisToolCatalog,
    ProviderCapabilities,
)


def test_catalog_hides_unavailable_mutations_and_hackernews() -> None:
    catalog = JarvisToolCatalog()
    providers = {
        "jarvis_local": ProviderCapabilities(
            "jarvis_local", "available", frozenset({"jarvis.audit"}), True
        ),
        "acelerachat_email": ProviderCapabilities(
            "acelerachat_email",
            "configured_not_probed",
            frozenset({"email.search", "email.unread", "messages.read"}),
            False,
            operational=True,
        ),
        "acelerachat_whatsapp": ProviderCapabilities(
            "acelerachat_whatsapp",
            "connected",
            frozenset({"connection.inspect", "conversations.search"}),
            True,
        ),
        "codex_desktop": ProviderCapabilities(
            "codex_desktop", "unavailable", frozenset(), False
        ),
        "hackernews": ProviderCapabilities(
            "hackernews", "preserved", frozenset(), True
        ),
    }

    snapshot = catalog.snapshot(providers)
    names = {entry["name"] for entry in snapshot["manifest"]}

    assert "email_search_messages" in names
    assert "email_reply_conversation" not in names
    assert "whatsapp_send_text" not in names
    assert all("hacker" not in name for name in names)
    whatsapp = next(
        item for item in snapshot["providers"] if item["id"] == "acelerachat_whatsapp"
    )
    assert whatsapp["status"] == "connected"
    email = next(
        item for item in snapshot["providers"] if item["id"] == "acelerachat_email"
    )
    assert email["connected"] is False
    assert email["operational"] is True


def test_non_operational_provider_only_exposes_connection_inspection() -> None:
    catalog = JarvisToolCatalog()
    providers = {
        "jarvis_local": ProviderCapabilities(
            "jarvis_local", "available", frozenset({"jarvis.audit"}), True
        ),
        "acelerachat_email": ProviderCapabilities(
            "acelerachat_email",
            "disconnected",
            frozenset({"email.search"}),
            False,
            "source_disconnected",
            False,
        ),
        "acelerachat_whatsapp": ProviderCapabilities(
            "acelerachat_whatsapp",
            "disconnected",
            frozenset({"connection.inspect", "conversations.search"}),
            False,
            "source_disconnected",
            False,
        ),
    }

    snapshot = catalog.snapshot(providers)
    manifest = {entry["name"] for entry in snapshot["manifest"]}

    assert "email_search_messages" not in manifest
    assert "whatsapp_search_contacts" not in manifest
    assert "whatsapp_get_status" in manifest


def test_every_default_tool_has_policy_and_schema() -> None:
    catalog = JarvisToolCatalog()

    assert len(catalog.definitions) == len(
        {tool.tool_id for tool in catalog.definitions}
    )
    assert len(catalog.definitions) == len(
        {tool.gemini_name for tool in catalog.definitions}
    )
    for tool in catalog.definitions:
        assert tool.capability
        assert tool.adapter
        assert tool.timeout_seconds > 0
        assert tool.input_schema["type"] == "object"
        assert tool.requires_approval == (tool.effect.value != "READ")


def test_codex_manifest_uses_selected_session_target() -> None:
    definitions = {tool.gemini_name: tool for tool in JarvisToolCatalog().definitions}

    delegate = definitions["codex_delegate_task"].input_schema
    history = definitions["codex_read_recent_history"].input_schema

    assert set(delegate["properties"]) == {"command"}
    assert "project_cwd" not in delegate["properties"]
    assert "thread_id" not in delegate["properties"]
    assert set(history["properties"]) == {"limit"}


def test_release_gate_can_disable_every_mutation_without_hiding_reads() -> None:
    catalog = JarvisToolCatalog()
    capabilities = frozenset(tool.capability for tool in catalog.definitions)
    providers = {
        provider: ProviderCapabilities(provider, "available", capabilities, True)
        for provider in {tool.provider for tool in catalog.definitions}
    }

    snapshot = catalog.snapshot(providers, mutations_enabled=False)
    manifest = {entry["name"] for entry in snapshot["manifest"]}

    assert "email_search_messages" in manifest
    assert "codex_delegate_task" not in manifest
    blocked = next(tool for tool in snapshot["tools"] if tool["id"] == "codex.delegate")
    assert blocked["unavailable_reason"] == "external_mutations_disabled"
