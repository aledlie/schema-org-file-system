#!/usr/bin/env python3
"""Scoring signal-evidence schema migration.

Adds the nullable ``signal_evidence`` JSON column to the ``file_categories``
association table (UNIFIED_SCORING_PLAN §5.4) on an existing SQLite database.
Fresh databases get the column automatically via ``Base.metadata.create_all``
(the column is declared in :mod:`src.storage.models`); this migration
back-fills the schema for databases created before the column existed.

Follows the hand-rolled migration pattern of :mod:`src.storage.migration`
(PRAGMA-based column-existence checks, dry-run support, banner/summary
output). Surfaced via ``organize-files migrate-scoring``.
"""

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Union

try:
    from ..constants import (
        DEFAULT_DB_PATH,
        SEPARATOR_WIDTH_SMALL,
        SEPARATOR_WIDTH_MEDIUM,
    )
except ImportError:
    from constants import (  # type: ignore[no-redef]
        DEFAULT_DB_PATH,
        SEPARATOR_WIDTH_SMALL,
        SEPARATOR_WIDTH_MEDIUM,
    )

# Target schema change (kept as literals so the migration stays self-contained
# against raw sqlite3, matching run_migration in migration.py).
FILE_CATEGORIES_TABLE = "file_categories"
SIGNAL_EVIDENCE_COLUMN = "signal_evidence"
SIGNAL_EVIDENCE_COLUMN_TYPE = "JSON"


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def run_scoring_migration(
    db_path: Union[str, Path] = DEFAULT_DB_PATH, dry_run: bool = False
) -> Dict[str, Any]:
    """Add ``file_categories.signal_evidence`` to an existing SQLite database.

    Idempotent: the column is only added when missing. Existing rows keep a
    NULL ``signal_evidence`` (legacy runs persist NULL by design).

    Args:
        db_path: Path to SQLite database
        dry_run: If True, show what would be done without making changes

    Returns:
        Migration statistics (``columns_added`` counts the columns added, or
        that would be added under ``dry_run``)
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

        if not _table_exists(conn, FILE_CATEGORIES_TABLE):
            print(f"  Table {FILE_CATEGORIES_TABLE} does not exist, skipping")
        elif not _column_exists(conn, FILE_CATEGORIES_TABLE, SIGNAL_EVIDENCE_COLUMN):
            if dry_run:
                print(f"  [DRY RUN] Would add {SIGNAL_EVIDENCE_COLUMN} to {FILE_CATEGORIES_TABLE}")
            else:
                conn.execute(
                    f"ALTER TABLE {FILE_CATEGORIES_TABLE} "
                    f"ADD COLUMN {SIGNAL_EVIDENCE_COLUMN} {SIGNAL_EVIDENCE_COLUMN_TYPE}"
                )
                print(f"  Added {SIGNAL_EVIDENCE_COLUMN} to {FILE_CATEGORIES_TABLE}")
            stats["columns_added"] += 1
        else:
            print(f"  {SIGNAL_EVIDENCE_COLUMN} already exists in {FILE_CATEGORIES_TABLE}")

        if not dry_run:
            conn.commit()

        # Summary
        print("\n" + "=" * SEPARATOR_WIDTH_SMALL)
        print("Migration Summary")
        print("=" * SEPARATOR_WIDTH_SMALL)
        print(f"  Columns added: {stats.get('columns_added', 0)}")
        if dry_run:
            print("\n  [DRY RUN] No changes were made")

    finally:
        conn.close()

    return dict(stats)


def run_scoring_migration_with_banner(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    dry_run: bool = False,
) -> None:
    """Print the scoring migration banner, run the migration, then print the completion line.

    Single-sources the banner text for the ``organize-files migrate-scoring``
    subcommand, mirroring :func:`src.storage.migration.run_migration_with_banner`.

    :param db_path: Path to the SQLite database.
    :param dry_run: If True, passes ``dry_run=True`` to
        :func:`run_scoring_migration` and prints a dry-run notice instead of
        the completion message.
    """
    separator = "=" * SEPARATOR_WIDTH_MEDIUM
    print(f"\n{separator}")
    print("Running Scoring Signal-Evidence Migration")
    print(f"{separator}\n")
    run_scoring_migration(db_path, dry_run=dry_run)
    if dry_run:
        print("\n[DRY RUN] No changes were made.")
    else:
        print(
            "\nMigration complete. file_categories.signal_evidence is available "
            "for scoring-evidence persistence."
        )
