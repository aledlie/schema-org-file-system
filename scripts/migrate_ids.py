#!/usr/bin/env python3
"""
Database migration script for ID generation improvements.

This script:
1. Adds new columns (canonical_id, source_ids, merged_into_id) to entity tables
2. Backfills canonical_id with deterministic UUIDs from names/paths
3. Creates the merge_events table

Safe to run multiple times (idempotent).

Usage:
    python scripts/migrate_ids.py --db-path results/file_organization.db
    python scripts/migrate_ids.py --dry-run  # Show what would be done
"""

import argparse
import sqlite3
import uuid
import sys
from pathlib import Path
from datetime import datetime


# Namespace UUIDs for deterministic ID generation (must match models.py)
NAMESPACES = {
    'file': uuid.UUID('f4e8a9c0-1234-5678-9abc-def012345678'),
    'category': uuid.UUID('c4e8a9c0-2345-6789-abcd-ef0123456789'),
    'company': uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),
    'person': uuid.UUID('d1e2a3b4-5678-9abc-def0-123456789012'),
    'location': uuid.UUID('e2e3a4b5-6789-abcd-ef01-234567890123'),
}


def generate_canonical_id(namespace: str, name: str) -> str:
    """Generate deterministic UUID v5 from name."""
    ns_uuid = NAMESPACES.get(namespace)
    if not ns_uuid:
        raise ValueError(f"Unknown namespace: {namespace}")
    return str(uuid.uuid5(ns_uuid, name.lower().strip()))


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cursor.fetchone() is not None


def add_column_if_not_exists(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
    dry_run: bool = False
) -> bool:
    """Add a column to a table if it doesn't exist.

    Note: SQLite doesn't support adding UNIQUE columns directly via ALTER TABLE.
    We add the column without UNIQUE constraint, then create a unique index.
    """
    if column_exists(conn, table, column):
        print(f"  Column {table}.{column} already exists")
        return False

    # Remove UNIQUE from column type (SQLite limitation)
    # We'll add a unique index separately
    base_type = column_type.replace(' UNIQUE', '').replace('UNIQUE ', '')

    sql = f"ALTER TABLE {table} ADD COLUMN {column} {base_type}"
    if dry_run:
        print(f"  [DRY RUN] Would execute: {sql}")
    else:
        conn.execute(sql)
        print(f"  Added column {table}.{column}")

    # Create unique index if UNIQUE was specified
    if 'UNIQUE' in column_type:
        index_name = f"uq_{table}_{column}"
        if dry_run:
            print(f"  [DRY RUN] Would create unique index: {index_name}")
        else:
            try:
                conn.execute(f"CREATE UNIQUE INDEX {index_name} ON {table}({column})")
                print(f"  Created unique index {index_name}")
            except sqlite3.OperationalError as e:
                if "already exists" in str(e):
                    print(f"  Unique index {index_name} already exists")
                else:
                    raise

    return True


