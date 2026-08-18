"""Internal JSON and row codecs for the Jarvis SQLite repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any


def encode_json(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def decode_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else None


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
