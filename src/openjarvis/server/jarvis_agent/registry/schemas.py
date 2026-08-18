"""Small JSON-schema builders shared by canonical tool definitions."""

from __future__ import annotations

from typing import Any


def object_schema(
    properties: dict[str, Any], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def string(
    description: str,
    *,
    min_length: int = 1,
    max_length: int = 4000,
    enum: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "string",
        "description": description,
        "minLength": min_length,
        "maxLength": max_length,
    }
    if enum:
        schema["enum"] = list(enum)
    return schema


def integer(description: str, *, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "minimum": minimum,
        "maximum": maximum,
    }


def boolean(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def string_array(
    description: str, *, max_items: int, item_max_length: int = 240
) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "maxItems": max_items,
        "items": {"type": "string", "minLength": 1, "maxLength": item_max_length},
    }
