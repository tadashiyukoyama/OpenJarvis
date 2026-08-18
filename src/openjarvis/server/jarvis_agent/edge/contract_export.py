"""Deterministic JSON Schema export for Edge protocol version 1.0."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame
from openjarvis.server.jarvis_agent.edge.payloads import CLIENT_PAYLOADS, CORE_PAYLOADS


def schema_bundle(
    payloads: Mapping[str, type[Any]], *, direction: str
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"OpenJarvis Edge 1.0 {direction} frames",
        "schema_version": "1.0",
        "direction": direction,
        "envelope": EdgeFrame.model_json_schema(),
        "payloads": {
            frame_type: model.model_json_schema()
            for frame_type, model in sorted(payloads.items())
        },
    }


def export_edge_contracts(root: Path) -> tuple[Path, Path]:
    target = root / "contracts" / "edge" / "v1"
    target.mkdir(parents=True, exist_ok=True)
    outputs = (
        (
            target / "client-frames.schema.json",
            schema_bundle(CLIENT_PAYLOADS, direction="client-to-core"),
        ),
        (
            target / "core-frames.schema.json",
            schema_bundle(CORE_PAYLOADS, direction="core-to-client"),
        ),
    )
    for path, payload in outputs:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return outputs[0][0], outputs[1][0]


def main() -> None:
    export_edge_contracts(Path(__file__).resolve().parents[5])


if __name__ == "__main__":
    main()


__all__ = ["export_edge_contracts", "schema_bundle"]
