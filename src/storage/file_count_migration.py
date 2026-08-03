#!/usr/bin/env python3
"""Drop the denormalized ``file_count`` caches; add the association indexes.

``Category``/``Company``/``Person``/``Location`` each stored a ``file_count``
that had to be incremented and decremented by hand at 12 call sites across three
modules. Any write that bypassed those sites left the number wrong, and the stale
value was *exported* as ``fileCount``/``mentionCount`` in the JSON-LD
(``models.build_*_jsonld``) and shown on the dashboard. On 2026-07-26 four
category counts had drifted, all from raw-SQL edge repairs — which no amount of
call-site discipline can cover.

``file_count`` is now derived: a correlated ``COUNT`` over the entity's
association table, evaluated by the database in the same SELECT that loads the
entity (``models._edge_count_property``). Nothing is cached, so nothing can
drift. This migration brings an existing database to that shape:

1. **Create the four association indexes.** ``ix_file_categories_category_id``
   and its siblings are declared in the model, but ``Base.metadata.create_all``
   skips tables that already exist — so databases created before those
   declarations never got them. The derived count needs them: with the index each
   count is a covering-index lookup; without it, a table scan per entity row.
2. **Drop the four ``file_count`` columns.** Left in place they would keep
   serving stale numbers to anything reading the tables directly (``sqlite3``,
   the D1 mirror), which is the failure mode being removed.

Fresh databases get the correct shape from ``create_all`` and need no migration.
Idempotent: existing indexes are left alone and absent columns are skipped, so
re-running is a no-op. Requires SQLite 3.35+ for ``ALTER TABLE DROP COLUMN``
(bundled Python 3.12+ ships 3.37+). Surfaced via
``organize-files migrate-file-counts``.
"""

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypedDict, Union

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

FILE_COUNT_COLUMN = "file_count"

# SQLite version that introduced ALTER TABLE ... DROP COLUMN.
MIN_SQLITE_DROP_COLUMN = (3, 35, 0)

# (entity table, association table, FK column). The index name matches the
# ``Index(...)`` declarations in models.py so create_all and this migration
# converge on the same schema.
EDGE_SOURCES: Tuple[Tuple[str, str, str], ...] = (
    ("categories", "file_categories", "category_id"),
    ("companies", "file_companies", "company_id"),
    ("people", "file_people", "person_id"),
    ("locations", "file_locations", "location_id"),
)


def index_name(assoc_table: str, fk_column: str) -> str:
    """``ix_file_categories_category_id`` — must match the model declaration."""
    return f"ix_{assoc_table}_{fk_column}"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index,))
    return cursor.fetchone() is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _supports_drop_column() -> bool:
    return sqlite3.sqlite_version_info >= MIN_SQLITE_DROP_COLUMN


class DriftEntry(TypedDict):
    """One cached count that disagreed with its edges at drop time."""
    table: str
    name: Optional[str]
    stored: int
    actual: int


class FileCountMigrationResult(TypedDict, total=False):
    """``run_file_count_migration()`` shape: the error short-circuit, or
    the stats keys (``drop_column_unsupported`` only on old SQLite)."""
    error: str
    indexes_created: int
    columns_dropped: int
    drifted_counts: int
    drop_column_unsupported: int
    drifted: List[DriftEntry]


