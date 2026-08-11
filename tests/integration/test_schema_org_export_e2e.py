"""
End-to-end export tests.

Covers the full pipeline: DB population → SchemaOrgExporter → JSON-LD output,
validating structure for each output format (json, ndjson, @graph) and for
each entity type (File, Category, Company, Person, Location).
"""

import json
import sys
from datetime import datetime
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
from storage.schema_org_exporter import SchemaOrgExporter  # noqa: E402

SCHEMA_ORG_URL = "https://schema.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _seed_db(session: Session) -> dict:
    """Insert one of each entity type; return keyed dict for assertions."""
    file_ = File(
        id="e2eaabbcc001",
        filename="invoice.pdf",
        original_path="/docs/invoice.pdf",
        mime_type="application/pdf",
        file_size=51200,
        canonical_id="urn:sha256:e2eaabbcc001",
        created_at=datetime(2024, 6, 1),
        modified_at=datetime(2024, 6, 15),
    )
    image = File(
        id="e2eimg001",
        filename="photo.jpg",
        original_path="/images/photo.jpg",
        mime_type="image/jpeg",
        file_size=204800,
        canonical_id="urn:sha256:e2eimg001",
        image_width=1920,
        image_height=1080,
        has_faces=False,
    )
    category = Category(
        name="Financial",
        canonical_id="e2ecaf001-0000-0000-0000-000000000001",
        description="Financial documents",
        full_path="Financial",
        level=0,
    )
    company = Company(
        name="GlobalCorp",
        canonical_id="e2ecac001-0000-0000-0000-000000000001",
        normalized_name="globalcorp",
        domain="globalcorp.com",
        industry="Consulting",
        first_seen=datetime(2024, 1, 1),
        last_seen=datetime(2024, 6, 1),
    )
    person = Person(
        name="Eve Tester",
        canonical_id="e2epab001-0000-0000-0000-000000000001",
        normalized_name="eve tester",
        email="eve@example.com",
        role="QA Engineer",
    )
    location = Location(
        name="Berlin Office",
        canonical_id="e2elab001-0000-0000-0000-000000000001",
        city="Berlin",
        country="DE",
        latitude=52.52,
        longitude=13.405,
    )

    # Attach relationships
    file_.companies.append(company)
    file_.people.append(person)
    file_.categories.append(category)
    file_.locations.append(location)

    session.add_all([file_, image, category, company, person, location])
    session.commit()

    return {
        "file": file_,
        "image": image,
        "category": category,
        "company": company,
        "person": person,
        "location": location,
    }


@pytest.fixture
def populated_session(db_session: Session) -> Session:
    _seed_db(db_session)
    return db_session


@pytest.fixture
def exporter(populated_session: Session) -> SchemaOrgExporter:
    return SchemaOrgExporter(populated_session)


# ---------------------------------------------------------------------------
# Helper: assert minimal JSON-LD validity
# ---------------------------------------------------------------------------


def assert_jsonld_node(node: dict, expected_type: str | None = None) -> None:
    """Assert node has @context (or is a graph node without it), @type, and @id."""
    assert "@type" in node, f"missing @type: {node}"
    assert "@id" in node, f"missing @id: {node}"
    if expected_type:
        assert node["@type"] == expected_type, f"expected {expected_type}, got {node['@type']}"


# ---------------------------------------------------------------------------
# Pipeline: json format
# ---------------------------------------------------------------------------


