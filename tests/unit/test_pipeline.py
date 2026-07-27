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
        "technical",
        "other",
        "DigitalDocument",
        "",
        None,
        [],
        {},
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


# ---------------------------------------------------------------------------
# _persist_to_graph_store — location edge from image metadata
# ---------------------------------------------------------------------------


class TestPersistLocationEdge:
    def _persist(self, tmp_path: Path, image_metadata: Any) -> MagicMock:
        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-1")
        fp = _make_file_processor(tmp_path, graph_store=graph_store)
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"\xff\xd8")
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=tmp_path / "dest" / "photo.jpg",
            category="media",
            subcategory="photos",
            schema={"@type": "ImageObject", "encodingFormat": "image/jpeg"},
            extracted_text="",
            company_name=None,
            people_names=[],
            image_metadata=image_metadata,
        )
        return graph_store

    def test_metadata_summary_shape_creates_location_edge(self, tmp_path: Path) -> None:
        """get_metadata_summary() emits location_name/gps_coordinates — the
        shape ContentOrganizer actually passes in."""
        store = self._persist(
            tmp_path,
            {
                "location_name": "San Francisco, California, USA",
                "gps_coordinates": (37.77, -122.42),
            },
        )
        store.add_file_to_location.assert_called_once()
        kwargs = store.add_file_to_location.call_args.kwargs
        assert kwargs["location_name"] == "San Francisco, California, USA"
        assert kwargs["latitude"] == 37.77
        assert kwargs["longitude"] == -122.42

    def test_structured_location_shape_still_supported(self, tmp_path: Path) -> None:
        store = self._persist(
            tmp_path,
            {
                "location": {
                    "display_name": "NYC",
                    "latitude": 40.7,
                    "longitude": -74.0,
                    "city": "New York",
                    "state": "NY",
                    "country": "US",
                },
            },
        )
        kwargs = store.add_file_to_location.call_args.kwargs
        assert kwargs["location_name"] == "NYC"
        assert kwargs["city"] == "New York"

    def test_no_location_no_edge(self, tmp_path: Path) -> None:
        store = self._persist(tmp_path, {"datetime": None, "location_name": None})
        store.add_file_to_location.assert_not_called()

    def test_location_name_without_coordinates(self, tmp_path: Path) -> None:
        store = self._persist(tmp_path, {"location_name": "Marfa", "gps_coordinates": None})
        kwargs = store.add_file_to_location.call_args.kwargs
        assert kwargs["location_name"] == "Marfa"
        assert kwargs["latitude"] is None


# ---------------------------------------------------------------------------
# _persist_to_graph_store — category edge replacement on re-run (Bug 1)
# ---------------------------------------------------------------------------


class TestPersistCategoryEdgeReplacement:
    """_persist_to_graph_store must replace, not accumulate, category edges.

    When the same file is processed a second time (different category or the
    same category), the DB row must end up with exactly ONE category edge —
    the one from the most recent run — not both the old and new.
    """

    def _persist(
        self,
        tmp_path: Path,
        src: Path,
        dest: Path,
        category: str,
        subcategory: str,
        graph_store: Any,
    ) -> None:
        fp = _make_file_processor(tmp_path, graph_store=graph_store)
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True
        fp.registry = MagicMock()
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=dest,
            category=category,
            subcategory=subcategory,
            schema={"@type": "DigitalDocument", "encodingFormat": "application/pdf"},
            extracted_text="",
            company_name=None,
            people_names=[],
            image_metadata=None,
        )

    def test_re_run_replaces_old_category_edge(self, tmp_path: Path) -> None:
        """Second persist replaces the first category edge, not stacks on it."""
        # Use the flat import path (storage.*) so the FileStatus enum class
        # matches what FileProcessor._persist_to_graph_store passes — both
        # .  and src/ are on pytest's sys.path, making storage.* and
        # src.storage.* distinct module objects despite being the same file.
        from storage.graph_store import GraphStore  # noqa: PLC0415
        from storage.models import File  # noqa: PLC0415

        db_path = str(tmp_path / "graph.db")
        store = GraphStore(db_path)

        src = tmp_path / "invoice.pdf"
        src.write_bytes(b"%PDF-1")
        dest = tmp_path / "organized" / "invoice.pdf"
        dest.parent.mkdir()
        dest.write_bytes(b"%PDF-1")

        # First run: classified as game_assets/sprites
        self._persist(tmp_path, src, dest, "game_assets", "sprites", store)

        session = store.get_session()
        file_row = session.query(File).filter(File.original_path == str(src)).first()
        assert file_row is not None
        first_categories = [c.full_path for c in file_row.categories]
        session.close()
        assert first_categories == ["game_assets/sprites"]

        # Second run: now classified as media/photos_other
        self._persist(tmp_path, src, dest, "media", "photos_other", store)

        session = store.get_session()
        file_row = session.query(File).filter(File.original_path == str(src)).first()
        assert file_row is not None
        second_categories = [c.full_path for c in file_row.categories]
        session.close()

        # Must have exactly one edge — the new one
        assert second_categories == ["media/photos_other"], (
            f"Expected only media/photos_other but got {second_categories!r}; "
            "stale game_assets/sprites edge was not removed"
        )

    def test_file_count_is_correct_after_replacement(self, tmp_path: Path) -> None:
        """Category.file_count stays at 1 after a re-run, not 2."""
        from storage.graph_store import GraphStore  # noqa: PLC0415
        from storage.models import Category  # noqa: PLC0415

        db_path = str(tmp_path / "graph.db")
        store = GraphStore(db_path)

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF")
        dest = tmp_path / "dest" / "doc.pdf"
        dest.parent.mkdir()
        dest.write_bytes(b"%PDF")

        self._persist(tmp_path, src, dest, "financial", "invoices", store)
        self._persist(tmp_path, src, dest, "financial", "invoices", store)

        session = store.get_session()
        cat = session.query(Category).filter(Category.full_path == "financial/invoices").first()
        count = cat.file_count if cat else None
        session.close()
        assert count == 1, f"Expected file_count=1 after idempotent re-run, got {count}"


