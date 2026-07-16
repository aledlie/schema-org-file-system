#!/usr/bin/env python3
"""Integration tests for src/storage/scoring_migration.py.

Follows the tests/integration/test_storage_migration.py idiom: build a
pre-migration SQLite schema with raw sqlite3, run the migration, and assert
schema/data state via PRAGMA. Covers dry-run (no writes), the real run
(column added, data preserved), and idempotent re-runs.
"""

import sqlite3
from pathlib import Path

import pytest

from src.storage.scoring_migration import (
    FILE_CATEGORIES_TABLE,
    SIGNAL_EVIDENCE_COLUMN,
    run_scoring_migration,
)


def _columns(db_path: str, table: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cursor.fetchall()]
    finally:
        conn.close()


@pytest.fixture
def premigration_db(tmp_path: Path) -> str:
    """A database with the pre-signal_evidence file_categories schema."""
    db_path = tmp_path / "premigration.db"
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE files (
            id VARCHAR(64) PRIMARY KEY,
            filename VARCHAR(255),
            original_path TEXT
        )
        """)
    conn.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            file_count INTEGER DEFAULT 0
        )
        """)
    conn.execute("""
        CREATE TABLE file_categories (
            file_id VARCHAR(64) REFERENCES files(id),
            category_id INTEGER REFERENCES categories(id),
            confidence FLOAT DEFAULT 1.0,
            created_at DATETIME,
            PRIMARY KEY (file_id, category_id)
        )
        """)

    # Seed one association so data preservation can be asserted post-migration.
    conn.execute(
        "INSERT INTO files (id, filename, original_path) "
        "VALUES ('abc123', 'invoice.pdf', '/tmp/invoice.pdf')"
    )
    conn.execute("INSERT INTO categories (name) VALUES ('financial')")
    conn.execute(
        "INSERT INTO file_categories (file_id, category_id, confidence) VALUES ('abc123', 1, 0.9)"
    )
    conn.commit()
    conn.close()

    return str(db_path)


class TestDryRun:
    def test_dry_run_does_not_add_column(self, premigration_db: str) -> None:
        stats = run_scoring_migration(premigration_db, dry_run=True)

        assert stats.get("columns_added", 0) == 1  # would-add count
        assert SIGNAL_EVIDENCE_COLUMN not in _columns(premigration_db, FILE_CATEGORIES_TABLE)

    def test_dry_run_prints_notice(self, premigration_db: str, capsys) -> None:
        run_scoring_migration(premigration_db, dry_run=True)
        out = capsys.readouterr().out
        assert "[DRY RUN]" in out
        assert SIGNAL_EVIDENCE_COLUMN in out


class TestRealRun:
    def test_adds_signal_evidence_column(self, premigration_db: str) -> None:
        stats = run_scoring_migration(premigration_db, dry_run=False)

        assert stats.get("columns_added", 0) == 1
        assert SIGNAL_EVIDENCE_COLUMN in _columns(premigration_db, FILE_CATEGORIES_TABLE)

    def test_existing_rows_get_null_evidence(self, premigration_db: str) -> None:
        run_scoring_migration(premigration_db, dry_run=False)

        conn = sqlite3.connect(premigration_db)
        row = conn.execute(
            f"SELECT file_id, category_id, confidence, {SIGNAL_EVIDENCE_COLUMN} "
            f"FROM {FILE_CATEGORIES_TABLE}"
        ).fetchone()
        conn.close()

        assert row == ("abc123", 1, 0.9, None)

    def test_column_accepts_json_values_after_migration(self, premigration_db: str) -> None:
        run_scoring_migration(premigration_db, dry_run=False)

        conn = sqlite3.connect(premigration_db)
        conn.execute(
            f"UPDATE {FILE_CATEGORIES_TABLE} SET {SIGNAL_EVIDENCE_COLUMN} = ? "
            "WHERE file_id = 'abc123'",
            ('{"scorer": "shadow"}',),
        )
        conn.commit()
        stored = conn.execute(
            f"SELECT {SIGNAL_EVIDENCE_COLUMN} FROM {FILE_CATEGORIES_TABLE} "
            "WHERE file_id = 'abc123'"
        ).fetchone()[0]
        conn.close()

        assert stored == '{"scorer": "shadow"}'


class TestIdempotency:
    def test_second_run_is_noop(self, premigration_db: str) -> None:
        first = run_scoring_migration(premigration_db, dry_run=False)
        second = run_scoring_migration(premigration_db, dry_run=False)

        assert first.get("columns_added", 0) == 1
        assert second.get("columns_added", 0) == 0
        # Column present exactly once.
        columns = _columns(premigration_db, FILE_CATEGORIES_TABLE)
        assert columns.count(SIGNAL_EVIDENCE_COLUMN) == 1

    def test_dry_run_after_real_run_reports_existing(self, premigration_db: str, capsys) -> None:
        run_scoring_migration(premigration_db, dry_run=False)
        stats = run_scoring_migration(premigration_db, dry_run=True)

        assert stats.get("columns_added", 0) == 0
        assert "already exists" in capsys.readouterr().out


class TestEdgeCases:
    def test_nonexistent_db_returns_error(self, tmp_path: Path) -> None:
        result = run_scoring_migration(str(tmp_path / "missing.db"))
        assert "error" in result

    def test_missing_table_is_skipped(self, tmp_path: Path, capsys) -> None:
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE files (id VARCHAR(64) PRIMARY KEY)")
        conn.commit()
        conn.close()

        stats = run_scoring_migration(str(db_path), dry_run=False)

        assert stats.get("columns_added", 0) == 0
        assert "does not exist" in capsys.readouterr().out
