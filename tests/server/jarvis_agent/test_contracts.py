from __future__ import annotations

from pathlib import Path

from openjarvis.server.jarvis_agent.api.contract_export import write_contracts


def test_openapi_and_typescript_contracts_are_current() -> None:
    repository = Path(__file__).resolve().parents[3]

    assert write_contracts(repository, check=True) == []
