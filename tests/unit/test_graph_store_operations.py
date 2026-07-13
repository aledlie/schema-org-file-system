"""Functional tests for GraphStore's file/category/company/location/
relationship/session/statistics/search operations (the areas not covered by
tests/unit/test_graph_store_prune.py).

GraphStore methods commit-and-close their own session, which expires and
detaches returned ORM objects (see the note in test_person_migration.py).
Helpers here therefore run store calls inside an explicitly held session and
hand plain values (ids) back to the tests.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from src.storage.graph_store import GraphStore
from src.storage.models import (
    Company,
    CostRecord,
    FileStatus,
    Location,
    OrganizationSession,
    RelationshipType,
)


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(str(tmp_path / "graph.db"))


@contextmanager
def session_scope(store: GraphStore):
    session = store.get_session()
    try:
        yield session
    finally:
        session.close()


def _add_file(store: GraphStore, path: str, **kwargs) -> str:
    """Add a file and return its id (a plain string, safe after detach)."""
    with session_scope(store) as session:
        file = store.add_file(
            original_path=path, filename=Path(path).name, session=session, **kwargs
        )
        return file.id


class TestFileOperations:
    def test_add_file_creates_with_derived_fields(self, store: GraphStore):
        with session_scope(store) as session:
            file = store.add_file(
                original_path="/tmp/report.PDF", filename="report.PDF", session=session
            )
            assert file.id
            assert file.canonical_id
            assert file.file_extension == ".pdf"
            assert file.status == FileStatus.PENDING

    def test_add_file_same_path_updates_existing(self, store: GraphStore):
        first_id = _add_file(store, "/tmp/report.pdf")
        second_id = _add_file(store, "/tmp/report.pdf", extracted_text="updated")

        assert second_id == first_id
        assert store.get_file(file_id=first_id).extracted_text == "updated"

    def test_get_file_by_id_and_by_path(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/report.pdf")

        assert store.get_file(file_id=file_id).id == file_id
        assert store.get_file(path="/tmp/report.pdf").id == file_id
        assert store.get_file(path="/tmp/missing.pdf") is None
        assert store.get_file() is None

    def test_get_files_filters(self, store: GraphStore):
        pdf_id = _add_file(store, "/tmp/a.pdf")
        png_id = _add_file(store, "/tmp/b.png")
        store.update_file_status(pdf_id, FileStatus.ORGANIZED, destination="/docs/a.pdf")
        store.add_file_to_category(pdf_id, "financial")
        store.add_file_to_company(pdf_id, "Acme Corp")

        assert [f.id for f in store.get_files(extension=".PNG")] == [png_id]
        assert [f.id for f in store.get_files(status=FileStatus.ORGANIZED)] == [pdf_id]
        assert [f.id for f in store.get_files(category="financial")] == [pdf_id]
        assert [f.id for f in store.get_files(company="Acme Corp")] == [pdf_id]

    def test_get_files_limit_and_offset(self, store: GraphStore):
        for i in range(3):
            _add_file(store, f"/tmp/f{i}.txt")

        assert len(store.get_files(limit=2)) == 2
        assert len(store.get_files(limit=10, offset=2)) == 1

    def test_update_file_status(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/a.pdf")

        assert store.update_file_status(
            file_id, FileStatus.ORGANIZED, destination="/docs/a.pdf", reason="matched"
        ) is True

        updated = store.get_file(file_id=file_id)
        assert updated.status == FileStatus.ORGANIZED
        assert updated.current_path == "/docs/a.pdf"
        assert updated.organization_reason == "matched"
        assert updated.organized_at is not None

    def test_update_file_status_missing_file(self, store: GraphStore):
        assert store.update_file_status("no-such-id", FileStatus.ORGANIZED) is False


class TestCategoryOperations:
    def test_get_or_create_category_root_and_dedup(self, store: GraphStore):
        with session_scope(store) as session:
            first = store.get_or_create_category("financial", session=session)
            second = store.get_or_create_category("financial", session=session)

            assert first.id == second.id
            assert first.level == 0
            assert first.full_path == "financial"

    def test_subcategory_gets_parent_and_level(self, store: GraphStore):
        with session_scope(store) as session:
            store.get_or_create_category("financial", session=session)
            sub = store.get_or_create_category("tax", parent_name="financial", session=session)

            assert sub.full_path == "financial/tax"
            assert sub.level == 1
            assert sub.parent_id is not None

    def test_add_file_to_category_with_subcategory(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/w2.pdf")

        assert store.add_file_to_category(file_id, "financial", "tax") is True

        with session_scope(store) as session:
            refreshed = store.get_file(file_id=file_id, session=session)
            assert {c.full_path for c in refreshed.categories} == {"financial/tax"}
            assert refreshed.categories[0].file_count == 1

    def test_add_file_to_category_duplicate_is_noop(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/w2.pdf")
        store.add_file_to_category(file_id, "financial")
        store.add_file_to_category(file_id, "financial")

        with session_scope(store) as session:
            refreshed = store.get_file(file_id=file_id, session=session)
            assert len(refreshed.categories) == 1
            assert refreshed.categories[0].file_count == 1

    def test_add_file_to_category_missing_file(self, store: GraphStore):
        assert store.add_file_to_category("no-such-id", "financial") is False

    def test_get_category_tree_nests_subcategories(self, store: GraphStore):
        with session_scope(store) as session:
            store.get_or_create_category("financial", session=session)
            store.get_or_create_category("tax", parent_name="financial", session=session)
            store.get_or_create_category("media", session=session)
            session.commit()

        tree = store.get_category_tree()

        roots = {node['name']: node for node in tree}
        assert set(roots) == {"financial", "media"}
        assert [sub['name'] for sub in roots['financial']['subcategories']] == ["tax"]
        assert roots['media']['subcategories'] == []


class TestCompanyOperations:
    def test_get_or_create_company_dedups_on_normalized_name(self, store: GraphStore):
        with session_scope(store) as session:
            first = store.get_or_create_company("Acme Corp", session=session)
            second = store.get_or_create_company("  ACME CORP ", session=session)

            assert first.id == second.id
            assert first.canonical_id

    def test_add_file_to_company_updates_stats(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/invoice.pdf")

        assert store.add_file_to_company(file_id, "Acme Corp", context="invoice") is True
        assert store.add_file_to_company(file_id, "Acme Corp") is True  # duplicate no-op

        with session_scope(store) as session:
            company = session.query(Company).one()
            assert company.file_count == 1
            assert company.last_seen is not None

    def test_add_file_to_company_missing_file(self, store: GraphStore):
        assert store.add_file_to_company("no-such-id", "Acme Corp") is False


class TestLocationOperations:
    def test_get_or_create_location_dedups_by_name(self, store: GraphStore):
        with session_scope(store) as session:
            first = store.get_or_create_location("Austin", session=session)
            second = store.get_or_create_location("Austin", session=session)

            assert first.id == second.id

    def test_get_or_create_location_dedups_by_nearby_coordinates(self, store: GraphStore):
        with session_scope(store) as session:
            first = store.get_or_create_location(
                "Austin", latitude=30.2672, longitude=-97.7431, session=session
            )
            nearby = store.get_or_create_location(
                "Austin Downtown", latitude=30.2673, longitude=-97.7430, session=session
            )

            assert nearby.id == first.id
            assert nearby.name == "Austin"
            session.commit()

        with session_scope(store) as session:
            assert session.query(Location).count() == 1

    def test_add_file_to_location(self, store: GraphStore):
        file_id = _add_file(store, "/tmp/photo.jpg")

        assert store.add_file_to_location(
            file_id, "Austin", location_type="captured_at",
            latitude=30.2672, longitude=-97.7431, city="Austin", state="TX",
        ) is True

        with session_scope(store) as session:
            refreshed = store.get_file(file_id=file_id, session=session)
            assert [loc.name for loc in refreshed.locations] == ["Austin"]
            assert refreshed.locations[0].file_count == 1

    def test_add_file_to_location_missing_file(self, store: GraphStore):
        assert store.add_file_to_location("no-such-id", "Austin") is False


def _add_relationship(store: GraphStore, source_id: str, target_id: str,
                      rel_type: RelationshipType, confidence: float = 1.0):
    """Create a relationship and return (id, confidence) as plain values."""
    with session_scope(store) as session:
        rel = store.add_relationship(
            source_id, target_id, rel_type, confidence=confidence, session=session
        )
        return rel.id, rel.confidence


class TestRelationshipOperations:
    def test_add_relationship_creates_edge(self, store: GraphStore):
        a = _add_file(store, "/tmp/a.pdf")
        b = _add_file(store, "/tmp/b.pdf")

        rel_id, confidence = _add_relationship(
            store, a, b, RelationshipType.DUPLICATE, confidence=0.9
        )

        assert rel_id is not None
        assert confidence == 0.9

    def test_add_relationship_upserts_existing_triple(self, store: GraphStore):
        a = _add_file(store, "/tmp/a.pdf")
        b = _add_file(store, "/tmp/b.pdf")
        first_id, _ = _add_relationship(store, a, b, RelationshipType.SIMILAR, 0.5)
        second_id, second_conf = _add_relationship(store, a, b, RelationshipType.SIMILAR, 0.8)

        assert second_id == first_id
        assert second_conf == 0.8

    def test_find_related_files_traverses_both_directions(self, store: GraphStore):
        a = _add_file(store, "/tmp/a.pdf")
        b = _add_file(store, "/tmp/b.pdf")
        c = _add_file(store, "/tmp/c.pdf")
        _add_relationship(store, a, b, RelationshipType.SIMILAR)
        _add_relationship(store, c, a, RelationshipType.DERIVED)

        related = store.find_related_files(a)

        found = {f.id: rel_type for f, rel_type, _confidence in related}
        assert found == {b: RelationshipType.SIMILAR, c: RelationshipType.DERIVED}

    def test_find_related_files_filters_by_type(self, store: GraphStore):
        a = _add_file(store, "/tmp/a.pdf")
        b = _add_file(store, "/tmp/b.pdf")
        c = _add_file(store, "/tmp/c.pdf")
        _add_relationship(store, a, b, RelationshipType.SIMILAR)
        _add_relationship(store, a, c, RelationshipType.DERIVED)

        related = store.find_related_files(a, relationship_type=RelationshipType.SIMILAR)

        assert [f.id for f, _t, _c in related] == [b]

    def test_find_related_files_depth_two(self, store: GraphStore):
        a = _add_file(store, "/tmp/a.pdf")
        b = _add_file(store, "/tmp/b.pdf")
        c = _add_file(store, "/tmp/c.pdf")
        _add_relationship(store, a, b, RelationshipType.RELATED)
        _add_relationship(store, b, c, RelationshipType.RELATED)

        depth_one = store.find_related_files(a, depth=1)
        depth_two = store.find_related_files(a, depth=2)

        assert {f.id for f, _t, _c in depth_one} == {b}
        assert {f.id for f, _t, _c in depth_two} == {b, c}


class TestDuplicateDetection:
    def test_find_duplicates_groups_by_hash(self, store: GraphStore):
        _add_file(store, "/tmp/a.pdf", content_hash="h1")
        _add_file(store, "/tmp/copy_of_a.pdf", content_hash="h1")
        _add_file(store, "/tmp/unique.pdf", content_hash="h2")

        groups = store.find_duplicates()

        assert len(groups) == 1
        assert {f.content_hash for f in groups[0]} == {"h1"}
        assert len(groups[0]) == 2

    def test_find_duplicates_specific_hash(self, store: GraphStore):
        _add_file(store, "/tmp/a.pdf", content_hash="h1")
        _add_file(store, "/tmp/b.pdf", content_hash="h1")

        assert len(store.find_duplicates(content_hash="h1")) == 1
        assert store.find_duplicates(content_hash="h-none") == []

    def test_find_duplicates_none_when_all_unique(self, store: GraphStore):
        _add_file(store, "/tmp/a.pdf", content_hash="h1")
        assert store.find_duplicates() == []


class TestSessionOperations:
    def test_create_and_complete_session(self, store: GraphStore):
        with session_scope(store) as session:
            org_session = store.create_session(
                source_directories=["/tmp/in"], base_path="/tmp/out",
                dry_run=True, file_limit=100, session=session,
            )
            session_id = org_session.id
            assert org_session.dry_run is True
        assert session_id

        assert store.complete_session(session_id, {
            'total_files': 10, 'organized': 7, 'skipped': 2,
            'errors': 1, 'total_cost': 0.5, 'processing_time': 12.5,
        }) is True

        with session_scope(store) as session:
            row = session.query(OrganizationSession).filter(
                OrganizationSession.id == session_id
            ).one()
            assert row.completed_at is not None
            assert row.total_files == 10
            assert row.organized_count == 7
            assert row.skipped_count == 2
            assert row.error_count == 1

    def test_complete_session_unknown_id(self, store: GraphStore):
        assert store.complete_session("no-such-session", {}) is False


class TestStatistics:
    def test_get_statistics_counts_and_breakdowns(self, store: GraphStore):
        pdf_id = _add_file(store, "/tmp/a.pdf")
        _add_file(store, "/tmp/b.png")
        store.update_file_status(pdf_id, FileStatus.ORGANIZED, destination="/docs/a.pdf")
        store.add_file_to_category(pdf_id, "financial")
        store.add_file_to_company(pdf_id, "Acme Corp")
        with session_scope(store) as session:
            store.create_session(
                source_directories=["/tmp"], base_path="/docs", session=session
            )

        stats = store.get_statistics()

        assert stats['total_files'] == 2
        assert stats['organized_files'] == 1
        assert stats['total_categories'] == 1
        assert stats['total_companies'] == 1
        assert stats['total_sessions'] == 1
        assert stats['categories'] == {"financial": 1}
        assert stats['extensions'] == {".pdf": 1, ".png": 1}

    def test_get_cost_statistics_aggregates_by_feature(self, store: GraphStore):
        with session_scope(store) as session:
            org_session = store.create_session(
                source_directories=["/tmp"], base_path="/docs", session=session
            )
            session_id = org_session.id
            session.add_all([
                CostRecord(session_id=session_id, feature_name="ocr",
                           processing_time_sec=1.0, cost=0.01, success=True),
                CostRecord(session_id=session_id, feature_name="ocr",
                           processing_time_sec=2.0, cost=0.02, success=False),
                CostRecord(session_id=session_id, feature_name="clip",
                           processing_time_sec=0.5, cost=0.005, success=True),
            ])
            session.commit()

        stats = store.get_cost_statistics()
        assert stats['total_records'] == 3
        assert stats['total_cost'] == pytest.approx(0.035)
        assert stats['by_feature']['ocr']['invocations'] == 2
        assert stats['by_feature']['ocr']['success_count'] == 1
        assert stats['by_feature']['ocr']['error_count'] == 1

        ocr_only = store.get_cost_statistics(feature_name="ocr")
        assert ocr_only['total_records'] == 2
        assert store.get_cost_statistics(session_id="no-such")['total_records'] == 0


class TestSearch:
    def test_search_files_by_filename_and_content(self, store: GraphStore):
        named = _add_file(store, "/tmp/tax_return_2025.pdf")
        content = _add_file(store, "/tmp/scan001.pdf", extracted_text="Annual tax summary")
        _add_file(store, "/tmp/photo.jpg", extracted_text="a beach")

        both = {f.id for f in store.search_files("tax")}
        assert both == {named, content}

        filename_only = {f.id for f in store.search_files("tax", search_content=False)}
        assert filename_only == {named}

        content_only = {f.id for f in store.search_files("tax", search_filename=False)}
        assert content_only == {content}

    def test_search_files_no_fields_returns_empty(self, store: GraphStore):
        _add_file(store, "/tmp/tax.pdf")
        assert store.search_files("tax", search_content=False, search_filename=False) == []

    def test_search_files_respects_limit(self, store: GraphStore):
        for i in range(3):
            _add_file(store, f"/tmp/tax_{i}.pdf")
        assert len(store.search_files("tax", limit=2)) == 2

    def test_search_by_location_bounding_box(self, store: GraphStore):
        near = _add_file(store, "/tmp/near.jpg",
                         gps_latitude=30.2672, gps_longitude=-97.7431)
        _add_file(store, "/tmp/far.jpg",
                  gps_latitude=40.7128, gps_longitude=-74.0060)
        _add_file(store, "/tmp/no_gps.jpg")

        results = store.search_by_location(30.2672, -97.7431, radius_km=10)

        assert [f.id for f in results] == [near]

    def test_search_by_location_longitude_offset_within_radius(self, store: GraphStore):
        # ~5 km east of center at latitude 30 (1 deg lon ~ 96 km there).
        # Regression: the old formula divided by abs(latitude) instead of
        # cos(latitude), shrinking the longitude box ~35x and missing this.
        east = _add_file(store, "/tmp/east.jpg",
                         gps_latitude=30.0, gps_longitude=-97.95)
        _add_file(store, "/tmp/too_far_east.jpg",
                  gps_latitude=30.0, gps_longitude=-97.70)  # ~29 km east

        results = store.search_by_location(30.0, -98.0, radius_km=10)

        assert [f.id for f in results] == [east]
