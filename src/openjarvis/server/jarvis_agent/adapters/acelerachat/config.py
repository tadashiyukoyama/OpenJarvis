"""Private environment configuration for the AceleraChat boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://atendimento.meugerenciador.pro/api/v1/openjarvis"


def _optional_positive_int(value: str) -> int | None:
    if not value.strip():
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("inbox id must be positive")
    return parsed


@dataclass(frozen=True, slots=True)
class AceleraChatConfig:
    base_url: str = DEFAULT_BASE_URL
    bearer_token: str = ""
    webhook_secret_current: str = ""
    webhook_secret_previous: str = ""
    email_inbox_id: int | None = None
    whatsapp_inbox_id: int | None = None
    timeout_seconds: float = 15.0
    max_response_bytes: int = 2 * 1024 * 1024
    error: str | None = None

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "AceleraChatConfig":
        values = os.environ if environment is None else environment
        base_url = values.get("ACELERACHAT_BASE_URL", DEFAULT_BASE_URL).strip()
        error: str | None = None
        try:
            email_inbox_id = _optional_positive_int(
                values.get("ACELERACHAT_EMAIL_INBOX_ID", "")
            )
            whatsapp_inbox_id = _optional_positive_int(
                values.get("ACELERACHAT_WHATSAPP_INBOX_ID", "")
            )
            cls._validate_base_url(base_url)
        except (TypeError, ValueError):
            email_inbox_id = None
            whatsapp_inbox_id = None
            error = "invalid_private_configuration"
        return cls(
            base_url=base_url.rstrip("/"),
            bearer_token=values.get("ACELERACHAT_BEARER_TOKEN", "").strip(),
            webhook_secret_current=values.get(
                "ACELERACHAT_WEBHOOK_SECRET_CURRENT", ""
            ).strip(),
            webhook_secret_previous=values.get(
                "ACELERACHAT_WEBHOOK_SECRET_PREVIOUS", ""
            ).strip(),
            email_inbox_id=email_inbox_id,
            whatsapp_inbox_id=whatsapp_inbox_id,
            error=error,
        )

    @staticmethod
    def _validate_base_url(value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("AceleraChat base URL must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("AceleraChat base URL contains forbidden components")

    @property
    def api_enabled(self) -> bool:
        return self.error is None and bool(self.bearer_token)

    @property
    def webhook_enabled(self) -> bool:
        return self.error is None and bool(self.webhook_secret_current)

    @property
    def unavailable_reason(self) -> str:
        if self.error:
            return self.error
        if not self.bearer_token:
            return "private_credentials_missing"
        return "provider_unavailable"
