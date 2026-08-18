"""Single allowlist for the local MCP relay's Agent Core HTTP surface."""

from __future__ import annotations

import re

_SEGMENT = r"[A-Za-z0-9_-]{1,128}"
_ALLOWED = (
    ("GET", re.compile(r"^/v1/jarvis/agent/catalog$")),
    ("POST", re.compile(r"^/v1/jarvis/agent/sessions$")),
    ("POST", re.compile(rf"^/v1/jarvis/agent/sessions/{_SEGMENT}/proposals$")),
    ("POST", re.compile(rf"^/v1/jarvis/agent/sessions/{_SEGMENT}/close$")),
    ("GET", re.compile(rf"^/v1/jarvis/agent/actions/{_SEGMENT}$")),
)


def is_mcp_relay_request_allowed(method: str, path: str) -> bool:
    normalized_method = method.upper()
    for allowed_method, pattern in _ALLOWED:
        if normalized_method == allowed_method and pattern.fullmatch(path):
            return True
    return False


__all__ = ["is_mcp_relay_request_allowed"]