# ---------------------------------------------------------------------------
# _content_description
# ---------------------------------------------------------------------------


class TestContentDescription:
    def test_filename_fallback_without_organizer(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        assert fp._content_description(tmp_path / "report.pdf") == "report.pdf"

    def test_filename_fallback_without_clip_state(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        fp._organizer = MagicMock(_last_file_state={})
        assert fp._content_description(tmp_path / "report.pdf") == "report.pdf"

    def test_composes_clip_label_and_confidence(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        fp._organizer = MagicMock(_last_file_state={"clip_description": ("food or a meal", 0.914)})
        assert fp._content_description(tmp_path / "img.jpg") == (
            "Content: food or a meal (91% confident)"
        )


class TestGenerateSchemaSceneTypes:
    """Scene @types (from the unified SceneSignal: Room family, House, Place)
    are image-shaped: generate_schema must persist the assigned @type with
    image properties, not fall through to DocumentGenerator's
    ``DigitalDocument`` default."""

    @pytest.mark.parametrize(
        "scene_type", ["Room", "HotelRoom", "MeetingRoom", "House", "Place", "Accommodation"]
    )
    def test_scene_type_keeps_its_type_and_is_image_shaped(
        self, tmp_path: Path, scene_type: str
    ) -> None:
        fp = _make_file_processor(tmp_path)
        img = tmp_path / "interior.png"
        img.write_bytes(b"x")
        schema = fp.generate_schema(img, scene_type)
        assert schema["@type"] == scene_type
        # contentUrl is an ImageGenerator property; its presence proves we did
        # NOT drop into the DocumentGenerator branch.
        assert "contentUrl" in schema

    def test_unknown_type_still_falls_back_to_document(self, tmp_path: Path) -> None:
        fp = _make_file_processor(tmp_path)
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        assert fp.generate_schema(f, "TotallyUnknownType")["@type"] == "DigitalDocument"


# ---------------------------------------------------------------------------
# organize_file — AI classification paths (skip, already-organized, error,
# non-dry-run)
# ---------------------------------------------------------------------------


class TestOrganizeFileAIPaths:
    """Exercises the organize_file branches not covered by dry-run tests."""

    def _make_fp(self, tmp_path: Path, graph_store: Any = None) -> FileProcessor:
        fp = _make_file_processor(tmp_path, graph_store=graph_store)
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True
        fp.registry = MagicMock()
        return fp

    def _attach_organizer(self, fp: FileProcessor, dest: Path, **kwargs: Any) -> MagicMock:
        org = _make_mock_organizer(dest)
        for k, v in kwargs.items():
            setattr(org, k, v)
        fp._organizer = org  # type: ignore[attr-defined]
        return org

    def test_skip_category_returns_skipped_with_reason(self, tmp_path: Path) -> None:
        """detect_file_category returning category='skip' should short-circuit."""
        src = tmp_path / "dup.txt"
        src.write_text("duplicate")
        dest = tmp_path / "dest" / "dup.txt"

        fp = self._make_fp(tmp_path)
        org = self._attach_organizer(fp, dest)
        org.detect_file_category.return_value = (
            "skip",
            "duplicate",
            "DigitalDocument",
            "",
            None,
            [],
            {},
        )

        result = fp.organize_file(src, dry_run=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate"
        assert org.stats["skipped"] == 1
        org.generate_schema.assert_not_called()

    def test_already_organized_returns_status_without_move(self, tmp_path: Path) -> None:
        """File already at destination returns already_organized without moving."""
        src = tmp_path / "in_place.txt"
        src.write_text("already here")

        fp = self._make_fp(tmp_path)
        # dest == src so the already-organized branch fires
        org = self._attach_organizer(fp, src)

        result = fp.organize_file(src, dry_run=False, force=False)

        assert result["status"] == "already_organized"
        assert result["destination"] == str(src)
        assert org.stats["already_organized"] == 1

    def test_force_flag_bypasses_already_organized(self, tmp_path: Path) -> None:
        """force=True re-organizes even when file is already at its destination."""
        src = tmp_path / "in_place.txt"
        src.write_text("already here")
        # Destination is a new path so shutil.move won't error
        dest = tmp_path / "dest"
        dest.mkdir()
        final_dest = dest / "in_place.txt"

        fp = self._make_fp(tmp_path)
        org = self._attach_organizer(fp, final_dest)

        result = fp.organize_file(src, dry_run=True, force=True)

        assert result["status"] == "would_organize"
        assert org.stats["organized"] == 1

    def test_error_in_detection_is_captured(self, tmp_path: Path) -> None:
        """Exceptions during detect_file_category are caught and surfaced."""
        src = tmp_path / "error_file.txt"
        src.write_text("boom")
        dest = tmp_path / "dest" / "error_file.txt"

        fp = self._make_fp(tmp_path)
        org = self._attach_organizer(fp, dest)
        org.detect_file_category.side_effect = RuntimeError("classifier exploded")

        result = fp.organize_file(src, dry_run=True)

        assert result["status"] == "error"
        assert "classifier exploded" in result["reason"]
        assert org.stats["errors"] == 1

    def test_non_dry_run_registers_schema(self, tmp_path: Path) -> None:
        """Without dry_run the registry and shutil.move path are exercised."""
        src = tmp_path / "real_file.txt"
        src.write_text("real content")
        dest_dir = tmp_path / "organized"
        dest_dir.mkdir()
        dest = dest_dir / "real_file.txt"

        fp = self._make_fp(tmp_path)
        self._attach_organizer(fp, dest)

        result = fp.organize_file(src, dry_run=False)

        assert result["status"] == "organized"
        # fp.registry is a MagicMock (see _make_fp); SchemaRegistry.register is
        # a plain callable on the real type, so reach the mock through Any.
        registry: Any = fp.registry
        registry.register.assert_called_once()
        # File was moved
        assert dest.exists()
        assert not src.exists()

    def test_non_dry_run_calls_graph_store(self, tmp_path: Path) -> None:
        """Graph store persistence is called during a live (non-dry-run) run."""
        src = tmp_path / "graphed.txt"
        src.write_text("store me")
        dest_dir = tmp_path / "organized"
        dest_dir.mkdir()
        dest = dest_dir / "graphed.txt"

        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-42")
        fp = self._make_fp(tmp_path, graph_store=graph_store)
        self._attach_organizer(fp, dest)

        result = fp.organize_file(src, dry_run=False)

        assert result["status"] == "organized"
        graph_store.add_file.assert_called_once()
        call_kwargs = graph_store.add_file.call_args.kwargs
        assert call_kwargs["filename"] == "graphed.txt"
        assert call_kwargs["current_path"] == str(dest)

    def test_already_organized_reconciles_graph_when_not_dry_run(self, tmp_path: Path) -> None:
        """already_organized path calls _persist_to_graph_store to reconcile edges."""
        from storage.graph_store import GraphStore  # noqa: PLC0415
        from storage.models import File  # noqa: PLC0415

        db_path = str(tmp_path / "graph.db")
        src = tmp_path / "in_place.txt"
        src.write_text("already here")
        # dest == src so the already-organized branch fires
        dest = src

        graph_store = GraphStore(db_path)
        fp = self._make_fp(tmp_path, graph_store=graph_store)
        org = self._attach_organizer(fp, dest)
        org.detect_file_category.return_value = (
            "financial",
            "invoices",
            "DigitalDocument",
            "",
            None,
            [],
            {},
        )

        result = fp.organize_file(src, dry_run=False, force=False)

        assert result["status"] == "already_organized"
        # Graph row must exist after the non-dry-run reconcile
        session = graph_store.get_session()
        file_row = session.query(File).filter(File.original_path == str(src)).first()
        assert file_row is not None, "DB row was not created for already_organized file"
        category_paths = [c.full_path for c in file_row.categories]
        session.close()
        assert "financial/invoices" in category_paths

    def test_already_organized_dry_run_does_not_write_graph(self, tmp_path: Path) -> None:
        """already_organized + dry_run must NOT touch the graph store."""
        graph_store = MagicMock()
        src = tmp_path / "in_place.txt"
        src.write_text("x")

        fp = self._make_fp(tmp_path, graph_store=graph_store)
        self._attach_organizer(fp, src)  # dest == src

        result = fp.organize_file(src, dry_run=True, force=False)

        assert result["status"] == "already_organized"
        graph_store.add_file.assert_not_called()

    def test_non_file_path_is_skipped(self, tmp_path: Path) -> None:
        """Passing a directory path returns skipped / not_file."""
        dest = tmp_path / "dest" / "subdir"
        fp = self._make_fp(tmp_path)
        org = self._attach_organizer(fp, dest)
        org.should_skip_file.return_value = False

        result = fp.organize_file(tmp_path, dry_run=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_file"


# ---------------------------------------------------------------------------
# organize_directories (BatchProcessor AI paths)
# ---------------------------------------------------------------------------


class TestOrganizeDirectories:
    """Exercises the organize_directories / organize_batch main loop."""

    def test_organize_directories_processes_all_files(self, tmp_path: Path) -> None:
        """Files from a source directory are each passed to file_processor."""
        src = tmp_path / "source"
        src.mkdir()
        (src / "a.txt").write_text("alpha")
        (src / "b.txt").write_text("beta")

        # Use a real BatchProcessor to exercise the actual scan + dispatch loop
        fp = _make_file_processor(tmp_path)
        org = MagicMock()
        org.stats = defaultdict(int)
        org.ocr_available = True
        org.registry = None
        org.should_skip_file.return_value = False
        org._maybe_rename_image.side_effect = lambda p, dr: p
        org.detect_file_category.return_value = (
            "technical",
            "other",
            "DigitalDocument",
            "",
            None,
            [],
            {},
        )
        org.generate_schema.return_value = {"@type": "DigitalDocument"}
        org.get_destination_path.return_value = tmp_path / "organized" / "file.txt"
        fp._organizer = org  # type: ignore[attr-defined]
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True

        bp = BatchProcessor(file_processor=fp)
        summary = bp.organize_directories([str(src)], dry_run=True)

        assert summary["total_files"] == 2
        assert org.detect_file_category.call_count == 2

    def test_organize_directories_respects_limit(self, tmp_path: Path) -> None:
        """limit parameter caps the number of processed files."""
        src = tmp_path / "source"
        src.mkdir()
        for i in range(5):
            (src / f"file_{i}.txt").write_text(f"content {i}")

        fp = _make_file_processor(tmp_path)
        org = MagicMock()
        org.stats = defaultdict(int)
        org.ocr_available = True
        org.registry = None
        org.should_skip_file.return_value = False
        org._maybe_rename_image.side_effect = lambda p, dr: p
        org.detect_file_category.return_value = (
            "technical",
            "other",
            "DigitalDocument",
            "",
            None,
            [],
            {},
        )
        org.generate_schema.return_value = {"@type": "DigitalDocument"}
        org.get_destination_path.return_value = tmp_path / "organized" / "x.txt"
        fp._organizer = org  # type: ignore[attr-defined]
        fp.validator = MagicMock()
        fp.validator.validate.return_value.is_valid.return_value = True

        bp = BatchProcessor(file_processor=fp)
        summary = bp.organize_directories([str(src)], dry_run=True, limit=2)

        assert summary["total_files"] == 2
        assert org.detect_file_category.call_count == 2

    def test_organize_directories_nonexistent_dir_is_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Non-existent source directories are reported and skipped gracefully."""
        fp = _make_file_processor(tmp_path)
        org = MagicMock()
        org.stats = defaultdict(int)
        org.ocr_available = True
        org.registry = None
        fp._organizer = org  # type: ignore[attr-defined]

        bp = BatchProcessor(file_processor=fp)
        summary = bp.organize_directories([str(tmp_path / "no_such_dir")], dry_run=True)

        assert summary["total_files"] == 0
        assert "not found" in capsys.readouterr().out

    def test_organize_directories_summary_structure(self, tmp_path: Path) -> None:
        """Summary dict has the expected keys."""
        fp = _make_file_processor(tmp_path)
        org = MagicMock()
        org.stats = defaultdict(int)
        org.ocr_available = True
        org.registry = None
        fp._organizer = org  # type: ignore[attr-defined]

        bp = BatchProcessor(file_processor=fp)
        summary = bp.organize_directories([], dry_run=True)

        for key in (
            "total_files",
            "organized",
            "already_organized",
            "skipped",
            "errors",
            "dry_run",
        ):
            assert key in summary

    def test_organize_directories_ocr_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When ocr_available is False a warning is printed."""
        fp = _make_file_processor(tmp_path)
        org = MagicMock()
        org.stats = defaultdict(int)
        org.ocr_available = False
        org.registry = None
        fp._organizer = org  # type: ignore[attr-defined]

        bp = BatchProcessor(file_processor=fp)
        bp.organize_directories([], dry_run=True)

        assert "WARNING" in capsys.readouterr().out
