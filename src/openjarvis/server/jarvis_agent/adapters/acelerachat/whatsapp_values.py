"""Validated values shared by AceleraChat WhatsApp operations."""

from __future__ import annotations

import re

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError

_E164 = re.compile(r"^\+[1-9]\d{5,14}$")


def normalize_e164(value: object) -> str:
    """Return a formatting-tolerant, strictly validated E.164 number."""

    normalized = re.sub(r"[\s().-]", "", str(value or "").strip())
    if not _E164.fullmatch(normalized):
        raise JarvisAgentError(
            "INVALID_REQUEST", "Informe o telefone completo no formato E.164."
        )
    return normalized


__all__ = ["normalize_e164"]
