"""Tests for GraphStore.set_file_category / prune_missing_files and the
organize-files reconcile CLI command."""

import argparse
from pathlib import Path
from typing import Optional

import pytest

from src.storage.graph_store import GraphStore
from src.storage.models import File, FileStatus, file_categories


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "graph.db")


@pytest.fixture
def store(db_path: str) -> GraphStore:
    return GraphStore(db_path)


def _add_file(store: GraphStore, path: str, category: str, subcategory: Optional[str] = None):
    """Create a file and attach one category edge; returns the file id."""
    session = store.get_session()
    file = store.add_file(original_path=path, filename=Path(path).name, session=session)
    file_id = file.id
    store.add_file_to_category(file_id, category, subcategory, session=session)
    session.commit()
    session.close()
    return file_id


def _categories(store: GraphStore, file_id: str) -> list:
    session = store.get_session()
    try:
        file = session.query(File).filter(File.id == file_id).first()
        assert file is not None
        return sorted(c.full_path for c in file.categories)
    finally:
        session.close()


def _file_count(store: GraphStore, full_path: str) -> int:
    from src.storage.models import Category

    session = store.get_session()
    try:
        cat = session.query(Category).filter(Category.full_path == full_path).first()
        return (cat.file_count or 0) if cat else 0
    finally:
        session.close()


