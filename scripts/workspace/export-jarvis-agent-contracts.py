"""Export the canonical Jarvis Agent OpenAPI and TypeScript contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from openjarvis.server.jarvis_agent.api.contract_export import write_contracts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    changed = write_contracts(repository, check=args.check)
    if args.check and changed:
        for path in changed:
            print(f"outdated: {path.relative_to(repository)}")
        return 1
    for path in changed:
        print(f"generated: {path.relative_to(repository)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
