#!/usr/bin/env python3
"""Category identity migration: ``full_path`` replaces ``name`` as the key.

``categories.name`` used to carry a UNIQUE index while the taxonomy reuses leaf
names across parents (``other`` under 15 categories, ``records`` under 3, plus
``events``/``insurance``/``photos``/``clients``/``audio``/``web``/
``meeting_notes``). Only the first claimant of a leaf name could exist; every
later ``(category, subcategory)`` sharing it hit an ``IntegrityError`` that
``GraphStore.get_or_create_category`` swallowed into ``None``, so
``add_file_to_category`` created no edge and the file persisted **with no
category at all** — 26% of rows on the 2026-07-26 audit.

This migration swaps the indexes to match the fixed model
(:mod:`src.storage.models`): ``name`` becomes a plain index, ``full_path``
becomes UNIQUE. It also realigns ``canonical_id`` with
``Category.generate_canonical_id(full_path)`` for any row whose id was derived
from the bare name, and reports (without changing) files left with no category
edge — repair those with ``organize-files reconcile --backfill-categories``.

Fresh databases get the correct indexes from ``Base.metadata.create_all``.
Follows the hand-rolled migration pattern of :mod:`src.storage.migration`
(dry-run support, banner/summary output). Surfaced via
``organize-files migrate-category-identity``.
"""

import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

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

CATEGORIES_TABLE = "categories"
NAME_INDEX = "ix_categories_name"
FULL_PATH_INDEX = "ix_categories_full_path"

