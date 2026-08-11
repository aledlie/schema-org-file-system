"""
Unit tests for SchemaOrgExporter.

Covers: export_to_file, export_to_ndjson, export_with_graph,
        get_graph_document, and export_entities_filtered.
Uses tmp_path fixture and a seeded in-memory SQLite session.
"""

import json
import sys
from pathlib import Path

from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add src/ to sys.path so storage.* modules resolve without triggering src/__init__.py
_SRC_DIR = Path(__file__).parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from storage.models import Base, File, Category, Company, Person, Location  # noqa: E402
from storage.schema_org_exporter import SchemaOrgExporter, SCHEMA_ORG_CONTEXT  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Iterator[Session]:
    """In-memory SQLite session, tables pre-created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_session(db_session: Session) -> Session:
    """Session pre-populated with one of each entity type."""
    file_ = File(
        id="aabbcc001",
        filename="report.pdf",
        original_path="/docs/report.pdf",
        mime_type="application/pdf",
        file_size=20480,
        canonical_id="urn:sha256:aabbcc001",
    )
    category = Category(
        name="Finance",
        canonical_id="caf00001-0000-0000-0000-000000000001",
        full_path="Finance",
        level=0,
    )
    company = Company(
        name="Acme Corp",
        canonical_id="cac00001-0000-0000-0000-000000000001",
        normalized_name="acme corp",
    )
    person = Person(
        name="Jane Doe",
        canonical_id="cap00001-0000-0000-0000-000000000001",
        normalized_name="jane doe",
        email="jane@example.com",
    )
    location = Location(
        name="New York",
        canonical_id="cal00001-0000-0000-0000-000000000001",
        city="New York",
    )
    db_session.add_all([file_, category, company, person, location])
    db_session.commit()
    return db_session


@pytest.fixture
def exporter(seeded_session: Session) -> SchemaOrgExporter:
    return SchemaOrgExporter(seeded_session)


# ---------------------------------------------------------------------------
# export_to_file
# ---------------------------------------------------------------------------


class TestExportToFile:
    def test_creates_file(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        count = exporter.export_to_file(out)
        assert out.exists()
        assert count == 5

    def test_output_is_json_list(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        exporter.export_to_file(out)
        data = json.loads(out.read_text())
        assert isinstance(data, list)

    def test_all_records_have_context_type_id(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        exporter.export_to_file(out)
        records = json.loads(out.read_text())
        for rec in records:
            assert rec["@context"] == SCHEMA_ORG_CONTEXT, f"missing @context in {rec}"
            assert "@type" in rec, f"missing @type in {rec}"
            assert "@id" in rec, f"missing @id in {rec}"

    def test_pretty_print_is_default(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        exporter.export_to_file(out, pretty=True)
        raw = out.read_text()
        assert "\n" in raw, "expected indented (pretty) output"

    def test_compact_output_when_pretty_false(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        exporter.export_to_file(out, pretty=False)
        raw = out.read_text()
        assert "\n" not in raw.strip(), "expected single-line compact output"

    def test_filter_to_single_entity_class(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "files_only.json"
        count = exporter.export_to_file(out, entity_classes=[File])
        assert count == 1
        records = json.loads(out.read_text())
        assert all(
            rec["@type"]
            in (
                "DigitalDocument",
                "ImageObject",
                "VideoObject",
                "AudioObject",
                "WebPage",
                "SoftwareSourceCode",
            )
            for rec in records
        )

    def test_returns_zero_for_empty_db(self, db_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(db_session)
        out = tmp_path / "empty.json"
        count = exporter.export_to_file(out)
        assert count == 0
        assert json.loads(out.read_text()) == []

    def test_file_record_fields(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        file_rec = records[0]
        assert file_rec["name"] == "report.pdf"
        assert file_rec["encodingFormat"] == "application/pdf"
        assert file_rec["contentSize"] == "20480"


# ---------------------------------------------------------------------------
# export_to_ndjson
# ---------------------------------------------------------------------------


class TestExportToNdjson:
    def test_creates_file(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.ndjson"
        count = exporter.export_to_ndjson(out)
        assert out.exists()
        assert count == 5

    def test_one_json_object_per_line(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.ndjson"
        exporter.export_to_ndjson(out)
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
        assert len(lines) == 5
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)

    def test_each_line_has_required_keys(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.ndjson"
        exporter.export_to_ndjson(out)
        for line in out.read_text().splitlines():
            obj = json.loads(line)
            assert "@context" in obj
            assert "@type" in obj
            assert "@id" in obj

    def test_no_embedded_newlines_in_records(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "export.ndjson"
        exporter.export_to_ndjson(out)
        for line in out.read_text().splitlines():
            assert line.count("{") >= 1, "each line should be a complete JSON object"

    def test_empty_db_produces_empty_file(self, db_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(db_session)
        out = tmp_path / "empty.ndjson"
        count = exporter.export_to_ndjson(out)
        assert count == 0
        assert out.read_text() == ""

    def test_filtered_export(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "people.ndjson"
        count = exporter.export_to_ndjson(out, entity_classes=[Person])
        assert count == 1
        obj = json.loads(out.read_text().strip())
        assert obj["@type"] == "Person"
        assert obj["name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# export_with_graph
# ---------------------------------------------------------------------------


class TestExportWithGraph:
    def test_creates_file(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        count = exporter.export_with_graph(out)
        assert out.exists()
        assert count == 5

    def test_graph_document_structure(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        assert doc["@context"] == SCHEMA_ORG_CONTEXT
        assert "@graph" in doc
        assert isinstance(doc["@graph"], list)

    def test_graph_nodes_omit_context(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        for node in doc["@graph"]:
            assert "@context" not in node, "node-level @context should be omitted in @graph"

    def test_graph_node_count(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        assert len(doc["@graph"]) == 5

    def test_empty_db_graph_has_empty_list(self, db_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(db_session)
        out = tmp_path / "empty_graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        assert doc["@graph"] == []


# ---------------------------------------------------------------------------
# get_graph_document
# ---------------------------------------------------------------------------


class TestGetGraphDocument:
    def test_returns_dict_with_required_keys(self, exporter: SchemaOrgExporter):
        doc = exporter.get_graph_document()
        assert "@context" in doc
        assert "@graph" in doc

    def test_context_is_schema_org(self, exporter: SchemaOrgExporter):
        doc = exporter.get_graph_document()
        assert doc["@context"] == SCHEMA_ORG_CONTEXT

    def test_graph_has_correct_entity_count(self, exporter: SchemaOrgExporter):
        doc = exporter.get_graph_document()
        assert len(doc["@graph"]) == 5

    def test_filtered_by_entity_class(self, exporter: SchemaOrgExporter):
        doc = exporter.get_graph_document(entity_classes=[Company])
        assert len(doc["@graph"]) == 1
        assert doc["@graph"][0]["@type"] == "Organization"

    def test_graph_is_json_serializable(self, exporter: SchemaOrgExporter):
        doc = exporter.get_graph_document()
        serialized = json.dumps(doc)
        parsed = json.loads(serialized)
        assert len(parsed["@graph"]) == 5


# ---------------------------------------------------------------------------
# export_entities_filtered
# ---------------------------------------------------------------------------


class TestExportEntitiesFiltered:
    def test_export_subset_by_pk(self, seeded_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(seeded_session)

        # Add a second company
        extra = Company(
            name="Beta Corp",
            canonical_id="cac00002-0000-0000-0000-000000000002",
            normalized_name="beta corp",
        )
        seeded_session.add(extra)
        seeded_session.commit()

        companies = seeded_session.query(Company).all()
        first_id = companies[0].id

        out = tmp_path / "filtered.json"
        count = exporter.export_entities_filtered(out, Company, [first_id])
        assert count == 1
        records = json.loads(out.read_text())
        assert len(records) == 1

    def test_empty_id_list_returns_empty(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "empty_filtered.json"
        count = exporter.export_entities_filtered(out, File, [])
        assert count == 0
        assert json.loads(out.read_text()) == []

    def test_output_records_have_schema_org_fields(self, seeded_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(seeded_session)
        category = seeded_session.query(Category).first()
        out = tmp_path / "cat.json"
        exporter.export_entities_filtered(out, Category, [category.id])
        records = json.loads(out.read_text())
        assert records[0]["@type"] == "DefinedTerm"
        assert records[0]["name"] == "Finance"
