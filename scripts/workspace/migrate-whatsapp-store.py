"""Create a verified, non-destructive WhatsApp SQLite snapshot on managed disk."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from openjarvis.channels.whatsapp.store_schema import initialize_schema

TABLES = (
    "whatsapp_contacts",
    "whatsapp_chats",
    "whatsapp_messages",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {result!r}")


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in TABLES
    }


def managed_d_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if os.name == "nt" and resolved.drive.upper() != "F:":
        raise RuntimeError(f"Managed target must be on disk F: {resolved}")
    return resolved


def migrate(source: Path, target: Path, manifest: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    target = managed_d_path(target)
    manifest = managed_d_path(manifest)
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found: {source}")
    if target.exists():
        raise FileExistsError(f"Target already exists; refusing overwrite: {target}")
    if manifest.exists():
        raise FileExistsError(
            f"Manifest already exists; refusing overwrite: {manifest}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.migrating-{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(f"Temporary target already exists: {temporary}")

    try:
        with (
            closing(
                sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
            ) as origin,
            closing(sqlite3.connect(temporary)) as snapshot,
        ):
            origin.backup(snapshot)
            integrity(snapshot)
            before = counts(snapshot)
        snapshot_sha256 = sha256(temporary)

        with closing(sqlite3.connect(temporary)) as migrated:
            migrated.row_factory = sqlite3.Row
            initialize_schema(migrated)
            integrity(migrated)
            after = counts(migrated)
        if before != after:
            raise RuntimeError(
                f"Row counts changed during schema migration: {before!r} -> {after!r}"
            )
        migrated_sha256 = sha256(temporary)
        temporary.replace(target)

        record: dict[str, object] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "source_preserved": True,
            "target": str(target),
            "snapshot_sha256_before_schema_migration": snapshot_sha256,
            "target_sha256": migrated_sha256,
            "row_counts_before": before,
            "row_counts_after": after,
            "integrity_check": "ok",
        }
        manifest.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return record
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        record = migrate(args.source, args.target, args.manifest)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
