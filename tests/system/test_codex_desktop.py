"""Tests for the constrained Codex Desktop URI dispatcher."""

from __future__ import annotations

import pytest

from openjarvis.integrations.codex_desktop import (
    codex_thread_uri,
    open_codex_thread_in_desktop,
)


@pytest.mark.parametrize(
    "thread_id",
    ["", "../settings", "thread:other", "thread/other", "a" * 129],
)
def test_codex_thread_uri_rejects_unsafe_identifiers(thread_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid Codex thread identifier"):
        codex_thread_uri(thread_id)


def test_codex_desktop_remount_uses_only_documented_routes() -> None:
    opened: list[str] = []
    delays: list[float] = []

    uri = open_codex_thread_in_desktop(
        "thread-a",
        opener=opened.append,
        sleeper=delays.append,
    )

    assert uri == "codex://threads/thread-a"
    assert opened == ["codex://settings", "codex://threads/thread-a"]
    assert delays == [0.75]