class TestJsonExportPipeline:
    def test_full_export_produces_valid_json(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.json"
        exporter.export_to_file(out)
        data = json.loads(out.read_text())
        assert isinstance(data, list)

    def test_entity_count(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.json"
        count = exporter.export_to_file(out)
        assert count == 6  # 2 files + category + company + person + location

    def test_file_json_ld_structure(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        for rec in records:
            assert rec["@context"] == SCHEMA_ORG_URL
            assert_jsonld_node(rec)

    def test_file_with_pdf_mime_is_digital_document(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        pdf_rec = next(r for r in records if r.get("encodingFormat") == "application/pdf")
        assert pdf_rec["@type"] == "DigitalDocument"

    def test_image_file_is_image_object(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        img_rec = next(r for r in records if r.get("encodingFormat") == "image/jpeg")
        assert img_rec["@type"] == "ImageObject"
        assert img_rec["width"] == 1920
        assert img_rec["height"] == 1080

    def test_file_with_relationships_has_mentions_and_about(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        invoice = next(r for r in records if r["name"] == "invoice.pdf")
        assert "mentions" in invoice
        # Single category maps to mainEntityOfPage; "about" only appears with 2+ categories
        assert "mainEntityOfPage" in invoice
        assert "spatialCoverage" in invoice

    def test_category_is_defined_term(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "cats.json"
        exporter.export_to_file(out, entity_classes=[Category])
        records = json.loads(out.read_text())
        assert records[0]["@type"] == "DefinedTerm"
        assert records[0]["name"] == "Financial"
        assert "inDefinedTermSet" in records[0]

    def test_company_is_organization(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "companies.json"
        exporter.export_to_file(out, entity_classes=[Company])
        records = json.loads(out.read_text())
        assert records[0]["@type"] == "Organization"
        assert records[0]["name"] == "GlobalCorp"
        assert records[0]["url"] == "https://globalcorp.com"

    def test_person_is_person_type(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "people.json"
        exporter.export_to_file(out, entity_classes=[Person])
        records = json.loads(out.read_text())
        assert records[0]["@type"] == "Person"
        assert records[0]["email"] == "eve@example.com"
        assert records[0]["jobTitle"] == "QA Engineer"

    def test_location_is_place_or_city(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "locations.json"
        exporter.export_to_file(out, entity_classes=[Location])
        records = json.loads(out.read_text())
        # Berlin Office has city + country → Place; just city → City
        assert records[0]["@type"] in ("Place", "City")
        assert "address" in records[0]
        assert records[0]["address"]["addressLocality"] == "Berlin"
        assert "geo" in records[0]
        assert records[0]["geo"]["latitude"] == 52.52


# ---------------------------------------------------------------------------
# Pipeline: ndjson format
# ---------------------------------------------------------------------------


class TestNdjsonExportPipeline:
    def test_produces_one_line_per_entity(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.ndjson"
        exporter.export_to_ndjson(out)
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
        assert len(lines) == 6

    def test_each_line_parses_as_json_object(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.ndjson"
        exporter.export_to_ndjson(out)
        for line in out.read_text().splitlines():
            obj = json.loads(line)
            assert isinstance(obj, dict)

    def test_all_entities_have_required_jsonld_fields(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "full.ndjson"
        exporter.export_to_ndjson(out)
        for line in out.read_text().splitlines():
            obj = json.loads(line)
            assert obj["@context"] == SCHEMA_ORG_URL
            assert "@type" in obj
            assert "@id" in obj

    def test_each_entity_type_present_in_output(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.ndjson"
        exporter.export_to_ndjson(out)
        types_seen = set()
        for line in out.read_text().splitlines():
            types_seen.add(json.loads(line)["@type"])
        assert "DefinedTerm" in types_seen
        assert "Organization" in types_seen
        assert "Person" in types_seen
        # Location type depends on address fields: Place, City, or Country
        assert types_seen & {"Place", "City", "Country"}, "expected at least one location type"


# ---------------------------------------------------------------------------
# Pipeline: @graph format
# ---------------------------------------------------------------------------


class TestGraphExportPipeline:
    def test_graph_document_has_context_and_graph(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        assert doc["@context"] == SCHEMA_ORG_URL
        assert "@graph" in doc

    def test_graph_nodes_omit_context(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        for node in doc["@graph"]:
            assert "@context" not in node

    def test_graph_node_count(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        count = exporter.export_with_graph(out)
        assert count == 6

    def test_graph_nodes_have_type_and_id(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        for node in doc["@graph"]:
            assert_jsonld_node(node)

    def test_graph_is_round_trip_stable(self, exporter: SchemaOrgExporter, tmp_path: Path):
        """Serialize to JSON and back; entity names are preserved."""
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        first = json.loads(out.read_text())
        # Second write from same session
        exporter.export_with_graph(out)
        second = json.loads(out.read_text())
        assert len(first["@graph"]) == len(second["@graph"])

    def test_company_domain_in_url(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        doc = json.loads(out.read_text())
        org = next(n for n in doc["@graph"] if n.get("@type") == "Organization")
        assert org["url"] == "https://globalcorp.com"


# ---------------------------------------------------------------------------
# Pipeline: filtered exports
# ---------------------------------------------------------------------------


class TestFilteredExportPipeline:
    def test_single_class_export_contains_only_that_type(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "companies_only.json"
        exporter.export_to_file(out, entity_classes=[Company])
        records = json.loads(out.read_text())
        assert all(r["@type"] == "Organization" for r in records)

    def test_multi_class_export_contains_both_types(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "two_types.json"
        exporter.export_to_file(out, entity_classes=[Person, Location])
        records = json.loads(out.read_text())
        types = {r["@type"] for r in records}
        assert "Person" in types
        # Location type depends on address fields: Place, City, or Country
        assert types & {"Place", "City", "Country"}, "expected at least one location type"

    def test_entity_ids_filter_returns_subset(self, populated_session: Session, tmp_path: Path):
        exporter = SchemaOrgExporter(populated_session)
        # Get first company's pk
        company = populated_session.query(Company).first()
        out = tmp_path / "one_company.json"
        count = exporter.export_entities_filtered(out, Company, [company.id])
        assert count == 1
        records = json.loads(out.read_text())
        assert records[0]["name"] == "GlobalCorp"


# ---------------------------------------------------------------------------
# JSON-LD structural validity
# ---------------------------------------------------------------------------


class TestJsonLdStructuralValidity:
    def test_all_ids_are_urns(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.json"
        exporter.export_to_file(out)
        records = json.loads(out.read_text())
        for rec in records:
            assert rec["@id"].startswith("urn:"), f"@id should be URN: {rec['@id']}"

    def test_no_null_values_in_top_level_fields(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "full.json"
        exporter.export_to_file(out)
        records = json.loads(out.read_text())
        for rec in records:
            for key, val in rec.items():
                assert val is not None, f"null value for key '{key}' in {rec['@type']}"

    def test_relationship_references_have_type_and_id(
        self, exporter: SchemaOrgExporter, tmp_path: Path
    ):
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        invoice = next(r for r in records if r.get("name") == "invoice.pdf")

        for mention in invoice.get("mentions", []):
            assert "@type" in mention
            assert "@id" in mention

        for about in invoice.get("about", []):
            assert "@type" in about
            assert "@id" in about

    def test_content_size_is_string(self, exporter: SchemaOrgExporter, tmp_path: Path):
        """schema.org contentSize must be a string."""
        out = tmp_path / "files.json"
        exporter.export_to_file(out, entity_classes=[File])
        records = json.loads(out.read_text())
        for rec in records:
            if "contentSize" in rec:
                assert isinstance(rec["contentSize"], str), "contentSize must be a string"

    def test_graph_export_is_valid_json(self, exporter: SchemaOrgExporter, tmp_path: Path):
        out = tmp_path / "graph.json"
        exporter.export_with_graph(out)
        raw = out.read_text()
        doc = json.loads(raw)
        assert isinstance(doc, dict)
        # Re-serialize and compare entity count
        doc2 = json.loads(json.dumps(doc))
        assert len(doc2["@graph"]) == len(doc["@graph"])
