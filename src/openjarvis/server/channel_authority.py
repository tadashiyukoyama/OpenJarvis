"""Single-source channel authority policy for each OpenJarvis runtime mode."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

ACELERACHAT_MANAGED_CONNECTORS = frozenset(
    {"gmail", "gmail_imap", "whatsapp", "whatsapp_baileys"}
)


@dataclass(frozen=True, slots=True)
class ChannelAuthorityPolicy:
    core_mode: str
    blocked_connector_ids: frozenset[str]
    mount_legacy_customer_sources: bool

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "ChannelAuthorityPolicy":
        values = os.environ if environment is None else environment
        mode = values.get("OPENJARVIS_CORE_MODE", "local").strip().lower()
        if mode == "vps":
            return cls(mode, ACELERACHAT_MANAGED_CONNECTORS, False)
        return cls(mode or "local", frozenset(), True)

    def public_status(self) -> dict[str, object]:
        return {
            "core_mode": self.core_mode,
            "customer_channel_authority": (
                "acelerachat" if not self.mount_legacy_customer_sources else "local"
            ),
            "blocked_connector_ids": sorted(self.blocked_connector_ids),
        }


__all__ = ["ACELERACHAT_MANAGED_CONNECTORS", "ChannelAuthorityPolicy"]