def migrate_schema(conn: sqlite3.Connection, dry_run: bool = False):
    """Add new columns to existing tables."""
    print("\n=== Phase 1: Schema Migration ===\n")

    # Files table
    print("Migrating files table...")
    add_column_if_not_exists(conn, 'files', 'canonical_id', 'VARCHAR(100) UNIQUE', dry_run)
    add_column_if_not_exists(conn, 'files', 'source_ids', "JSON DEFAULT '[]'", dry_run)

    # Categories table
    print("Migrating categories table...")
    add_column_if_not_exists(conn, 'categories', 'canonical_id', 'VARCHAR(36) UNIQUE', dry_run)
    add_column_if_not_exists(conn, 'categories', 'source_ids', "JSON DEFAULT '[]'", dry_run)
    add_column_if_not_exists(conn, 'categories', 'merged_into_id', 'INTEGER REFERENCES categories(id)', dry_run)

    # Companies table
    print("Migrating companies table...")
    add_column_if_not_exists(conn, 'companies', 'canonical_id', 'VARCHAR(36) UNIQUE', dry_run)
    add_column_if_not_exists(conn, 'companies', 'source_ids', "JSON DEFAULT '[]'", dry_run)
    add_column_if_not_exists(conn, 'companies', 'merged_into_id', 'INTEGER REFERENCES companies(id)', dry_run)

    # People table
    print("Migrating people table...")
    add_column_if_not_exists(conn, 'people', 'canonical_id', 'VARCHAR(36) UNIQUE', dry_run)
    add_column_if_not_exists(conn, 'people', 'source_ids', "JSON DEFAULT '[]'", dry_run)
    add_column_if_not_exists(conn, 'people', 'merged_into_id', 'INTEGER REFERENCES people(id)', dry_run)

    # Locations table
    print("Migrating locations table...")
    add_column_if_not_exists(conn, 'locations', 'canonical_id', 'VARCHAR(36) UNIQUE', dry_run)
    add_column_if_not_exists(conn, 'locations', 'source_ids', "JSON DEFAULT '[]'", dry_run)
    add_column_if_not_exists(conn, 'locations', 'merged_into_id', 'INTEGER REFERENCES locations(id)', dry_run)

    # Create merge_events table
    print("Creating merge_events table...")
    if table_exists(conn, 'merge_events'):
        print("  Table merge_events already exists")
    else:
        sql = """
        CREATE TABLE merge_events (
            id VARCHAR(36) PRIMARY KEY,
            target_entity_type VARCHAR(20) NOT NULL,
            target_entity_id INTEGER NOT NULL,
            target_canonical_id VARCHAR(36),
            source_entity_ids JSON NOT NULL,
            source_canonical_ids JSON,
            merge_reason TEXT,
            confidence FLOAT DEFAULT 1.0,
            performed_by VARCHAR(100),
            performed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            jsonld JSON,
            is_rolled_back BOOLEAN DEFAULT FALSE,
            rolled_back_at DATETIME,
            rolled_back_by VARCHAR(100)
        )
        """
        if dry_run:
            print(f"  [DRY RUN] Would create merge_events table")
        else:
            conn.execute(sql)
            conn.execute("CREATE INDEX ix_merge_entity_type ON merge_events(target_entity_type)")
            conn.execute("CREATE INDEX ix_merge_performed_at ON merge_events(performed_at)")
            print("  Created merge_events table")

    if not dry_run:
        conn.commit()


