"""Regression tests for organization-session tracking on the batch path.

The production ``organize-files content`` path is BatchProcessor.organize_directories
→ FileProcessor.organize_file → FileProcessor._persist_to_graph_store →
GraphStore.add_file. Before this was wired, no ``organization_sessions`` row was
ever written and ``files.session_id`` stayed NULL, so the timeline had nothing to
group by. These tests pin:

- BatchProcessor opens a session (non-dry-run + graph store present), threads its
  id into every ``organize_file`` call, and completes it with run stats.
- Dry runs and graph-store-less runs create no session (and don't crash).
- FileProcessor forwards ``session_id`` to ``add_file`` (defaulting to None).
- End-to-end against a real SQLite GraphStore: a session row is written and every
  file links to it.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import MagicMock

from src.pipeline import BatchProcessor, FileProcessor


def _mock_organizer(dest_dir: Path) -> MagicMock:
    """Organizer double exposing the classification hooks FileProcessor calls.

    Routes each file to ``dest_dir/<name>`` so a multi-file batch produces
    distinct destinations, and returns a fresh schema dict per call.
    """
    org = MagicMock()
    org.stats = defaultdict(int)
    org.ocr_available = True
    org.registry = None
    org.should_skip_file.return_value = False
    org._maybe_rename_image.side_effect = lambda p, dry_run: p
    org.detect_file_category.return_value = (
        "technical", "other", "DigitalDocument", "", None, [], {},
    )
    org.generate_schema.side_effect = lambda *a, **k: {"@type": "DigitalDocument"}
    org.get_destination_path.side_effect = lambda renamed_path, *a, **k: dest_dir / Path(renamed_path).name
    org._last_file_ocr_confidence = None
    org._last_file_detected_language = None
    org._last_file_state = {}
    return org


def _batch(tmp_path: Path, graph_store: Any, filenames: List[str]) -> Tuple[BatchProcessor, Path, MagicMock]:
    """Wire a real FileProcessor + BatchProcessor over ``filenames`` in a temp dir."""
    src = tmp_path / "source"
    src.mkdir()
    for name in filenames:
        (src / name).write_text(name)
    dest_dir = tmp_path / "organized"
    dest_dir.mkdir()

    fp = FileProcessor(base_path=tmp_path, dry_run=False, graph_store=graph_store)
    fp.validator = MagicMock()
    fp.validator.validate.return_value.is_valid.return_value = True
    fp.registry = MagicMock()
    fp._organizer = _mock_organizer(dest_dir)  # type: ignore[attr-defined]

    bp = BatchProcessor(file_processor=fp)
    return bp, src, fp._organizer  # type: ignore[attr-defined]


class TestBatchSessionLifecycle:
    def test_non_dry_run_creates_threads_and_completes_session(self, tmp_path: Path) -> None:
        graph_store = MagicMock()
        graph_store.create_session.return_value = MagicMock(id="sess-123")
        graph_store.add_file.return_value = MagicMock(id="file-1")
        bp, src, _org = _batch(tmp_path, graph_store, ["a.txt", "b.txt"])

        bp.organize_directories([str(src)], dry_run=False)

        # Session opened once with this run's parameters.
        graph_store.create_session.assert_called_once()
        cs = graph_store.create_session.call_args.kwargs
        assert cs["source_directories"] == [str(src)]
        assert cs["dry_run"] is False
        assert cs["file_limit"] is None

        # The session id reaches every persisted file.
        assert graph_store.add_file.call_count == 2
        for call in graph_store.add_file.call_args_list:
            assert call.kwargs["session_id"] == "sess-123"

        # Session finalized with run stats.
        graph_store.complete_session.assert_called_once()
        sid, stats = graph_store.complete_session.call_args.args
        assert sid == "sess-123"
        assert stats["total_files"] == 2
        assert stats["organized"] == 2

    def test_dry_run_creates_no_session_and_persists_nothing(self, tmp_path: Path) -> None:
        graph_store = MagicMock()
        bp, src, _org = _batch(tmp_path, graph_store, ["a.txt"])

        bp.organize_directories([str(src)], dry_run=True)

        graph_store.create_session.assert_not_called()
        graph_store.complete_session.assert_not_called()
        graph_store.add_file.assert_not_called()

    def test_no_graph_store_runs_without_session(self, tmp_path: Path) -> None:
        bp, src, _org = _batch(tmp_path, None, ["a.txt"])

        summary = bp.organize_directories([str(src)], dry_run=False)

        assert summary["total_files"] == 1

    def test_create_session_failure_is_non_fatal(self, tmp_path: Path) -> None:
        graph_store = MagicMock()
        graph_store.create_session.side_effect = RuntimeError("db down")
        graph_store.add_file.return_value = MagicMock(id="file-1")
        bp, src, _org = _batch(tmp_path, graph_store, ["a.txt"])

        summary = bp.organize_directories([str(src)], dry_run=False)

        # Organization still completes; files persist unlinked (session_id None).
        assert summary["total_files"] == 1
        graph_store.complete_session.assert_not_called()
        assert graph_store.add_file.call_args.kwargs["session_id"] is None


class TestPersistSessionLinkage:
    """FileProcessor._persist_to_graph_store forwards session_id to add_file."""

    def _fp(self, tmp_path: Path) -> Tuple[FileProcessor, MagicMock]:
        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-1")
        fp = FileProcessor(base_path=tmp_path, graph_store=graph_store)
        return fp, graph_store

    def _persist(self, fp: FileProcessor, tmp_path: Path, **kwargs: Any) -> None:
        src = tmp_path / "f.txt"
        src.write_text("x")
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=src,
            category="technical",
            subcategory="other",
            schema={"@type": "DigitalDocument"},
            extracted_text="",
            company_name=None,
            people_names=[],
            image_metadata=None,
            **kwargs,
        )

    def test_session_id_forwarded_to_add_file(self, tmp_path: Path) -> None:
        fp, graph_store = self._fp(tmp_path)
        self._persist(fp, tmp_path, session_id="sess-9")
        assert graph_store.add_file.call_args.kwargs["session_id"] == "sess-9"

    def test_session_id_defaults_to_none(self, tmp_path: Path) -> None:
        fp, graph_store = self._fp(tmp_path)
        self._persist(fp, tmp_path)
        assert graph_store.add_file.call_args.kwargs["session_id"] is None


class TestSessionPersistedToRealDb:
    """End-to-end against a real SQLite GraphStore (the actual bug locus).

    Builds the store from the exact ``GraphStore`` symbol ``file_processor``
    resolved, so the ``FileStatus`` enum the ``files`` column was declared with
    matches the one persistence uses (the flat-vs-``src`` dual import otherwise
    yields two distinct enum classes and a spurious write failure). Assertions
    read the raw SQLite rows so they don't depend on ORM class identity.
    """

    def test_batch_run_writes_session_and_links_files(self, tmp_path: Path) -> None:
        import sqlite3

        from src.pipeline import file_processor as fp_mod

        db_path = tmp_path / "graph.db"
        store = fp_mod.GraphStore(str(db_path))
        bp, src, _org = _batch(tmp_path, store, ["a.txt", "b.txt"])

        summary = bp.organize_directories([str(src)], dry_run=False)
        assert summary["organized"] == 2

        conn = sqlite3.connect(str(db_path))
        try:
            sessions = conn.execute(
                "SELECT id, total_files, completed_at FROM organization_sessions"
            ).fetchall()
            assert len(sessions) == 1
            sid, total_files, completed_at = sessions[0]
            assert total_files == 2
            assert completed_at is not None

            file_sids = [row[0] for row in conn.execute("SELECT session_id FROM files").fetchall()]
            assert len(file_sids) == 2
            assert all(s == sid for s in file_sids)
        finally:
            conn.close()
