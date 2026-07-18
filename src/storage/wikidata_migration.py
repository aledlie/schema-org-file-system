"""Wikidata QID schema migration.

Adds the nullable ``wikidata_qid`` TEXT column to the ``companies`` table so
the nightly Wikidata enrichment (``scripts/enrich_wikidata.py``) can persist
confirmed QIDs back to the company row for use in JSON-LD ``sameAs`` output.

Fresh databases get the column automatically via ``Base.metadata.create_all``
(the column is declared in :mod:`src.storage.models`); this migration
back-fills the schema for databases created before the column existed.

Surfaced via ``organize-files migrate-wikidata``.
"""

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Union

try:
    from ..constants import (
        DEFAULT_DB_PATH,
        SEPARATOR_WIDTH_MEDIUM,
        SEPARATOR_WIDTH_SMALL,
    )
except ImportError:
    from constants import (  # type: ignore[no-redef]
        DEFAULT_DB_PATH,
        SEPARATOR_WIDTH_MEDIUM,
        SEPARATOR_WIDTH_SMALL,
    )

COMPANIES_TABLE = "companies"
WIKIDATA_QID_COLUMN = "wikidata_qid"
WIKIDATA_QID_COLUMN_TYPE = "TEXT"


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return column in {row[1] for row in cursor.fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def run_wikidata_migration(
    db_path: Union[str, Path] = DEFAULT_DB_PATH, dry_run: bool = False
) -> Dict[str, Any]:
    """Add ``companies.wikidata_qid`` to an existing SQLite database.

    Idempotent: the column is only added when missing.  Existing rows keep a
    NULL ``wikidata_qid`` until enriched by ``scripts/enrich_wikidata.py``.

    Args:
        db_path: Path to SQLite database.
        dry_run: If True, show what would be done without making changes.

    Returns:
        Migration statistics dict (``columns_added`` key).
    """
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    stats: Dict[str, int] = defaultdict(int)
    conn = sqlite3.connect(str(db_path))

    try:
        print("Phase 1: Schema Migration")
        print("-" * SEPARATOR_WIDTH_SMALL)

        if not _table_exists(conn, COMPANIES_TABLE):
            print(f"  Table {COMPANIES_TABLE!r} does not exist — nothing to migrate")
        elif not _column_exists(conn, COMPANIES_TABLE, WIKIDATA_QID_COLUMN):
            if dry_run:
                print(
                    f"  [DRY RUN] Would add {WIKIDATA_QID_COLUMN} "
                    f"to {COMPANIES_TABLE}"
                )
            else:
                conn.execute(
                    f"ALTER TABLE {COMPANIES_TABLE} "
                    f"ADD COLUMN {WIKIDATA_QID_COLUMN} {WIKIDATA_QID_COLUMN_TYPE}"
                )
                print(f"  Added {WIKIDATA_QID_COLUMN} to {COMPANIES_TABLE}")
                stats["columns_added"] += 1  # only on actual ALTER TABLE, not dry-run
        else:
            print(
                f"  {WIKIDATA_QID_COLUMN} already exists in {COMPANIES_TABLE}"
            )

        if not dry_run:
            conn.commit()

        print("\n" + "=" * SEPARATOR_WIDTH_SMALL)
        print("Migration Summary")
        print("=" * SEPARATOR_WIDTH_SMALL)
        print(f"  Columns added: {stats.get('columns_added', 0)}")
        if dry_run:
            print("\n  [DRY RUN] No changes were made")

    finally:
        conn.close()

    return dict(stats)


def run_wikidata_migration_with_banner(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    dry_run: bool = False,
) -> None:
    """Print migration banner, run migration, print completion line."""
    separator = "=" * SEPARATOR_WIDTH_MEDIUM
    print(f"\n{separator}")
    print("Running Wikidata QID Schema Migration")
    print(f"{separator}\n")
    run_wikidata_migration(db_path, dry_run=dry_run)
    if dry_run:
        print("\n[DRY RUN] No changes were made.")
    else:
        print(
            "\nMigration complete. companies.wikidata_qid is available "
            "for Wikidata QID persistence (run enrich-wikidata to populate)."
        )
