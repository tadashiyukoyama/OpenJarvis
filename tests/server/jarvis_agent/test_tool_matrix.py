from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pytest

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.registry.catalog import (
    JarvisToolCatalog,
    ProviderCapabilities,
)
from openjarvis.server.jarvis_agent.registry.policy import JarvisToolPolicy


def _providers(catalog: JarvisToolCatalog) -> dict[str, ProviderCapabilities]:
    capabilities: dict[str, set[str]] = defaultdict(set)
    for tool in catalog.definitions:
        capabilities[tool.provider].add(tool.capability)
    return {
        provider: ProviderCapabilities(provider, "connected", frozenset(values), True)
        for provider, values in capabilities.items()
    }


def _schema_value(schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    if kind == "string":
        options = schema.get("enum") or []
        return options[0] if options else "x"
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    if kind == "object":
        properties = schema.get("properties") or {}
        return {
            name: _schema_value(properties[name])
            for name in schema.get("required") or []
        }
    raise AssertionError(f"unsupported schema in test: {schema}")


def test_canonical_catalog_has_the_exact_agent_surface() -> None:
    catalog = JarvisToolCatalog()
    identifiers = {tool.tool_id for tool in catalog.definitions}

    assert len(identifiers) == 24
    assert "whatsapp_action" not in identifiers
    assert not any("call" in identifier for identifier in identifiers)
    assert not any("hacker" in identifier for identifier in identifiers)
    assert all(
        re.fullmatch(r"[a-z][a-z0-9_]*", tool.gemini_name)
        for tool in catalog.definitions
    )


@pytest.mark.parametrize(
    "tool",
    JarvisToolCatalog().definitions,
    ids=lambda tool: tool.tool_id,
)
def test_every_tool_accepts_its_minimal_contract_and_rejects_extra_fields(tool) -> None:
    catalog = JarvisToolCatalog()
    providers = _providers(catalog)
    snapshot = catalog.snapshot(providers)
    policy = JarvisToolPolicy(catalog)
    arguments = _schema_value(dict(tool.input_schema))

    selected = policy.validate_call(
        name=tool.gemini_name,
        arguments=arguments,
        session_manifest_version=snapshot["version"],
        current_snapshot=snapshot,
    )
    assert selected.tool_id == tool.tool_id
    assert tool.input_schema.get("additionalProperties") is False

    with pytest.raises(JarvisAgentError) as error:
        policy.validate_call(
            name=tool.gemini_name,
            arguments={**arguments, "provider_internal_id": "forbidden"},
            session_manifest_version=snapshot["version"],
            current_snapshot=snapshot,
        )
    assert error.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "tool",
    JarvisToolCatalog().definitions,
    ids=lambda tool: tool.tool_id,
)
def test_unavailable_capability_is_never_announced_to_gemini(tool) -> None:
    catalog = JarvisToolCatalog()
    providers = _providers(catalog)
    current = providers[tool.provider]
    providers[tool.provider] = ProviderCapabilities(
        current.provider,
        "disconnected",
        frozenset(value for value in current.capabilities if value != tool.capability),
        False,
        "source_disconnected",
    )

    names = {entry["name"] for entry in catalog.snapshot(providers)["manifest"]}
    assert tool.gemini_name not in names


def test_model_schemas_never_accept_provider_identifiers() -> None:
    forbidden = {
        "jid",
        "remoteJid",
        "message_id",
        "thread_id",
        "project_cwd",
        "provider_value",
    }
    for tool in JarvisToolCatalog().definitions:
        properties = set(tool.input_schema.get("properties") or {})
        assert properties.isdisjoint(forbidden), tool.tool_id


@pytest.mark.parametrize(
    "tool",
    JarvisToolCatalog().definitions,
    ids=lambda tool: f"non-empty-{tool.tool_id}",
)
def test_declared_text_fields_reject_empty_values(tool) -> None:
    catalog = JarvisToolCatalog()
    providers = _providers(catalog)
    snapshot = catalog.snapshot(providers)
    policy = JarvisToolPolicy(catalog)
    base = _schema_value(dict(tool.input_schema))
    properties = tool.input_schema.get("properties") or {}

    for name, schema in properties.items():
        if schema.get("type") != "string" or not schema.get("minLength"):
            continue
        with pytest.raises(JarvisAgentError) as error:
            policy.validate_call(
                name=tool.gemini_name,
                arguments={**base, name: ""},
                session_manifest_version=snapshot["version"],
                current_snapshot=snapshot,
            )
        assert error.value.code == "INVALID_REQUEST"


def test_acelerachat_surface_does_not_advertise_unsupported_mutations() -> None:
    identifiers = {tool.tool_id for tool in JarvisToolCatalog().definitions}

    assert {
        "whatsapp.react",
        "whatsapp.reply",
        "whatsapp.send_media",
        "whatsapp.mark_read_provider",
    }.issubset(identifiers)
    assert not {
        "gmail.archive",
        "gmail.trash",
        "whatsapp.broadcast",
    }.intersection(identifiers)
