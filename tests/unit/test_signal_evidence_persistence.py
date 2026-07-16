"""Unit tests for signal_evidence persistence (UNIFIED_SCORING_PLAN §5.4).

Covers the storage half of the shadow/unified scoring pipeline:
- GraphStore.add_file_to_category accepts and stores ``signal_evidence`` on
  the file_categories association row (verbatim JSON, NULL when absent), and
  degrades gracefully on databases created before the column existed.
- FileProcessor reads ``organizer._last_file_state["scoring_decision"]`` and
  passes it through _persist_to_graph_store into the graph-store write.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from src.pipeline import FileProcessor

# GraphStore comes via file_processor so the FileStatus enum identity in the
# store's table metadata matches what _persist_to_graph_store passes
# (file_processor prefers the flat `storage.*` modules; binding
# src.storage.GraphStore here would pair a different FileStatus class with the
# insert and the end-to-end persistence would fail with a LookupError).
from src.pipeline.file_processor import GraphStore
from src.storage.models import file_categories
from src.storage.scoring_migration import run_scoring_migration

# Shadow-run evidence dict in the shape the unified adapter will populate
# (self-describing via "scorer" — no separate source column, plan §5.4).
SHADOW_DECISION: Dict[str, Any] = {
    "scorer": "shadow",
    "decision": {
        "category": "technical",
        "subcategory": "other",
        "confidence": 0.71,
        "margin": 0.18,
        "decision_state": "committed",
    },
    "winning_signals": ["TextContentSignal"],
    "all_scores": [
        {"signal": "TextContentSignal", "cat": "technical", "sub": "other", "conf": 0.71}
    ],
    "agrees": True,
}


def _evidence_rows(store: GraphStore, file_id: str) -> List[Tuple[int, Optional[dict]]]:
    """(category_id, signal_evidence) rows for a file's category associations."""
    session = store.get_session()
    try:
        rows = session.execute(
            select(file_categories.c.category_id, file_categories.c.signal_evidence).where(
                file_categories.c.file_id == file_id
            )
        ).all()
        return [(row.category_id, row.signal_evidence) for row in rows]
    finally:
        session.close()


def _add_file(store: GraphStore, path: str) -> str:
    session = store.get_session()
    try:
        file = store.add_file(original_path=path, filename=Path(path).name, session=session)
        file_id = file.id
        session.commit()
        return file_id
    finally:
        session.close()


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(str(tmp_path / "graph.db"))


