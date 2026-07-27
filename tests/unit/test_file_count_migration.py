"""Tests for the file_count cache-removal migration.

Covers both halves: creating the association indexes the derived count needs
(declared in the model but never created on pre-existing databases, because
``create_all`` skips tables that already exist), and dropping the stale
``file_count`` columns.
"""

import sqlite3
from pathlib import Path

import pytest

from src.storage.file_count_migration import (
    EDGE_SOURCES,
    FILE_COUNT_COLUMN,
    index_name,
    run_file_count_migration,
)


def _legacy_db(path: Path) -> str:
    """A database in the pre-migration shape: cache columns, no assoc indexes."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE files (id TEXT PRIMARY KEY);
        CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT, file_count INTEGER);
        CREATE TABLE companies  (id INTEGER PRIMARY KEY, name TEXT, file_count INTEGER);
        CREATE TABLE people     (id INTEGER PRIMARY KEY, name TEXT, file_count INTEGER);
        CREATE TABLE locations  (id INTEGER PRIMARY KEY, name TEXT, file_count INTEGER);
        CREATE TABLE file_categories (file_id TEXT, category_id INTEGER);
        CREATE TABLE file_companies  (file_id TEXT, company_id INTEGER);
        CREATE TABLE file_people     (file_id TEXT, person_id INTEGER);
        CREATE TABLE file_locations  (file_id TEXT, location_id INTEGER);

        INSERT INTO files VALUES ('f1'), ('f2');
        INSERT INTO categories VALUES (1, 'clients', 2), (2, 'orphan', 4);
        INSERT INTO file_categories VALUES ('f1', 1), ('f2', 1);
        """)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def legacy_db(tmp_path: Path) -> str:
    return _legacy_db(tmp_path / "legacy.db")


def _columns(db_path: str, table: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _indexes(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()


class TestFileCountMigration:
    def test_creates_the_four_association_indexes(self, legacy_db: str) -> None:
        assert not any(
            index_name(assoc, fk) in _indexes(legacy_db) for _e, assoc, fk in EDGE_SOURCES
        )

        stats = run_file_count_migration(legacy_db)

        assert stats["indexes_created"] == 4
        for _entity, assoc, fk in EDGE_SOURCES:
            assert index_name(assoc, fk) in _indexes(legacy_db)

    def test_drops_the_cache_columns(self, legacy_db: str) -> None:
        stats = run_file_count_migration(legacy_db)

        assert stats["columns_dropped"] == 4
        for entity_table, _assoc, _fk in EDGE_SOURCES:
            assert FILE_COUNT_COLUMN not in _columns(legacy_db, entity_table)

    def test_reports_counts_that_had_already_drifted(self, legacy_db: str) -> None:
        """The 'orphan' row stores 4 with zero edges — recorded, then discarded."""
        stats = run_file_count_migration(legacy_db)

        assert stats["drifted_counts"] == 1
        entry = stats["drifted"][0]
        assert (entry["table"], entry["name"], entry["stored"], entry["actual"]) == (
            "categories",
            "orphan",
            4,
            0,
        )

    def test_dry_run_changes_nothing(self, legacy_db: str) -> None:
        stats = run_file_count_migration(legacy_db, dry_run=True)

        assert stats["indexes_created"] == 4
        assert stats["columns_dropped"] == 4
        assert FILE_COUNT_COLUMN in _columns(legacy_db, "categories")
        assert not any(
            index_name(assoc, fk) in _indexes(legacy_db) for _e, assoc, fk in EDGE_SOURCES
        )

    def test_is_idempotent(self, legacy_db: str) -> None:
        run_file_count_migration(legacy_db)

        second = run_file_count_migration(legacy_db)

        assert second["indexes_created"] == 0
        assert second["columns_dropped"] == 0
        assert second["drifted_counts"] == 0

    def test_preserves_the_edges_the_count_derives_from(self, legacy_db: str) -> None:
        run_file_count_migration(legacy_db)

        conn = sqlite3.connect(legacy_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM file_categories").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 2
        finally:
            conn.close()

    def test_missing_database_reports_error(self, tmp_path: Path) -> None:
        stats = run_file_count_migration(str(tmp_path / "nope.db"))

        assert stats == {"error": "Database not found"}

    def test_tolerates_a_partially_migrated_database(self, tmp_path: Path) -> None:
        """One index already present, one column already dropped."""
        db_path = _legacy_db(tmp_path / "partial.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE INDEX ix_file_people_person_id ON file_people (person_id)")
        conn.execute(f"ALTER TABLE locations DROP COLUMN {FILE_COUNT_COLUMN}")
        conn.commit()
        conn.close()

        stats = run_file_count_migration(db_path)

        assert stats["indexes_created"] == 3
        assert stats["columns_dropped"] == 3
        for entity_table, _assoc, _fk in EDGE_SOURCES:
            assert FILE_COUNT_COLUMN not in _columns(db_path, entity_table)
