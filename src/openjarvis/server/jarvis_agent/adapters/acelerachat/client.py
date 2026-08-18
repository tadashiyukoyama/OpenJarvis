"""No-retry HTTP client for the AceleraChat OpenJarvis API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

from openjarvis.server.jarvis_agent.adapters.acelerachat.config import (
    AceleraChatConfig,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


class AceleraChatClient:
    def __init__(
        self,
        config: AceleraChatConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=f"{config.base_url}/",
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {config.bearer_token}",
                "User-Agent": "OpenJarvis-AceleraChat/1.0",
            },
        )

    def close(self) -> None:
        self._client.close()

    def list_inboxes(self) -> list[dict[str, Any]]:
        return self._data_list(self._request("GET", "inboxes"))

    def inbox_health(self, inbox_id: int) -> dict[str, Any]:
        return self._data_object(self._request("GET", f"inboxes/{inbox_id}/health"))

    def search_contacts(self, query: str, limit: int) -> list[dict[str, Any]]:
        response = self._request("GET", "contacts", params={"q": query, "limit": limit})
        return self._data_list(response)

    def search_conversations(
        self,
        *,
        inbox_id: int,
        contact_id: int | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"inbox_id": inbox_id, "limit": limit}
        if contact_id is not None:
            params["contact_id"] = contact_id
        return self._data_list(self._request("GET", "conversations", params=params))

    def search_messages(
        self,
        *,
        inbox_id: int,
        query: str | None = None,
        unread: bool | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"inbox_id": inbox_id, "limit": limit}
        if query:
            params["q"] = query
        if unread is not None:
            params["unread"] = str(unread).lower()
        return self._data_list(self._request("GET", "messages", params=params))

    def list_messages(self, conversation_id: int, limit: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"conversations/{conversation_id}/messages",
            params={"limit": limit},
        )
        return self._data_list(response)

    def get_conversation(self, conversation_id: int) -> dict[str, Any]:
        return self._data_object(
            self._request("GET", f"conversations/{conversation_id}")
        )

    def create_message(
        self,
        conversation_id: int,
        message: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"conversations/{conversation_id}/messages",
            json_body={"message": dict(message)},
            idempotency_key=idempotency_key,
            mutation=True,
        )

    def mark_conversation_read(
        self, conversation_id: int, *, idempotency_key: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"conversations/{conversation_id}/read",
            json_body={},
            idempotency_key=idempotency_key,
            mutation=True,
        )

    def backfill(
        self, resource: str, *, cursor: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"resource": resource, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "backfill", params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        mutation: bool = False,
    ) -> dict[str, Any]:
        if not self.config.api_enabled:
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED",
                "A integração privada do AceleraChat não está configurada.",
                status_code=503,
            )
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        try:
            with self._client.stream(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    self._raise_http_error(response.status_code, mutation=mutation)
                content = self._bounded_content(response)
        except httpx.HTTPError as exc:
            code = "EXTERNAL_RESULT_UNKNOWN" if mutation else "PROVIDER_TIMEOUT"
            raise JarvisAgentError(
                code,
                "O AceleraChat não respondeu dentro do limite seguro.",
                status_code=504,
            ) from exc
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, ValueError) as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou uma resposta inválida.",
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou um contrato inesperado.",
                status_code=502,
            )
        return payload

    def _bounded_content(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) < 0 or int(declared) > self.config.max_response_bytes:
                    raise ValueError
            except ValueError as exc:
                raise JarvisAgentError(
                    "PROVIDER_RESPONSE_INVALID",
                    "A resposta do AceleraChat excedeu o limite seguro.",
                    status_code=502,
                ) from exc
        content = bytearray()
        for chunk in response.iter_bytes():
            if len(content) + len(chunk) > self.config.max_response_bytes:
                raise JarvisAgentError(
                    "PROVIDER_RESPONSE_INVALID",
                    "A resposta do AceleraChat excedeu o limite seguro.",
                    status_code=502,
                )
            content.extend(chunk)
        return bytes(content)

    @staticmethod
    def _raise_http_error(status: int, *, mutation: bool) -> None:
        if status == 401:
            code, message = (
                "PROVIDER_AUTH_FAILED",
                "A autenticação do AceleraChat falhou.",
            )
        elif status == 403:
            code, message = (
                "CAPABILITY_NOT_AVAILABLE",
                "O AceleraChat recusou esta capacidade.",
            )
        elif status == 404:
            code, message = (
                "INVALID_REQUEST",
                "O recurso solicitado não foi encontrado.",
            )
        elif status == 409:
            code, message = "PROVIDER_CONFLICT", "O AceleraChat informou um conflito."
        elif status == 429:
            code, message = (
                "PROVIDER_RATE_LIMITED",
                "O limite temporário do AceleraChat foi atingido.",
            )
        elif status >= 500 and mutation:
            code, message = (
                "EXTERNAL_RESULT_UNKNOWN",
                "O AceleraChat não confirmou se a operação foi aplicada.",
            )
        else:
            code, message = (
                "PROVIDER_UNAVAILABLE",
                "O AceleraChat está temporariamente indisponível.",
            )
        raise JarvisAgentError(
            code, message, status_code=502 if status >= 500 else status
        )

    @staticmethod
    def _data_list(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        values = payload.get("data")
        if not isinstance(values, list) or not all(
            isinstance(item, dict) for item in values
        ):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou uma coleção inválida.",
                status_code=502,
            )
        return values

    @staticmethod
    def _data_object(payload: Mapping[str, Any]) -> dict[str, Any]:
        value = payload.get("data")
        if not isinstance(value, dict):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou um recurso inválido.",
                status_code=502,
            )
        return value