def run_file_count_migration(
    db_path: Union[str, Path] = DEFAULT_DB_PATH, dry_run: bool = False
) -> FileCountMigrationResult:
    """Add the association indexes, then drop the ``file_count`` cache columns.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, show what would be done without making changes

    Returns:
        Migration statistics: ``indexes_created``, ``columns_dropped``,
        ``drifted_counts`` (how many cached values were already wrong at the
        moment they were discarded — reported for the record), and
        ``drop_column_unsupported`` when the SQLite build is too old.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    # Seeded so the returned keys are stable whether or not anything ran —
    # callers should not have to know which phases were no-ops.
    stats: Dict[str, int] = defaultdict(int)
    stats["indexes_created"] = 0
    stats["columns_dropped"] = 0
    stats["drifted_counts"] = 0
    drifted: List[DriftEntry] = []
    conn = sqlite3.connect(str(db_path))

    try:
        print("Phase 1: Association Indexes")
        print("-" * SEPARATOR_WIDTH_SMALL)
        for entity_table, assoc_table, fk_column in EDGE_SOURCES:
            if not _table_exists(conn, assoc_table):
                print(f"  {assoc_table}: table absent, skipping")
                continue
            index = index_name(assoc_table, fk_column)
            if _index_exists(conn, index):
                print(f"  {index}: already present")
                continue
            if dry_run:
                print(f"  [DRY RUN] Would create {index} on {assoc_table} ({fk_column})")
            else:
                conn.execute(f"CREATE INDEX {index} ON {assoc_table} ({fk_column})")
                print(f"  {index}: created")
            stats["indexes_created"] += 1

        print("\nPhase 2: Drift Census (report only — these values are about to go)")
        print("-" * SEPARATOR_WIDTH_SMALL)
        for entity_table, assoc_table, fk_column in EDGE_SOURCES:
            if not _table_exists(conn, entity_table) or not _has_column(
                conn, entity_table, FILE_COUNT_COLUMN
            ):
                continue
            rows = conn.execute(
                f"SELECT e.id, e.name, e.{FILE_COUNT_COLUMN}, "
                f"(SELECT COUNT(*) FROM {assoc_table} a WHERE a.{fk_column} = e.id) "
                f"FROM {entity_table} e"
            ).fetchall()
            for _entity_id, name, stored, actual in rows:
                if int(stored or 0) == int(actual or 0):
                    continue
                drifted.append(
                    {
                        "table": entity_table,
                        "name": name,
                        "stored": int(stored or 0),
                        "actual": int(actual or 0),
                    }
                )
        stats["drifted_counts"] = len(drifted)
        if drifted:
            print(f"  {len(drifted)} cached count(s) already disagreed with their edges:")
            for entry in drifted:
                print(
                    f"    {entry['table']:<12} {str(entry['name'])[:34]:<36} "
                    f"{entry['stored']} -> {entry['actual']}"
                )
            print("  The derived value is correct for all of them; no repair needed.")
        else:
            print("  Every cached count matched its edges at drop time")

        print(f"\nPhase 3: Drop {FILE_COUNT_COLUMN} Columns")
        print("-" * SEPARATOR_WIDTH_SMALL)
        if not _supports_drop_column():
            required = ".".join(str(part) for part in MIN_SQLITE_DROP_COLUMN)
            print(
                f"  SKIP: SQLite {sqlite3.sqlite_version} lacks ALTER TABLE DROP COLUMN "
                f"(needs {required}+)."
            )
            print("  The columns are now unmapped and unread, so they are harmless but stale.")
            stats["drop_column_unsupported"] = 1
        else:
            for entity_table, _assoc_table, _fk_column in EDGE_SOURCES:
                if not _table_exists(conn, entity_table):
                    print(f"  {entity_table}: table absent, skipping")
                    continue
                if not _has_column(conn, entity_table, FILE_COUNT_COLUMN):
                    print(f"  {entity_table}.{FILE_COUNT_COLUMN}: already dropped")
                    continue
                if dry_run:
                    print(f"  [DRY RUN] Would drop {entity_table}.{FILE_COUNT_COLUMN}")
                else:
                    conn.execute(f"ALTER TABLE {entity_table} DROP COLUMN {FILE_COUNT_COLUMN}")
                    print(f"  {entity_table}.{FILE_COUNT_COLUMN}: dropped")
                stats["columns_dropped"] += 1

        if not dry_run:
            conn.commit()

        print("\n" + "=" * SEPARATOR_WIDTH_SMALL)
        print("Migration Summary")
        print("=" * SEPARATOR_WIDTH_SMALL)
        print(f"  Indexes created:       {stats.get('indexes_created', 0)}")
        print(f"  Columns dropped:       {stats.get('columns_dropped', 0)}")
        print(f"  Drifted at drop time:  {stats.get('drifted_counts', 0)}")
        if dry_run:
            print("\n  [DRY RUN] No changes were made")

    finally:
        conn.close()

    result: FileCountMigrationResult = {
        "indexes_created": stats["indexes_created"],
        "columns_dropped": stats["columns_dropped"],
        "drifted_counts": stats["drifted_counts"],
        "drifted": drifted,
    }
    if "drop_column_unsupported" in stats:
        result["drop_column_unsupported"] = stats["drop_column_unsupported"]
    return result


def run_file_count_migration_with_banner(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    dry_run: bool = False,
) -> None:
    """Print the banner, run the file_count migration, print the closer.

    Single-sources the banner text for ``organize-files migrate-file-counts``,
    mirroring :func:`src.storage.category_migration.run_category_migration_with_banner`.

    :param db_path: Path to the SQLite database.
    :param dry_run: If True, passes ``dry_run=True`` and prints a dry-run notice.
    """
    separator = "=" * SEPARATOR_WIDTH_MEDIUM
    print(f"\n{separator}")
    print("Running file_count Cache Removal Migration")
    print(f"{separator}\n")
    run_file_count_migration(db_path, dry_run=dry_run)
    if dry_run:
        print("\n[DRY RUN] No changes were made.")
    else:
        print(
            "\nMigration complete. file_count is derived from association rows; "
            "there is no cached value left to drift."
        )
