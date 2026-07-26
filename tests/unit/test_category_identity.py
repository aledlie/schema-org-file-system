"""Category identity is ``full_path``, not ``name``.

The taxonomy reuses leaf names across parents (``other`` under 15 categories),
so a UNIQUE index on ``categories.name`` let only the first claimant exist:
every later ``(category, subcategory)`` sharing the leaf hit an IntegrityError
that ``get_or_create_category`` swallowed into ``None``, and
``add_file_to_category`` then created **no edge at all** — silently persisting
files with no category (26% of rows on the 2026-07-26 audit).

Covers the fixed model/store behaviour and
``src.storage.category_migration`` (legacy-shaped databases).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.storage.category_migration import (
    canonical_id_for,
    run_category_migration,
)
from src.organizers.category_config import build_path_to_category_map
from src.organizers.content_organizer import ContentOrganizer
from src.storage.graph_store import GraphStore
from src.storage.models import File

# Distinct categories that share the leaf name "other" — the exact shape that
# used to collide on the UNIQUE name index.
COLLIDING_PAIRS = [("media", "other"), ("legal", "other"), ("medical", "other")]


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(str(tmp_path / "graph.db"))


@contextmanager
def session_scope(store: GraphStore):
    """Mirror tests/unit/test_graph_store_operations.py: keep ORM objects bound."""
    session = store.get_session()
    try:
        yield session
    finally:
        session.close()


def _add_file(store: GraphStore, path: str) -> str:
    """Add a file and return its id (a plain string, safe after detach)."""
    with session_scope(store) as session:
        file = store.add_file(original_path=path, filename=Path(path).name, session=session)
        file_id = file.id
        session.commit()
        return file_id


class TestRepeatedLeafNames:
    def test_all_colliding_subcategories_are_created(self, store: GraphStore) -> None:
        with session_scope(store) as session:
            created = []
            for parent, leaf in COLLIDING_PAIRS:
                store.get_or_create_category(parent, session=session)
                category = store.get_or_create_category(leaf, parent, session=session)
                assert category is not None, f"{parent}/{leaf} was dropped"
                created.append(category.full_path)
            assert created == [f"{p}/{leaf}" for p, leaf in COLLIDING_PAIRS]

    def test_each_colliding_file_gets_its_category_edge(self, store: GraphStore) -> None:
        for index, (parent, leaf) in enumerate(COLLIDING_PAIRS):
            file_id = _add_file(store, f"/tmp/doc{index}.pdf")
            assert store.add_file_to_category(file_id, parent, leaf) is True
            with session_scope(store) as session:
                file = session.query(File).filter(File.id == file_id).first()
                assert file is not None
                assert [c.full_path for c in file.categories] == [f"{parent}/{leaf}"]

    def test_canonical_ids_are_distinct_and_derived_from_full_path(self, store: GraphStore) -> None:
        with session_scope(store) as session:
            ids = {}
            for parent, leaf in COLLIDING_PAIRS:
                store.get_or_create_category(parent, session=session)
                category = store.get_or_create_category(leaf, parent, session=session)
                assert category is not None
                assert category.canonical_id == canonical_id_for(category.full_path)
                ids[category.full_path] = category.canonical_id
            assert len(set(ids.values())) == len(COLLIDING_PAIRS), "canonical ids collided"

    def test_idempotent_lookup_returns_the_same_row(self, store: GraphStore) -> None:
        with session_scope(store) as session:
            store.get_or_create_category("media", session=session)
            first = store.get_or_create_category("other", "media", session=session)
            second = store.get_or_create_category("other", "media", session=session)
            assert first is not None and second is not None
            assert first.id == second.id

    def test_parent_resolved_by_full_path_not_name(self, store: GraphStore) -> None:
        """A leaf sharing a name with a root must not be adopted as the parent."""
        with session_scope(store) as session:
            # 'legal' exists both as a root category and as personal/legal.
            root_legal = store.get_or_create_category("legal", session=session)
            store.get_or_create_category("personal", session=session)
            personal_legal = store.get_or_create_category("legal", "personal", session=session)
            assert personal_legal is not None
            assert personal_legal.full_path == "personal/legal"

            # A child of the ROOT legal must parent to the root, not to
            # personal/legal (the old name-based lookup could pick either).
            contracts = store.get_or_create_category("contracts", "legal", session=session)
            assert contracts is not None
            assert contracts.full_path == "legal/contracts"
            assert root_legal is not None
            assert contracts.parent_id == root_legal.id


class TestCategoryMigration:
    @pytest.fixture
    def legacy_db_path(self, tmp_path: Path) -> str:
        """A database with the pre-fix index shape: name UNIQUE, full_path plain."""
        db_path = str(tmp_path / "legacy.db")
        GraphStore(db_path)  # modern schema
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            DROP INDEX IF EXISTS ix_categories_name;
            DROP INDEX IF EXISTS ix_categories_full_path;
            CREATE UNIQUE INDEX ix_categories_name ON categories (name);
            CREATE INDEX ix_categories_full_path ON categories (full_path);
            INSERT INTO categories (name, canonical_id, full_path, level)
                VALUES ('other', 'stale-canonical-id', 'organization/other', 1);
            """)
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def _index_sql(db_path: str, index: str) -> str:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index,)
            ).fetchone()
            return (row[0] or "") if row else ""
        finally:
            conn.close()

    def test_dry_run_changes_nothing(self, legacy_db_path: str) -> None:
        stats = run_category_migration(legacy_db_path, dry_run=True)
        assert stats["indexes_rebuilt"] == 1
        assert "UNIQUE" in self._index_sql(legacy_db_path, "ix_categories_name")

    def test_migration_swaps_the_indexes(self, legacy_db_path: str) -> None:
        run_category_migration(legacy_db_path, dry_run=False)
        assert "UNIQUE" not in self._index_sql(legacy_db_path, "ix_categories_name").upper()
        assert "UNIQUE" in self._index_sql(legacy_db_path, "ix_categories_full_path").upper()

    def test_migration_realigns_canonical_ids(self, legacy_db_path: str) -> None:
        stats = run_category_migration(legacy_db_path, dry_run=False)
        assert stats["canonical_ids_realigned"] >= 1
        conn = sqlite3.connect(legacy_db_path)
        try:
            canonical = conn.execute(
                "SELECT canonical_id FROM categories WHERE full_path='organization/other'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert canonical == canonical_id_for("organization/other")

    def test_migration_is_idempotent(self, legacy_db_path: str) -> None:
        run_category_migration(legacy_db_path, dry_run=False)
        again = run_category_migration(legacy_db_path, dry_run=False)
        assert again.get("indexes_rebuilt", 0) == 0
        assert again.get("canonical_ids_realigned", 0) == 0

    def test_colliding_names_work_after_migration(self, legacy_db_path: str) -> None:
        run_category_migration(legacy_db_path, dry_run=False)
        store = GraphStore(legacy_db_path)
        with session_scope(store) as session:
            # 'other' is already taken by organization/other in this database.
            store.get_or_create_category("media", session=session)
            category = store.get_or_create_category("other", "media", session=session)
            assert category is not None
            assert category.full_path == "media/other"

    def test_aborts_on_duplicate_full_paths(self, legacy_db_path: str) -> None:
        conn = sqlite3.connect(legacy_db_path)
        conn.execute(
            "INSERT INTO categories (name, canonical_id, full_path, level) "
            "VALUES ('other_dup', 'dup-id', 'organization/other', 1)"
        )
        conn.commit()
        conn.close()
        stats = run_category_migration(legacy_db_path, dry_run=False)
        assert stats["duplicate_full_paths"] == 1
        assert stats.get("indexes_rebuilt", 0) == 0
        # untouched: the UNIQUE name index is still in place
        assert "UNIQUE" in self._index_sql(legacy_db_path, "ix_categories_name")

    def test_reports_files_without_category(self, legacy_db_path: str) -> None:
        store = GraphStore(legacy_db_path)
        _add_file(store, "/tmp/orphan.pdf")
        stats = run_category_migration(legacy_db_path, dry_run=True)
        assert stats["files_without_category"] == 1

    def test_missing_database_reports_error(self, tmp_path: Path) -> None:
        stats = run_category_migration(str(tmp_path / "nope.db"), dry_run=True)
        assert stats == {"error": "Database not found"}


class TestPathToCategoryMap:
    def test_reverses_flat_and_nested_leaves(self) -> None:
        reverse = build_path_to_category_map()
        assert reverse["Technical/Other"] == ("technical", "other")
        assert reverse["Medical/BloodTest"] == ("medical", "bloodtest")
        # nested media forms collapse to the underscored subcategory
        assert reverse["Media/Photos/Social"] == ("media", "photos_social")
        assert reverse["Media/Photos/Screenshots/Browser"] == (
            "media",
            "photos_screenshots_browser",
        )
        assert reverse["Media/Interiors"] == ("media", "interiors_other")

    def test_category_with_no_subcategories_maps_to_none(self) -> None:
        assert build_path_to_category_map()["Uncategorized"] == ("uncategorized", None)

    def test_recovered_pairs_round_trip_through_the_taxonomy(self, tmp_path: Path) -> None:
        """Every reversed pair must resolve back to the path it came from."""
        base = tmp_path / "Documents"
        organizer = ContentOrganizer(base_path=base, content_classifier=None)
        for path, (category, subcategory) in build_path_to_category_map().items():
            if subcategory is None:
                continue
            resolved = organizer.get_destination_path(Path("/in/f.bin"), category, subcategory)
            # Organization/Events append an entity name, so compare the prefix.
            assert str(resolved).startswith(f"{base}/{path}"), (path, category, subcategory)


class TestBackfillMissingCategories:
    def test_attaches_edge_derived_from_the_on_disk_folder(
        self, store: GraphStore, tmp_path: Path
    ) -> None:
        base = tmp_path / "Documents"
        dest = base / "Medical" / "BloodTest"
        dest.mkdir(parents=True)
        target = dest / "labs.pdf"
        target.write_text("x")
        file_id = _add_file(store, str(target))
        store.add_file(original_path=str(target), filename="labs.pdf", current_path=str(target))

        summary = store.backfill_missing_categories(base_path=base, dry_run=False)
        assert summary["attached"] == 1
        assert summary["unresolved"] == 0
        with session_scope(store) as session:
            file = session.query(File).filter(File.id == file_id).first()
            assert file is not None
            assert [c.full_path for c in file.categories] == ["medical/bloodtest"]

    def test_dry_run_attaches_nothing(self, store: GraphStore, tmp_path: Path) -> None:
        base = tmp_path / "Documents"
        dest = base / "Technical" / "Other"
        dest.mkdir(parents=True)
        target = dest / "notes.txt"
        target.write_text("x")
        file_id = _add_file(store, str(target))
        store.add_file(original_path=str(target), filename="notes.txt", current_path=str(target))

        summary = store.backfill_missing_categories(base_path=base, dry_run=True)
        assert summary["attached"] == 1
        with session_scope(store) as session:
            file = session.query(File).filter(File.id == file_id).first()
            assert file is not None
            assert file.categories == []

    def test_entity_named_folder_is_unresolved_not_guessed(
        self, store: GraphStore, tmp_path: Path
    ) -> None:
        base = tmp_path / "Documents"
        dest = base / "Events" / "Burning Flipside"
        dest.mkdir(parents=True)
        target = dest / "map.pdf"
        target.write_text("x")
        file_id = _add_file(store, str(target))
        store.add_file(original_path=str(target), filename="map.pdf", current_path=str(target))

        summary = store.backfill_missing_categories(base_path=base, dry_run=False)
        assert summary["unresolved"] == 1
        assert summary["attached"] == 0
        with session_scope(store) as session:
            file = session.query(File).filter(File.id == file_id).first()
            assert file is not None
            assert file.categories == []

    def test_files_already_categorized_are_untouched(
        self, store: GraphStore, tmp_path: Path
    ) -> None:
        base = tmp_path / "Documents"
        dest = base / "Technical" / "Other"
        dest.mkdir(parents=True)
        target = dest / "kept.txt"
        target.write_text("x")
        file_id = _add_file(store, str(target))
        store.add_file(original_path=str(target), filename="kept.txt", current_path=str(target))
        store.add_file_to_category(file_id, "legal", "contracts")

        summary = store.backfill_missing_categories(base_path=base, dry_run=False)
        assert summary["orphaned"] == 0
        with session_scope(store) as session:
            file = session.query(File).filter(File.id == file_id).first()
            assert file is not None
            assert [c.full_path for c in file.categories] == ["legal/contracts"]