def backfill_files(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Backfill canonical_id for files."""
    cursor = conn.execute(
        "SELECT id, original_path FROM files WHERE canonical_id IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        print("  No files need backfilling")
        return 0

    print(f"  Backfilling {len(rows)} files...")

    for file_id, original_path in rows:
        canonical_id = f"urn:sha256:{file_id}"

        if dry_run:
            print(f"    [DRY RUN] Would set {file_id[:16]}... -> {canonical_id[:30]}...")
        else:
            conn.execute(
                "UPDATE files SET canonical_id = ? WHERE id = ?",
                (canonical_id, file_id)
            )

    if not dry_run:
        conn.commit()

    return len(rows)


def backfill_categories(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Backfill canonical_id for categories."""
    cursor = conn.execute(
        "SELECT id, name FROM categories WHERE canonical_id IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        print("  No categories need backfilling")
        return 0

    print(f"  Backfilling {len(rows)} categories...")

    for cat_id, name in rows:
        canonical_id = generate_canonical_id('category', name)

        if dry_run:
            print(f"    [DRY RUN] Would set '{name}' -> {canonical_id}")
        else:
            conn.execute(
                "UPDATE categories SET canonical_id = ? WHERE id = ?",
                (canonical_id, cat_id)
            )

    if not dry_run:
        conn.commit()

    return len(rows)


def backfill_companies(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Backfill canonical_id for companies."""
    cursor = conn.execute(
        "SELECT id, name FROM companies WHERE canonical_id IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        print("  No companies need backfilling")
        return 0

    print(f"  Backfilling {len(rows)} companies...")

    for comp_id, name in rows:
        canonical_id = generate_canonical_id('company', name)

        if dry_run:
            print(f"    [DRY RUN] Would set '{name}' -> {canonical_id}")
        else:
            conn.execute(
                "UPDATE companies SET canonical_id = ? WHERE id = ?",
                (canonical_id, comp_id)
            )

    if not dry_run:
        conn.commit()

    return len(rows)


def backfill_people(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Backfill canonical_id for people."""
    cursor = conn.execute(
        "SELECT id, name FROM people WHERE canonical_id IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        print("  No people need backfilling")
        return 0

    print(f"  Backfilling {len(rows)} people...")

    for person_id, name in rows:
        canonical_id = generate_canonical_id('person', name)

        if dry_run:
            print(f"    [DRY RUN] Would set '{name}' -> {canonical_id}")
        else:
            conn.execute(
                "UPDATE people SET canonical_id = ? WHERE id = ?",
                (canonical_id, person_id)
            )

    if not dry_run:
        conn.commit()

    return len(rows)


def backfill_locations(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Backfill canonical_id for locations."""
    cursor = conn.execute(
        "SELECT id, name FROM locations WHERE canonical_id IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        print("  No locations need backfilling")
        return 0

    print(f"  Backfilling {len(rows)} locations...")

    for loc_id, name in rows:
        canonical_id = generate_canonical_id('location', name)

        if dry_run:
            print(f"    [DRY RUN] Would set '{name}' -> {canonical_id}")
        else:
            conn.execute(
                "UPDATE locations SET canonical_id = ? WHERE id = ?",
                (canonical_id, loc_id)
            )

    if not dry_run:
        conn.commit()

    return len(rows)


def backfill_data(conn: sqlite3.Connection, dry_run: bool = False):
    """Backfill canonical_id for all entity tables."""
    print("\n=== Phase 2: Data Backfill ===\n")

    total = 0

    print("Backfilling files...")
    total += backfill_files(conn, dry_run)

    print("Backfilling categories...")
    total += backfill_categories(conn, dry_run)

    print("Backfilling companies...")
    total += backfill_companies(conn, dry_run)

    print("Backfilling people...")
    total += backfill_people(conn, dry_run)

    print("Backfilling locations...")
    total += backfill_locations(conn, dry_run)

    return total


def create_indexes(conn: sqlite3.Connection, dry_run: bool = False):
    """Create indexes on new columns."""
    print("\n=== Phase 3: Create Indexes ===\n")

    indexes = [
        ("ix_files_canonical_id", "files", "canonical_id"),
        ("ix_categories_canonical_id", "categories", "canonical_id"),
        ("ix_companies_canonical_id", "companies", "canonical_id"),
        ("ix_people_canonical_id", "people", "canonical_id"),
        ("ix_locations_canonical_id", "locations", "canonical_id"),
    ]

    for index_name, table, column in indexes:
        # Check if index exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,)
        )
        if cursor.fetchone():
            print(f"  Index {index_name} already exists")
            continue

        sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"
        if dry_run:
            print(f"  [DRY RUN] Would create index: {index_name}")
        else:
            conn.execute(sql)
            print(f"  Created index {index_name}")

    if not dry_run:
        conn.commit()


def verify_migration(conn: sqlite3.Connection):
    """Verify the migration was successful."""
    print("\n=== Verification ===\n")

    # Check for NULL canonical_ids
    tables = ['files', 'categories', 'companies', 'people', 'locations']

    all_good = True
    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE canonical_id IS NULL")
        null_count = cursor.fetchone()[0]

        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        total_count = cursor.fetchone()[0]

        if null_count > 0:
            print(f"  WARNING: {table} has {null_count}/{total_count} records without canonical_id")
            all_good = False
        else:
            print(f"  OK: {table} - {total_count} records, all have canonical_id")

    # Check merge_events table
    if table_exists(conn, 'merge_events'):
        print("  OK: merge_events table exists")
    else:
        print("  WARNING: merge_events table missing")
        all_good = False

    return all_good


def main():
    parser = argparse.ArgumentParser(
        description="Migrate database for ID generation improvements"
    )
    parser.add_argument(
        '--db-path',
        default='results/file_organization.db',
        help='Path to SQLite database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"ID Generation Migration Script")
    print(f"==============================")
    print(f"Database: {db_path}")
    print(f"Dry run: {args.dry_run}")
    print(f"Started: {datetime.now().isoformat()}")

    conn = sqlite3.connect(str(db_path))

    try:
        # Phase 1: Schema changes
        migrate_schema(conn, args.dry_run)

        # Phase 2: Data backfill
        total_backfilled = backfill_data(conn, args.dry_run)

        # Phase 3: Indexes
        create_indexes(conn, args.dry_run)

        # Verification
        if not args.dry_run:
            success = verify_migration(conn)
        else:
            print("\n=== Dry Run Complete ===")
            print("Run without --dry-run to apply changes")
            success = True

        print(f"\n=== Summary ===")
        print(f"Records backfilled: {total_backfilled}")
        print(f"Status: {'SUCCESS' if success else 'WARNINGS - check output above'}")
        print(f"Completed: {datetime.now().isoformat()}")

    finally:
        conn.close()


if __name__ == '__main__':
    main()
