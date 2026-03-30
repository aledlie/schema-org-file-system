"""Unit tests for scripts/shared/ utilities."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path so `from shared.x import y` resolves.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.file_ops import resolve_collision
from shared.db_utils import db_connection, get_db_connection


# ---------------------------------------------------------------------------
# resolve_collision
# ---------------------------------------------------------------------------

class TestResolveCollision:
    def test_no_collision_returns_path_unchanged(self, temp_dir: Path) -> None:
        target = temp_dir / "image.png"
        assert resolve_collision(target) == target

    def test_single_collision_appends_1(self, temp_dir: Path) -> None:
        existing = temp_dir / "image.png"
        existing.touch()
        result = resolve_collision(temp_dir / "image.png")
        assert result == temp_dir / "image_1.png"

    def test_multiple_collisions_increments_counter(self, temp_dir: Path) -> None:
        (temp_dir / "image.png").touch()
        (temp_dir / "image_1.png").touch()
        result = resolve_collision(temp_dir / "image.png")
        assert result == temp_dir / "image_2.png"

    def test_preserves_extension(self, temp_dir: Path) -> None:
        (temp_dir / "doc.pdf").touch()
        result = resolve_collision(temp_dir / "doc.pdf")
        assert result.suffix == ".pdf"
        assert result.stem == "doc_1"


# ---------------------------------------------------------------------------
# get_db_connection
# ---------------------------------------------------------------------------

class TestGetDbConnection:
    def test_returns_sqlite_connection(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        try:
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()

    def test_row_factory_enabled_by_default(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()

    def test_row_factory_disabled(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path, row_factory=False)
        try:
            assert conn.row_factory is None
        finally:
            conn.close()

    def test_creates_database_file(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        conn.close()
        assert Path(temp_db_path).exists()


# ---------------------------------------------------------------------------
# db_connection
# ---------------------------------------------------------------------------

class TestDbConnection:
    def test_yields_connection(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_connection_closed_after_block(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            pass
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_write_requires_explicit_commit(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            conn.execute("CREATE TABLE t (v TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
            conn.commit()

        with db_connection(temp_db_path) as conn:
            row = conn.execute("SELECT v FROM t").fetchone()
            assert row["v"] == "hello"

    def test_no_auto_commit_on_exit(self, temp_db_path: str) -> None:
        """Verify that data written without commit is not persisted."""
        with db_connection(temp_db_path) as conn:
            conn.execute("CREATE TABLE t2 (v TEXT)")
            conn.commit()

        with db_connection(temp_db_path) as conn:
            conn.execute("INSERT INTO t2 VALUES ('uncommitted')")

        with db_connection(temp_db_path) as conn:
            rows = conn.execute("SELECT * FROM t2").fetchall()
            assert len(rows) == 0


# ---------------------------------------------------------------------------
# extract_ocr_text
# ---------------------------------------------------------------------------

class TestExtractOcrText:
    def test_returns_none_when_ocr_unavailable(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_text, OCR_AVAILABLE
        if OCR_AVAILABLE:
            pytest.skip("doctr is installed; skipping unavailability test")
        result = extract_ocr_text(sample_image_file)
        assert result is None

    def test_returns_none_or_str_for_valid_image(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_text
        result = extract_ocr_text(sample_image_file)
        assert result is None or isinstance(result, str)

    def test_truncates_to_max_chars(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_text, OCR_AVAILABLE
        if not OCR_AVAILABLE:
            pytest.skip("doctr not installed")
        result = extract_ocr_text(sample_image_file, max_chars=10)
        if result is not None:
            assert len(result) <= 13  # 10 chars + "..."


# ---------------------------------------------------------------------------
# extract_ocr_with_confidence
# ---------------------------------------------------------------------------

class TestExtractOcrWithConfidence:
    def test_returns_none_when_ocr_unavailable(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_with_confidence, OCR_AVAILABLE
        if OCR_AVAILABLE:
            pytest.skip("doctr is installed; skipping unavailability test")
        result = extract_ocr_with_confidence(sample_image_file)
        assert result is None

    def test_returns_ocr_result_or_none(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_with_confidence, OCRResult
        result = extract_ocr_with_confidence(sample_image_file)
        assert result is None or isinstance(result, OCRResult)

    def test_result_has_confidence_and_metadata(self, sample_image_file: Path) -> None:
        from shared.ocr_utils import extract_ocr_with_confidence, OCR_AVAILABLE
        if not OCR_AVAILABLE:
            pytest.skip("doctr not installed")
        result = extract_ocr_with_confidence(sample_image_file)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0
            assert result.word_count > 0
            assert isinstance(result.text, str)
            # language and orientation may be None for simple images
