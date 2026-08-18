"""Bounded request-body readers for unauthenticated provider callbacks."""

from __future__ import annotations

from fastapi import Request

ACELERACHAT_WEBHOOK_BODY_LIMIT = 1024 * 1024


async def read_bounded_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if declared_size < 0 or declared_size > limit:
            raise ValueError("request body too large")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise ValueError("request body too large")
        body.extend(chunk)
    return bytes(body)