# Namespace UUID for category canonical ids — must match
# ``src.storage.models.NAMESPACES["category"]`` (kept literal so the migration
# stays self-contained against raw sqlite3, as run_migration does).
CATEGORY_NAMESPACE = uuid.UUID("c4e8a9c0-2345-6789-abcd-ef0123456789")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def _index_sql(conn: sqlite3.Connection, index: str) -> str:
    """The CREATE statement for an index, or '' when it does not exist."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index,)
    ).fetchone()
    return (row[0] or "") if row else ""


def _is_unique(conn: sqlite3.Connection, index: str) -> bool:
    return "UNIQUE" in _index_sql(conn, index).upper()


def canonical_id_for(full_path: str) -> str:
    """UUID v5 from ``full_path`` — mirrors ``Category.generate_canonical_id``."""
    return str(uuid.uuid5(CATEGORY_NAMESPACE, full_path.lower().strip()))


def _duplicate_full_paths(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    """(full_path, count) for paths appearing more than once — blocks UNIQUE."""
    return [
        (row[0], row[1])
        for row in conn.execute(
            f"SELECT full_path, COUNT(*) FROM {CATEGORIES_TABLE} "
            "WHERE full_path IS NOT NULL GROUP BY full_path HAVING COUNT(*) > 1"
        )
    ]


def run_category_migration(
    db_path: Union[str, Path] = DEFAULT_DB_PATH, dry_run: bool = False
) -> Dict[str, Any]:
    """Make ``categories.full_path`` the unique identity; drop UNIQUE on ``name``.

    Idempotent: indexes are only rebuilt when they do not already match the
    target shape, and canonical ids are only rewritten when they differ from
    ``canonical_id_for(full_path)``. Aborts the index swap (leaving the database
    untouched) if duplicate ``full_path`` values exist, since UNIQUE could not
    be enforced — the duplicates are reported for manual merge.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, show what would be done without making changes

    Returns:
        Migration statistics: ``indexes_rebuilt``, ``canonical_ids_realigned``,
        ``duplicate_full_paths``, ``files_without_category``.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    stats: Dict[str, int] = defaultdict(int)
    conn = sqlite3.connect(str(db_path))

    try:
        print("Phase 1: Index Identity Swap")
        print("-" * SEPARATOR_WIDTH_SMALL)

        if not _table_exists(conn, CATEGORIES_TABLE):
            print(f"  Table {CATEGORIES_TABLE} does not exist, skipping")
            return dict(stats)

        duplicates = _duplicate_full_paths(conn)
        stats["duplicate_full_paths"] = len(duplicates)
        if duplicates:
            print("  ABORT: duplicate full_path values block a UNIQUE index:")
            for full_path, count in duplicates:
                print(f"    {full_path!r} x{count}")
            print("  Merge these rows, then re-run.")
            return dict(stats)

        name_unique = _is_unique(conn, NAME_INDEX)
        path_unique = _is_unique(conn, FULL_PATH_INDEX)

        if not name_unique and path_unique:
            print("  Indexes already match the target shape (name plain, full_path UNIQUE)")
        else:
            if dry_run:
                if name_unique:
                    print(f"  [DRY RUN] Would drop UNIQUE {NAME_INDEX}, recreate as plain index")
                if not path_unique:
                    print(f"  [DRY RUN] Would recreate {FULL_PATH_INDEX} as UNIQUE")
            else:
                if name_unique:
                    conn.execute(f"DROP INDEX IF EXISTS {NAME_INDEX}")
                    conn.execute(f"CREATE INDEX {NAME_INDEX} ON {CATEGORIES_TABLE} (name)")
                    print(f"  {NAME_INDEX}: UNIQUE -> plain index")
                if not path_unique:
                    conn.execute(f"DROP INDEX IF EXISTS {FULL_PATH_INDEX}")
                    conn.execute(
                        f"CREATE UNIQUE INDEX {FULL_PATH_INDEX} "
                        f"ON {CATEGORIES_TABLE} (full_path)"
                    )
                    print(f"  {FULL_PATH_INDEX}: plain -> UNIQUE index")
            stats["indexes_rebuilt"] += 1

        print("\nPhase 2: Canonical ID Realignment (uuid5 over full_path)")
        print("-" * SEPARATOR_WIDTH_SMALL)
        rows = conn.execute(
            f"SELECT id, full_path, canonical_id FROM {CATEGORIES_TABLE} "
            "WHERE full_path IS NOT NULL"
        ).fetchall()
        for cat_id, full_path, canonical_id in rows:
            expected = canonical_id_for(full_path)
            if canonical_id == expected:
                continue
            if dry_run:
                print(f"  [DRY RUN] Would realign {full_path!r}: {canonical_id} -> {expected}")
            else:
                conn.execute(
                    f"UPDATE {CATEGORIES_TABLE} SET canonical_id=? WHERE id=?",
                    (expected, cat_id),
                )
                print(f"  Realigned {full_path!r} -> {expected}")
            stats["canonical_ids_realigned"] += 1
        if not stats.get("canonical_ids_realigned"):
            print("  All canonical ids already derived from full_path")

        print("\nPhase 3: Orphaned File Rows (report only)")
        print("-" * SEPARATOR_WIDTH_SMALL)
        orphaned = conn.execute(
            "SELECT COUNT(*) FROM files f LEFT JOIN file_categories fc "
            "ON fc.file_id = f.id WHERE fc.file_id IS NULL"
        ).fetchone()[0]
        stats["files_without_category"] = orphaned
        if orphaned:
            print(f"  {orphaned} file row(s) have no category edge (dropped by the old bug).")
            print("  Repair with: organize-files reconcile --backfill-categories --apply")
            print(
                "  (A plain `organize-files content` re-run cannot: a correctly-placed "
                "file short-circuits at already_organized before persistence.)"
            )
        else:
            print("  Every file row has at least one category edge")

        if not dry_run:
            conn.commit()

        print("\n" + "=" * SEPARATOR_WIDTH_SMALL)
        print("Migration Summary")
        print("=" * SEPARATOR_WIDTH_SMALL)
        print(f"  Index sets rebuilt:      {stats.get('indexes_rebuilt', 0)}")
        print(f"  Canonical ids realigned: {stats.get('canonical_ids_realigned', 0)}")
        print(f"  Files without category:  {stats.get('files_without_category', 0)}")
        if dry_run:
            print("\n  [DRY RUN] No changes were made")

    finally:
        conn.close()

    return dict(stats)


def run_category_migration_with_banner(
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    dry_run: bool = False,
) -> None:
    """Print the banner, run the category-identity migration, print the closer.

    Single-sources the banner text for ``organize-files migrate-category-identity``,
    mirroring :func:`src.storage.migration.run_migration_with_banner`.

    :param db_path: Path to the SQLite database.
    :param dry_run: If True, passes ``dry_run=True`` and prints a dry-run notice.
    """
    separator = "=" * SEPARATOR_WIDTH_MEDIUM
    print(f"\n{separator}")
    print("Running Category Identity Migration (full_path)")
    print(f"{separator}\n")
    run_category_migration(db_path, dry_run=dry_run)
    if dry_run:
        print("\n[DRY RUN] No changes were made.")
    else:
        print(
            "\nMigration complete. categories.full_path is the unique identity; "
            "repeated leaf names no longer drop category edges."
        )