class TestSetFileCategory:
    def test_replaces_edge_and_adjusts_counts(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "business", "clients")
        assert _categories(store, file_id) == ["business/clients"]
        assert _file_count(store, "business/clients") == 1

        summary = store.set_file_category(file_id, "legal")

        assert summary is not None
        assert summary["old_categories"] == ["business/clients"]
        assert summary["new_category"] == "legal"
        assert _categories(store, file_id) == ["legal"]
        assert _file_count(store, "business/clients") == 0
        assert _file_count(store, "legal") == 1

    def test_supports_subcategory(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "media", "photos_other")

        store.set_file_category(file_id, "legal", "real_estate")

        assert _categories(store, file_id) == ["legal/real_estate"]

    def test_resolves_by_current_path(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/orig.pdf", "business", "clients")
        store.update_file_status(
            file_id, FileStatus.ORGANIZED, destination="/docs/Personal/Legal/a.pdf"
        )

        summary = store.set_file_category("/docs/Personal/Legal/a.pdf", "legal")

        assert summary is not None
        assert summary["file_id"] == file_id
        assert _categories(store, file_id) == ["legal"]

    def test_dry_run_reports_without_changing(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "business", "clients")

        summary = store.set_file_category(file_id, "legal", dry_run=True)

        assert summary is not None
        assert summary["new_category"] == "legal"
        assert _categories(store, file_id) == ["business/clients"]

    def test_replaces_multiple_categories(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "game_assets", "sprites")
        session = store.get_session()
        store.add_file_to_category(file_id, "media", "interiors_other", session=session)
        session.commit()
        session.close()
        assert sorted(_categories(store, file_id)) == [
            "game_assets/sprites",
            "media/interiors_other",
        ]

        store.set_file_category(file_id, "legal")

        assert _categories(store, file_id) == ["legal"]
        assert _file_count(store, "game_assets/sprites") == 0
        assert _file_count(store, "media/interiors_other") == 0
        assert _file_count(store, "legal") == 1

    def test_returns_none_for_unknown_file(self, store: GraphStore) -> None:
        assert store.set_file_category("no-such-file", "legal") is None


class TestPruneMissingFiles:
    def test_removes_only_dead_path_rows(self, store: GraphStore, tmp_path: Path) -> None:
        real = tmp_path / "real.pdf"
        real.write_text("x")
        keep = _add_file(store, str(real), "media", "photos_other")
        drop = _add_file(store, "/nonexistent/gone.pdf", "business", "clients")

        result = store.prune_missing_files()

        assert result["removed"] == 1
        assert result["files"][0]["file_id"] == drop
        assert store.get_file(file_id=keep) is not None
        assert store.get_file(file_id=drop) is None
        # dropped row's category edge decremented; kept row's untouched
        assert _file_count(store, "business/clients") == 0
        assert _file_count(store, "media/photos_other") == 1

    def test_prefers_current_path_over_original(self, store: GraphStore, tmp_path: Path) -> None:
        organized = tmp_path / "organized.pdf"
        organized.write_text("x")
        file_id = _add_file(store, "/nonexistent/orig.pdf", "media", "photos_other")
        store.update_file_status(file_id, FileStatus.ORGANIZED, destination=str(organized))

        result = store.prune_missing_files()

        assert result["removed"] == 0
        assert store.get_file(file_id=file_id) is not None

    def test_deletes_cost_and_schema_children(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/nonexistent/a.pdf", "media", "photos_other")
        session = store.get_session()
        from src.storage.models import CostRecord, SchemaMetadata

        session.add(
            CostRecord(file_id=file_id, feature_name="ocr", processing_time_sec=0.1, cost=0.01)
        )
        session.add(
            SchemaMetadata(
                file_id=file_id, schema_type="ImageObject", schema_json={"@type": "ImageObject"}
            )
        )
        session.commit()
        session.close()

        result = store.prune_missing_files()

        assert result["removed"] == 1
        assert store.get_file(file_id=file_id) is None

    def test_deletes_key_value_store_associations(self, store: GraphStore) -> None:
        from src.storage.models import KeyValueStore

        file_id = _add_file(store, "/nonexistent/a.pdf", "media", "photos_other")
        session = store.get_session()
        session.add(
            KeyValueStore(namespace="cache", key="ocr_result", value="text", file_id=file_id)
        )
        session.commit()
        session.close()

        result = store.prune_missing_files()

        assert result["removed"] == 1
        assert store.get_file(file_id=file_id) is None
        session = store.get_session()
        kv_rows = session.query(KeyValueStore).filter(KeyValueStore.file_id == file_id).all()
        session.close()
        assert kv_rows == []

    def test_dry_run_reports_without_deleting(self, store: GraphStore) -> None:
        file_id = _add_file(store, "/nonexistent/a.pdf", "business", "clients")

        result = store.prune_missing_files(dry_run=True)

        assert result["removed"] == 1
        assert store.get_file(file_id=file_id) is not None


class TestReconcileCli:
    def _run(self, db_path: str, **kwargs) -> None:
        from src.cli import cmd_reconcile

        ns = argparse.Namespace(
            set_category=None,
            subcategory=None,
            prune_missing=False,
            backfill_categories=False,
            base_path="~/Documents",
            db_path=db_path,
            apply=False,
        )
        ns.__dict__.update(kwargs)
        cmd_reconcile(ns)

    def test_noop_exits_two(self, store: GraphStore, db_path: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            self._run(db_path)
        assert excinfo.value.code == 2

    def test_set_category_dry_run(self, store: GraphStore, db_path: str, capsys) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "business", "clients")

        self._run(db_path, set_category=[file_id, "legal"])

        out = capsys.readouterr().out
        assert "[DRY RUN]" in out and "business/clients] -> legal" in out
        assert _categories(store, file_id) == ["business/clients"]

    def test_apply_writes_and_backs_up(self, store: GraphStore, db_path: str, capsys) -> None:
        file_id = _add_file(store, "/tmp/a.pdf", "business", "clients")

        self._run(db_path, set_category=[file_id, "legal"], apply=True)

        out = capsys.readouterr().out
        assert "[APPLIED]" in out and "Backed up database" in out
        assert _categories(store, file_id) == ["legal"]
        assert list(Path(db_path).parent.glob("graph.db.bak-*"))

    def test_prune_missing_apply(self, store: GraphStore, db_path: str, capsys) -> None:
        file_id = _add_file(store, "/nonexistent/a.pdf", "business", "clients")

        self._run(db_path, prune_missing=True, apply=True)

        out = capsys.readouterr().out
        assert "prune-missing: 1 stale file row(s)" in out
        assert store.get_file(file_id=file_id) is None

    def test_set_category_unknown_file_exits_one(self, store: GraphStore, db_path: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            self._run(db_path, set_category=["no-such-file", "legal"])
        assert excinfo.value.code == 1
