"""Unit tests for src/pipeline FileProcessor and BatchProcessor."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.pipeline import BatchProcessor, FileProcessor


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_file_processor(
    base_path: Path,
    cost_calculator: Any = None,
    graph_store: Any = None,
) -> FileProcessor:
    """Create a FileProcessor with mocked optional dependencies."""
    return FileProcessor(
        base_path=base_path,
        dry_run=True,
        db_path=None,
        cost_calculator=cost_calculator,
        graph_store=graph_store,
    )


def _make_batch_processor(file_processor: Any) -> BatchProcessor:
    return BatchProcessor(file_processor=file_processor)


# ---------------------------------------------------------------------------
# scan_directory
# ---------------------------------------------------------------------------

class TestScanDirectory:
    def test_returns_list_of_paths(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.pdf").write_text("world")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.png").write_bytes(b"\x00")

        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        found = bp.scan_directory(tmp_path)

        assert isinstance(found, list)
        assert all(isinstance(p, Path) for p in found)
        assert len(found) == 3

    def test_returns_only_files_not_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("x")
        (tmp_path / "subdir").mkdir()

        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        found = bp.scan_directory(tmp_path)
        assert all(p.is_file() for p in found)

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        found = bp.scan_directory(tmp_path)
        assert found == []

    def test_nonexistent_directory_returns_empty_list(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        found = bp.scan_directory(tmp_path / "does_not_exist")
        assert found == []

    def test_skips_files_via_should_skip_file(self, tmp_path: Path) -> None:
        """Files for which should_skip_file returns True must be excluded."""
        (tmp_path / "keep.txt").write_text("ok")
        (tmp_path / "skip.txt").write_text("no")

        mock_organizer = MagicMock()
        mock_organizer.should_skip_file.side_effect = lambda p: p.name == "skip.txt"

        fp = _make_file_processor(tmp_path)
        fp._organizer = mock_organizer  # type: ignore[attr-defined]
        bp = _make_batch_processor(fp)

        found = bp.scan_directory(tmp_path)
        names = [p.name for p in found]
        assert "keep.txt" in names
        assert "skip.txt" not in names


# ---------------------------------------------------------------------------
# organize_file (dry_run mode)
# ---------------------------------------------------------------------------

def _make_mock_organizer(dest: Path) -> MagicMock:
    """Mock organizer exposing the classification hooks FileProcessor calls."""
    org = MagicMock()
    org.stats = defaultdict(int)
    org.should_skip_file.return_value = False
    org._maybe_rename_image.side_effect = lambda p, dry_run: p
    org.detect_file_category.return_value = (
        "technical", "other", "DigitalDocument", "", None, [], {},
    )
    org.generate_schema.return_value = {"@type": "DigitalDocument"}
    org.get_destination_path.return_value = dest
    org._last_file_ocr_confidence = None
    org._last_file_detected_language = None
    org._last_file_state = {}
    return org


class TestOrganizeFileDryRun:
    def test_dry_run_does_not_move_file(self, tmp_path: Path) -> None:
        src = tmp_path / "test.txt"
        src.write_text("content")
        dest = tmp_path / "dest" / "test.txt"

        mock_organizer = _make_mock_organizer(dest)

        fp = _make_file_processor(tmp_path)
        fp._organizer = mock_organizer  # type: ignore[attr-defined]
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True

        result = fp.organize_file(src, dry_run=True)

        assert result["status"] == "would_organize"
        assert result["destination"] == str(dest)
        assert mock_organizer.stats["organized"] == 1
        assert src.exists()
        assert not dest.exists()

    def test_organize_file_calls_classification_hooks(self, tmp_path: Path) -> None:
        """FileProcessor owns the pipeline and calls back into the organizer
        for classification (detect_file_category, generate_schema,
        get_destination_path)."""
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF")
        dest = tmp_path / "dest" / "doc.pdf"

        mock_organizer = _make_mock_organizer(dest)

        fp = _make_file_processor(tmp_path)
        fp._organizer = mock_organizer  # type: ignore[attr-defined]
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True

        fp.organize_file(src, dry_run=True, force=False)

        mock_organizer.detect_file_category.assert_called_once_with(src, display_path=None)
        mock_organizer.generate_schema.assert_called_once_with(src, "DigitalDocument", "")
        mock_organizer.get_destination_path.assert_called_once()

    def test_organize_file_skips_system_files(self, tmp_path: Path) -> None:
        src = tmp_path / ".DS_Store"
        src.write_bytes(b"\x00")

        mock_organizer = _make_mock_organizer(tmp_path / "dest" / ".DS_Store")
        mock_organizer.should_skip_file.return_value = True

        fp = _make_file_processor(tmp_path)
        fp._organizer = mock_organizer  # type: ignore[attr-defined]

        result = fp.organize_file(src, dry_run=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "system_file"
        assert mock_organizer.stats["skipped"] == 1
        mock_organizer.detect_file_category.assert_not_called()

    def test_organize_file_raises_without_organizer(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        with pytest.raises(RuntimeError, match="_organizer"):
            fp.organize_file(tmp_path / "x.txt", dry_run=True)


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------

class TestPrintSummary:
    def _make_summary(self, dry_run: bool = False) -> Dict[str, Any]:
        return {
            "total_files": 5,
            "organized": 3,
            "already_organized": 1,
            "skipped": 1,
            "errors": 0,
            "dry_run": dry_run,
            "results": [
                {
                    "status": "organized",
                    "category": "financial",
                    "subcategory": "invoices",
                    "company_name": "Acme Corp",
                    "extracted_text_length": 200,
                },
                {
                    "status": "organized",
                    "category": "technical",
                    "subcategory": "other",
                    "company_name": None,
                    "extracted_text_length": 0,
                },
            ],
            "registry_stats": None,
        }

    def test_print_summary_outputs_required_keys(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        bp.print_summary(self._make_summary())

        captured = capsys.readouterr().out
        assert "Total files processed" in captured
        assert "Successfully organized" in captured
        assert "Already organized" in captured
        assert "Skipped" in captured
        assert "Errors" in captured

    def test_print_summary_shows_dry_run_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        bp.print_summary(self._make_summary(dry_run=True))

        captured = capsys.readouterr().out
        assert "DRY RUN" in captured

    def test_print_summary_shows_category_breakdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        bp.print_summary(self._make_summary())

        captured = capsys.readouterr().out
        assert "Financial" in captured
        assert "Technical" in captured

    def test_print_summary_shows_detected_companies(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fp = _make_file_processor(tmp_path)
        bp = _make_batch_processor(fp)

        bp.print_summary(self._make_summary())

        captured = capsys.readouterr().out
        assert "Acme Corp" in captured


# ---------------------------------------------------------------------------
# get_cost_report / save_cost_report
# ---------------------------------------------------------------------------

class TestCostReports:
    def test_get_cost_report_returns_none_without_calculator(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path, cost_calculator=None)
        fp.cost_calculator = None
        assert fp.get_cost_report() is None

    def test_get_cost_report_delegates_to_calculator(self, tmp_path: Path) -> None:
        mock_calc = MagicMock()
        mock_calc.generate_report.return_value = {"total": 0.05}

        fp = _make_file_processor(tmp_path, cost_calculator=mock_calc)
        report = fp.get_cost_report()

        mock_calc.generate_report.assert_called_once()
        assert report == {"total": 0.05}

    def test_save_cost_report_prints_when_disabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fp = _make_file_processor(tmp_path)
        fp.cost_calculator = None

        fp.save_cost_report()

        assert "not enabled" in capsys.readouterr().out

    def test_save_cost_report_uses_provided_path(self, tmp_path: Path) -> None:
        mock_calc = MagicMock()
        fp = _make_file_processor(tmp_path, cost_calculator=mock_calc)
        out = str(tmp_path / "report.json")

        fp.save_cost_report(output_path=out)

        mock_calc.generate_report.assert_called_once_with(out)


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------

class TestSaveReport:
    def test_save_report_writes_json_file(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        summary = {"total_files": 10, "organized": 8}
        out = str(tmp_path / "report.json")

        fp.save_report(summary, output_path=out)

        with open(out) as f:
            data = json.load(f)
        assert data["total_files"] == 10
        assert data["organized"] == 8
