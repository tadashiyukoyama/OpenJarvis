"""Small strict validator for the JSON-Schema subset used by Jarvis tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


def validate_tool_arguments(
    arguments: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    _validate(arguments, schema, path="arguments")


def _invalid(path: str, reason: str) -> JarvisAgentError:
    return JarvisAgentError(
        "INVALID_REQUEST",
        f"Argumentos inválidos em {path}: {reason}.",
    )


def _validate(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    kind = schema.get("type")
    if kind == "object":
        _validate_object(value, schema, path=path)
        return
    if kind == "string":
        if not isinstance(value, str):
            raise _invalid(path, "texto esperado")
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise _invalid(path, "texto abaixo do limite")
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            raise _invalid(path, "texto excede o limite")
        options = schema.get("enum")
        if isinstance(options, Sequence) and value not in options:
            raise _invalid(path, "valor não permitido")
        return
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(path, "inteiro esperado")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int) and value < minimum:
            raise _invalid(path, "valor abaixo do mínimo")
        if isinstance(maximum, int) and value > maximum:
            raise _invalid(path, "valor acima do máximo")
        return
    if kind == "boolean":
        if not isinstance(value, bool):
            raise _invalid(path, "booleano esperado")
        return
    if kind == "array":
        if isinstance(value, (str, bytes)) or not isinstance(value, list):
            raise _invalid(path, "lista esperada")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            raise _invalid(path, "lista excede o limite")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate(item, item_schema, path=f"{path}[{index}]")
        return
    raise _invalid(path, "schema não suportado")


def _validate_object(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    if not isinstance(value, Mapping):
        raise _invalid(path, "objeto esperado")
    properties = schema.get("properties")
    fields = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required")
    required_fields = required if isinstance(required, Sequence) else ()
    missing = [str(name) for name in required_fields if name not in value]
    if missing:
        raise _invalid(path, f"campo obrigatório ausente ({', '.join(missing)})")
    if schema.get("additionalProperties") is False:
        extras = sorted(str(name) for name in value if name not in fields)
        if extras:
            raise _invalid(path, f"campo não permitido ({', '.join(extras)})")
    for name, item in value.items():
        field_schema = fields.get(name)
        if isinstance(field_schema, Mapping):
            _validate(item, field_schema, path=f"{path}.{name}")