class TestGraphStoreSignalEvidence:
    def test_stores_evidence_verbatim(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/report.pdf")

        assert (
            store.add_file_to_category(file_id, "technical", signal_evidence=SHADOW_DECISION)
            is True
        )

        rows = _evidence_rows(store, file_id)
        assert len(rows) == 1
        assert rows[0][1] == SHADOW_DECISION

    def test_default_is_null(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/report.pdf")

        store.add_file_to_category(file_id, "technical")

        rows = _evidence_rows(store, file_id)
        assert rows == [(rows[0][0], None)]

    def test_evidence_lands_on_subcategory_association(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/report.pdf")

        store.add_file_to_category(file_id, "technical", "other", signal_evidence=SHADOW_DECISION)

        rows = _evidence_rows(store, file_id)
        assert len(rows) == 1  # associated with the subcategory node only
        assert rows[0][1] == SHADOW_DECISION

    def test_existing_association_gets_updated_evidence(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/report.pdf")
        store.add_file_to_category(file_id, "technical")  # legacy run: NULL

        updated = dict(SHADOW_DECISION, scorer="unified")
        store.add_file_to_category(file_id, "technical", signal_evidence=updated)

        rows = _evidence_rows(store, file_id)
        assert len(rows) == 1  # no duplicate association
        assert rows[0][1] == updated

    def test_missing_file_returns_false(self, store: GraphStore) -> None:
        assert (
            store.add_file_to_category("no-such-id", "technical", signal_evidence=SHADOW_DECISION)
            is False
        )


class TestUnmigratedDatabase:
    """Databases created before the column existed skip evidence gracefully."""

    @pytest.fixture
    def legacy_db_path(self, tmp_path: Path) -> str:
        """A GraphStore database whose file_categories lacks signal_evidence."""
        db_path = str(tmp_path / "legacy.db")
        GraphStore(db_path)  # create the full modern schema

        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE file_categories_legacy AS
                SELECT file_id, category_id, confidence, created_at FROM file_categories;
            DROP TABLE file_categories;
            ALTER TABLE file_categories_legacy RENAME TO file_categories;
            """)
        conn.commit()
        conn.close()
        return db_path

    def test_evidence_skipped_with_warning_and_edge_still_written(
        self, legacy_db_path: str, capsys
    ) -> None:
        store = GraphStore(legacy_db_path)
        file_id = _add_file(store, "/tmp/report.pdf")

        assert (
            store.add_file_to_category(file_id, "technical", signal_evidence=SHADOW_DECISION)
            is True
        )

        assert "migrate-scoring" in capsys.readouterr().out
        conn = sqlite3.connect(legacy_db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM file_categories WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 1  # association written even though evidence was skipped

    def test_migration_then_new_store_persists_evidence(self, legacy_db_path: str) -> None:
        run_scoring_migration(legacy_db_path, dry_run=False)

        store = GraphStore(legacy_db_path)
        file_id = _add_file(store, "/tmp/report.pdf")
        store.add_file_to_category(file_id, "technical", signal_evidence=SHADOW_DECISION)

        rows = _evidence_rows(store, file_id)
        assert len(rows) == 1
        assert rows[0][1] == SHADOW_DECISION


# ---------------------------------------------------------------------------
# FileProcessor pass-through (mirrors tests/unit/test_pipeline.py idioms)
# ---------------------------------------------------------------------------


def _make_file_processor(base_path: Path, graph_store: Any) -> FileProcessor:
    fp = FileProcessor(
        base_path=base_path,
        dry_run=True,
        db_path=None,
        cost_calculator=None,
        graph_store=graph_store,
    )
    fp.validator = MagicMock()
    fp.validator.validate.return_value.is_valid.return_value = True
    fp.registry = MagicMock()
    return fp


def _make_mock_organizer(dest: Path, last_file_state: Optional[Dict[str, Any]] = None) -> MagicMock:
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
    org._last_file_state = last_file_state if last_file_state is not None else {}
    return org


class TestPersistToGraphStorePassThrough:
    def _persist(self, tmp_path: Path, scoring_decision: Optional[Dict[str, Any]]) -> MagicMock:
        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-1")
        fp = _make_file_processor(tmp_path, graph_store)
        src = tmp_path / "doc.txt"
        src.write_text("content")
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=tmp_path / "dest" / "doc.txt",
            category="technical",
            subcategory="other",
            schema={"@type": "DigitalDocument"},
            extracted_text="",
            company_name=None,
            people_names=[],
            image_metadata={},
            scoring_decision=scoring_decision,
        )
        return graph_store

    def test_forwards_scoring_decision_as_signal_evidence(self, tmp_path: Path) -> None:
        store = self._persist(tmp_path, SHADOW_DECISION)
        kwargs = store.add_file_to_category.call_args.kwargs
        assert kwargs["signal_evidence"] == SHADOW_DECISION

    def test_default_forwards_none(self, tmp_path: Path) -> None:
        store = self._persist(tmp_path, None)
        kwargs = store.add_file_to_category.call_args.kwargs
        assert kwargs["signal_evidence"] is None


class TestOrganizeFileReadsOrganizerState:
    def _organize(self, tmp_path: Path, last_file_state: Dict[str, Any]) -> MagicMock:
        src = tmp_path / "real.txt"
        src.write_text("real content")
        dest_dir = tmp_path / "organized"
        dest_dir.mkdir()
        dest = dest_dir / "real.txt"

        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-42")
        fp = _make_file_processor(tmp_path, graph_store)
        fp._organizer = _make_mock_organizer(dest, last_file_state)

        result = fp.organize_file(src, dry_run=False)
        assert result["status"] == "organized"
        return graph_store

    def test_scoring_decision_flows_from_last_file_state(self, tmp_path: Path) -> None:
        store = self._organize(tmp_path, {"scoring_decision": SHADOW_DECISION})
        kwargs = store.add_file_to_category.call_args.kwargs
        assert kwargs["signal_evidence"] == SHADOW_DECISION

    def test_legacy_state_without_decision_persists_none(self, tmp_path: Path) -> None:
        store = self._organize(tmp_path, {"kie_result": None})
        kwargs = store.add_file_to_category.call_args.kwargs
        assert kwargs["signal_evidence"] is None


class TestOrganizeFileEndToEnd:
    def test_evidence_lands_in_database(self, tmp_path: Path, store: GraphStore) -> None:
        src = tmp_path / "real.txt"
        src.write_text("real content")
        dest_dir = tmp_path / "organized"
        dest_dir.mkdir()
        dest = dest_dir / "real.txt"

        fp = _make_file_processor(tmp_path, store)
        fp._organizer = _make_mock_organizer(dest, {"scoring_decision": SHADOW_DECISION})

        result = fp.organize_file(src, dry_run=False)

        assert result["status"] == "organized"
        file_record = store.get_file(path=str(src))
        rows = _evidence_rows(store, file_record.id)
        assert len(rows) == 1
        assert rows[0][1] == SHADOW_DECISION
