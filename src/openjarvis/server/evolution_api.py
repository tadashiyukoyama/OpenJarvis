"""Small, fail-closed client for the local Evolution API instance.

The browser never receives the Evolution API key.  This module is deliberately
limited to provider status/QR reads; outbound WhatsApp effects remain owned by
the Agent Host policy and its Evolution transport.  The default URL is
loopback-only so a bad deployment cannot exfiltrate the key to a public host.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote, urlencode, urlparse

import httpx

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_RESPONSE_BYTES = 512 * 1024
_CONNECTED_STATES = {"open", "connected", "online"}


@dataclass(frozen=True, slots=True)
class EvolutionApiConfig:
    base_url: str
    api_key: str
    instance_name: str
    webhook_secret: str
    timeout_seconds: float = 8.0
    provisioning_enabled: bool = False

    @classmethod
    def from_environment(cls) -> "EvolutionApiConfig":
        return cls(
            base_url=(
                os.environ.get("OPENJARVIS_EVOLUTION_API_URL")
                or os.environ.get("EVOLUTION_API_URL")
                or "http://127.0.0.1:8787"
            )
            .strip()
            .rstrip("/"),
            api_key=(
                os.environ.get("OPENJARVIS_EVOLUTION_API_KEY")
                or os.environ.get("AGENT_HOST_EVOLUTION_API_KEY")
                or ""
            ).strip(),
            instance_name=(
                os.environ.get("OPENJARVIS_EVOLUTION_INSTANCE_NAME")
                or os.environ.get("EVOLUTION_INSTANCE_NAME")
                or "jarvis"
            ).strip(),
            webhook_secret=os.environ.get(
                "OPENJARVIS_EVOLUTION_WEBHOOK_SECRET", ""
            ).strip(),
            timeout_seconds=_bounded_timeout(
                os.environ.get("OPENJARVIS_EVOLUTION_TIMEOUT_SECONDS", "8")
            ),
            provisioning_enabled=_truthy(
                os.environ.get("OPENJARVIS_EVOLUTION_PROVISIONING_ENABLED", "0")
            ),
        )

    def configuration_error(self) -> str | None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
            return "EVOLUTION_API_URL_MUST_BE_LOOPBACK_HTTP"
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return "EVOLUTION_API_URL_MUST_NOT_CONTAIN_CREDENTIALS"
        if not _INSTANCE_RE.fullmatch(self.instance_name):
            return "EVOLUTION_INSTANCE_NAME_INVALID"
        if len(self.api_key) < 32:
            return "EVOLUTION_API_KEY_UNCONFIGURED"
        return None


def _bounded_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 8.0
    return max(1.0, min(parsed, 30.0))


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_object(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _state_from(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "unknown"
    for key in ("state", "status", "connectionState"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    nested = _as_object(value.get("instance"))
    if nested is not None:
        return _state_from(nested)
    return "unknown"


class EvolutionApiClient:
    """Authenticated read-only provider client used by the OpenJarvis UI."""

    def __init__(
        self,
        config: EvolutionApiConfig | None = None,
        *,
        client: Any = httpx,
    ) -> None:
        self.config = config or EvolutionApiConfig.from_environment()
        self._client = client

    def _headers(self) -> dict[str, str]:
        # Evolution's CORS middleware accepts the configured local UI origin;
        # the API key itself never crosses into browser JavaScript.
        origin = os.environ.get(
            "OPENJARVIS_EVOLUTION_CORS_ORIGIN", "http://127.0.0.1:8765"
        ).strip()
        headers = {"Accept": "application/json", "apikey": self.config.api_key}
        if origin:
            headers["Origin"] = origin
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Mapping[str, Any] | list[Any] | None, str | None]:
        error = self.config.configuration_error()
        if error:
            return 0, None, error
        url = self.config.base_url + path
        if query:
            url += "?" + urlencode(dict(query))
        try:
            request_kwargs: dict[str, Any] = {
                "headers": self._headers(),
                "timeout": self.config.timeout_seconds,
                "follow_redirects": False,
            }
            if payload is not None:
                request_kwargs["json"] = dict(payload)
            response = self._client.request(
                method,
                url,
                **request_kwargs,
            )
            raw = response.content[: _MAX_RESPONSE_BYTES + 1]
            if len(raw) > _MAX_RESPONSE_BYTES:
                return int(response.status_code), None, "EVOLUTION_RESPONSE_TOO_LARGE"
            if 300 <= response.status_code < 400:
                return int(response.status_code), None, "EVOLUTION_REDIRECT_REJECTED"
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return int(response.status_code), None, "EVOLUTION_INVALID_JSON"
            if not isinstance(value, (Mapping, list)):
                return int(response.status_code), None, "EVOLUTION_INVALID_RESPONSE"
            return int(response.status_code), value, None
        except httpx.TimeoutException:
            return 0, None, "EVOLUTION_TIMEOUT"
        except httpx.RequestError:
            return 0, None, "EVOLUTION_UNAVAILABLE"
        except (OSError, ValueError):
            return 0, None, "EVOLUTION_UNAVAILABLE"

    def _matching_instance(
        self, value: Mapping[str, Any] | list[Any] | None
    ) -> Mapping[str, Any] | None:
        rows: list[Any]
        if isinstance(value, list):
            rows = value
        elif isinstance(value, Mapping):
            candidate = value.get("instances") or value.get("data") or value
            rows = candidate if isinstance(candidate, list) else [candidate]
        else:
            rows = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = row.get("instanceName") or row.get("name")
            if isinstance(name, str) and name == self.config.instance_name:
                return row
        return None

    def status(self) -> dict[str, Any]:
        config_error = self.config.configuration_error()
        result: dict[str, Any] = {
            "provider": "evolution_api",
            "configured": config_error is None,
            "instance_name": self.config.instance_name,
            "instance_exists": False,
            "state": "not_configured" if config_error else "unknown",
            "connected": False,
            "qr_available": False,
            "provisioning_enabled": self.config.provisioning_enabled,
            "external_effects": "agent_host_policy",
        }
        if config_error:
            result["error_code"] = config_error
            return result

        code, payload, error = self._request(
            "GET",
            "/instance/fetchInstances",
            query={"instanceName": self.config.instance_name},
        )
        instance = self._matching_instance(payload)
        if code < 200 or code >= 300 or instance is None:
            if error and code == 0:
                result["state"] = "unavailable"
                result["error_code"] = error
            else:
                result["state"] = "not_provisioned"
                if error:
                    result["error_code"] = error
            return result

        result["instance_exists"] = True
        state_code, state_payload, state_error = self._request(
            "GET",
            f"/instance/connectionState/{quote(self.config.instance_name, safe='')}",
        )
        state = _state_from(_as_object(state_payload))
        if state == "unknown":
            state = _state_from(instance)
        result["state"] = state
        result["connected"] = state in _CONNECTED_STATES
        if state_error and state_code == 0:
            result["error_code"] = state_error
        return result

    def qr(self) -> dict[str, Any]:
        result = self.status()
        if not result["configured"] or not result["instance_exists"]:
            return {**result, "available": False, "qr": None, "base64": None}
        code, payload, error = self._request(
            "GET", f"/instance/connect/{quote(self.config.instance_name, safe='')}"
        )
        obj = _as_object(payload)
        if code < 200 or code >= 300 or obj is None:
            return {
                **result,
                "available": False,
                "qr": None,
                "base64": None,
                "error_code": error or "EVOLUTION_QR_UNAVAILABLE",
            }
        qr = obj.get("code") or obj.get("qr") or obj.get("pairingCode")
        base64_image = obj.get("base64") or obj.get("qrcode")
        return {
            **result,
            "available": bool(qr or base64_image),
            "qr": qr if isinstance(qr, str) else None,
            "base64": base64_image if isinstance(base64_image, str) else None,
        }

    def provision(self) -> dict[str, Any]:
        """Create the configured provider instance only after explicit enablement."""

        result = self.status()
        if not result["configured"]:
            return {**result, "provisioned": False}
        if result["instance_exists"]:
            return {**result, "provisioned": False, "reason": "already_exists"}
        if not self.config.provisioning_enabled:
            return {
                **result,
                "provisioned": False,
                "error_code": "EVOLUTION_PROVISIONING_DISABLED",
            }
        code, payload, error = self._request(
            "POST",
            "/instance/create",
            payload={
                "instanceName": self.config.instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
            },
        )
        if code < 200 or code >= 300:
            return {
                **result,
                "provisioned": False,
                "error_code": error or "EVOLUTION_INSTANCE_CREATE_FAILED",
            }
        return {
            **result,
            "provisioned": True,
            "state": "provisioning",
            "instance_exists": True,
            "provider_result": "accepted" if isinstance(payload, Mapping) else None,
        }


__all__ = ["EvolutionApiClient", "EvolutionApiConfig"]
