"""
JSON-LD validation tests against the schema.org vocabulary.

Validates that emitted properties are recognized schema.org terms and that
property value types match expected shapes. Uses jsonschema for validation.

Coverage:
- File (ImageObject / VideoObject / DigitalDocument)
- Category (DefinedTerm)
- Company (Organization)
- Person
- Location (Place / City / Country)
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add src/ to sys.path so storage.* modules resolve
_SRC_DIR = Path(__file__).parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from storage.models import Base, File, Category, Company, Person, Location  # noqa: E402

# ---------------------------------------------------------------------------
# JSON Schema definitions for each schema.org type we emit
# ---------------------------------------------------------------------------

# Properties required in every emitted JSON-LD object
_JSONLD_BASE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["@context", "@type", "@id", "name"],
    "properties": {
        "@context": {"type": "string"},
        "@type": {"type": "string"},
        "@id": {"type": "string"},
        "name": {"type": "string"},
    },
}

_FILE_SCHEMA: Dict[str, Any] = {
    **_JSONLD_BASE_SCHEMA,
    "properties": {
        **_JSONLD_BASE_SCHEMA["properties"],
        "dateCreated": {"type": "string"},
        "dateModified": {"type": "string"},
        "datePublished": {"type": "string"},
        "encodingFormat": {"type": "string"},
        "contentSize": {"type": "string"},
        "url": {"type": "string"},
        "text": {"type": "string"},
        "width": {"type": ["integer", "number"]},
        "height": {"type": ["integer", "number"]},
        "hasFaces": {"type": "boolean"},
        "contentLocation": {"type": "object"},
    },
    "additionalProperties": True,
}

_CATEGORY_SCHEMA: Dict[str, Any] = {
    **_JSONLD_BASE_SCHEMA,
    "required": ["@context", "@type", "@id", "name", "definition", "inDefinedTermSet"],
    "properties": {
        **_JSONLD_BASE_SCHEMA["properties"],
        "identifier": {"type": "string"},
        "definition": {"type": "string"},
        "inDefinedTermSet": {"type": "object"},
        "broader": {"type": "object"},
        "narrower": {"type": "array"},
        "fileCount": {"type": "integer"},
        "hierarchyLevel": {"type": "integer"},
    },
    "additionalProperties": True,
}

_COMPANY_SCHEMA: Dict[str, Any] = {
    **_JSONLD_BASE_SCHEMA,
    "properties": {
        **_JSONLD_BASE_SCHEMA["properties"],
        "url": {"type": "string"},
        "knowsAbout": {"type": "string"},
        "dateFounded": {"type": "string"},
        "dateCreated": {"type": "string"},
        "dateModified": {"type": "string"},
        "sameAs": {"type": "array", "items": {"type": "string"}},
        "mentionCount": {"type": "integer"},
    },
    "additionalProperties": True,
}

_PERSON_SCHEMA: Dict[str, Any] = {
    **_JSONLD_BASE_SCHEMA,
    "properties": {
        **_JSONLD_BASE_SCHEMA["properties"],
        "email": {"type": "string"},
        "jobTitle": {"type": "string"},
        "dateCreated": {"type": "string"},
        "dateModified": {"type": "string"},
        "mentionCount": {"type": "integer"},
        "worksFor": {"type": "object"},
        "workLocation": {"type": "object"},
    },
    "additionalProperties": True,
}

_LOCATION_SCHEMA: Dict[str, Any] = {
    **_JSONLD_BASE_SCHEMA,
    "properties": {
        **_JSONLD_BASE_SCHEMA["properties"],
        "address": {"type": "object"},
        "geo": {"type": "object"},
        "geoHash": {"type": "string"},
        "dateCreated": {"type": "string"},
        "mentionCount": {"type": "integer"},
    },
    "additionalProperties": True,
}

# Valid schema.org @type values emitted by our five entity models
_VALID_SCHEMA_ORG_TYPES = {
    "ImageObject",
    "VideoObject",
    "AudioObject",
    "DigitalDocument",
    "WebPage",
    "SoftwareSourceCode",
    "DefinedTerm",
    "Organization",
    "Person",
    "Place",
    "City",
    "Country",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_session() -> Iterator[Session]:
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def image_file(db_session: Session) -> File:
    f = File(
        id="img001",
        filename="photo.jpg",
        original_path="/photos/photo.jpg",
        mime_type="image/jpeg",
        file_size=1024000,
        canonical_id="urn:sha256:img001",
        image_width=1920,
        image_height=1080,
        has_faces=True,
        created_at=datetime(2024, 1, 15),
        modified_at=datetime(2024, 6, 1),
    )
    db_session.add(f)
    db_session.commit()
    return f


@pytest.fixture(scope="module")
def video_file(db_session: Session) -> File:
    f = File(
        id="vid001",
        filename="clip.mp4",
        original_path="/videos/clip.mp4",
        mime_type="video/mp4",
        file_size=50_000_000,
        canonical_id="urn:sha256:vid001",
    )
    db_session.add(f)
    db_session.commit()
    return f


@pytest.fixture(scope="module")
def digital_doc(db_session: Session) -> File:
    f = File(
        id="doc001",
        filename="report.pdf",
        original_path="/docs/report.pdf",
        mime_type="application/pdf",
        file_size=204800,
        canonical_id="urn:sha256:doc001",
        extracted_text="This is the report content.",
    )
    db_session.add(f)
    db_session.commit()
    return f


@pytest.fixture(scope="module")
def category(db_session: Session) -> Category:
    c = Category(
        name="Finance",
        canonical_id="caf10001-0000-0000-0000-000000000001",
        full_path="Finance",
        level=0,
        description="Financial documents",
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture(scope="module")
def company(db_session: Session) -> Company:
    c = Company(
        name="Acme Corporation",
        canonical_id="cac10001-0000-0000-0000-000000000001",
        normalized_name="acme corporation",
        domain="acme.com",
        industry="Manufacturing",
        first_seen=datetime(2020, 1, 1),
        last_seen=datetime(2024, 12, 31),
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture(scope="module")
def person(db_session: Session) -> Person:
    p = Person(
        name="Jane Doe",
        canonical_id="cap10001-0000-0000-0000-000000000001",
        normalized_name="jane doe",
        email="jane@example.com",
        role="Engineer",
        first_seen=datetime(2021, 3, 1),
        last_seen=datetime(2024, 11, 30),
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture(scope="module")
def place_location(db_session: Session) -> Location:
    loc = Location(
        name="New York, NY, US",
        canonical_id="cal10001-0000-0000-0000-000000000001",
        city="New York",
        state="NY",
        country="US",
        latitude=40.7128,
        longitude=-74.0060,
        geohash="dr5r7",
    )
    db_session.add(loc)
    db_session.commit()
    return loc


@pytest.fixture(scope="module")
def country_location(db_session: Session) -> Location:
    loc = Location(
        name="France",
        canonical_id="cal10002-0000-0000-0000-000000000001",
        country="FR",
    )
    db_session.add(loc)
    db_session.commit()
    return loc


@pytest.fixture(scope="module")
def city_location(db_session: Session) -> Location:
    loc = Location(
        name="Austin",
        canonical_id="cal10003-0000-0000-0000-000000000001",
        city="Austin",
    )
    db_session.add(loc)
    db_session.commit()
    return loc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def validate_jsonschema(instance: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validate instance against schema using jsonschema."""
    import jsonschema

    jsonschema.validate(instance=instance, schema=schema)


# ---------------------------------------------------------------------------
# @context and @type validation (all types)
# ---------------------------------------------------------------------------


class TestContextAndTypeValidation:
    """Validate @context and @type for all entity types."""

    def test_file_image_context_is_schema_org(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        assert result["@context"] == "https://schema.org"

    def test_file_image_type_is_valid_schema_org_type(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        assert result["@type"] in _VALID_SCHEMA_ORG_TYPES

    def test_file_image_type_is_image_object(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        assert result["@type"] == "ImageObject"

    def test_file_video_type_is_video_object(self, video_file: File) -> None:
        result = video_file.to_schema_org()
        assert result["@type"] == "VideoObject"

    def test_file_doc_type_is_digital_document(self, digital_doc: File) -> None:
        result = digital_doc.to_schema_org()
        assert result["@type"] == "DigitalDocument"

    def test_category_type_is_defined_term(self, category: Category) -> None:
        result = category.to_schema_org()
        assert result["@type"] == "DefinedTerm"
        assert result["@context"] == "https://schema.org"

    def test_company_type_is_organization(self, company: Company) -> None:
        result = company.to_schema_org()
        assert result["@type"] == "Organization"
        assert result["@context"] == "https://schema.org"

    def test_person_type_is_person(self, person: Person) -> None:
        result = person.to_schema_org()
        assert result["@type"] == "Person"
        assert result["@context"] == "https://schema.org"

    def test_place_location_type_is_valid(self, place_location: Location) -> None:
        result = place_location.to_schema_org()
        assert result["@type"] in _VALID_SCHEMA_ORG_TYPES

    def test_country_location_type_is_country(self, country_location: Location) -> None:
        result = country_location.to_schema_org()
        assert result["@type"] == "Country"

    def test_city_location_type_is_city(self, city_location: Location) -> None:
        result = city_location.to_schema_org()
        assert result["@type"] == "City"


# ---------------------------------------------------------------------------
# Required property validation
# ---------------------------------------------------------------------------


class TestRequiredProperties:
    """Validate that required properties per type are present."""

    def test_file_has_required_properties(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        assert "@context" in result
        assert "@type" in result
        assert "@id" in result
        assert "name" in result

    def test_category_has_required_properties(self, category: Category) -> None:
        result = category.to_schema_org()
        assert "@context" in result
        assert "@type" in result
        assert "@id" in result
        assert "name" in result
        assert "definition" in result
        assert "inDefinedTermSet" in result

    def test_company_has_required_properties(self, company: Company) -> None:
        result = company.to_schema_org()
        assert "@context" in result
        assert "@type" in result
        assert "@id" in result
        assert "name" in result

    def test_person_has_required_properties(self, person: Person) -> None:
        result = person.to_schema_org()
        assert "@context" in result
        assert "@type" in result
        assert "@id" in result
        assert "name" in result

    def test_location_has_required_properties(self, place_location: Location) -> None:
        result = place_location.to_schema_org()
        assert "@context" in result
        assert "@type" in result
        assert "@id" in result
        assert "name" in result

    def test_id_is_urn_format(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        assert result["@id"].startswith("urn:")

    def test_category_id_is_urn_uuid(self, category: Category) -> None:
        result = category.to_schema_org()
        assert result["@id"].startswith("urn:uuid:")

    def test_company_id_is_urn_uuid(self, company: Company) -> None:
        result = company.to_schema_org()
        assert result["@id"].startswith("urn:uuid:")

    def test_person_id_is_urn_uuid(self, person: Person) -> None:
        result = person.to_schema_org()
        assert result["@id"].startswith("urn:uuid:")

    def test_location_id_is_urn_uuid(self, place_location: Location) -> None:
        result = place_location.to_schema_org()
        assert result["@id"].startswith("urn:uuid:")


# ---------------------------------------------------------------------------
# Property value type validation via jsonschema
# ---------------------------------------------------------------------------


class TestPropertyValueTypes:
    """Validate property value types using jsonschema."""

    def test_file_image_matches_schema(self, image_file: File) -> None:
        validate_jsonschema(image_file.to_schema_org(), _FILE_SCHEMA)

    def test_file_video_matches_schema(self, video_file: File) -> None:
        validate_jsonschema(video_file.to_schema_org(), _FILE_SCHEMA)

    def test_file_doc_matches_schema(self, digital_doc: File) -> None:
        validate_jsonschema(digital_doc.to_schema_org(), _FILE_SCHEMA)

    def test_category_matches_schema(self, category: Category) -> None:
        validate_jsonschema(category.to_schema_org(), _CATEGORY_SCHEMA)

    def test_company_matches_schema(self, company: Company) -> None:
        validate_jsonschema(company.to_schema_org(), _COMPANY_SCHEMA)

    def test_person_matches_schema(self, person: Person) -> None:
        validate_jsonschema(person.to_schema_org(), _PERSON_SCHEMA)

    def test_location_place_matches_schema(self, place_location: Location) -> None:
        validate_jsonschema(place_location.to_schema_org(), _LOCATION_SCHEMA)

    def test_location_country_matches_schema(self, country_location: Location) -> None:
        validate_jsonschema(country_location.to_schema_org(), _LOCATION_SCHEMA)

    def test_location_city_matches_schema(self, city_location: Location) -> None:
        validate_jsonschema(city_location.to_schema_org(), _LOCATION_SCHEMA)

    def test_file_image_width_is_numeric(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        if "width" in result:
            assert isinstance(result["width"], (int, float))

    def test_file_image_height_is_numeric(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        if "height" in result:
            assert isinstance(result["height"], (int, float))

    def test_file_has_faces_is_bool(self, image_file: File) -> None:
        result = image_file.to_schema_org()
        if "hasFaces" in result:
            assert isinstance(result["hasFaces"], bool)

    def test_category_file_count_is_int(self, category: Category) -> None:
        result = category.to_schema_org()
        assert isinstance(result["fileCount"], int)

    def test_category_hierarchy_level_is_int(self, category: Category) -> None:
        result = category.to_schema_org()
        assert isinstance(result["hierarchyLevel"], int)

    def test_company_same_as_is_list_of_strings(self, company: Company) -> None:
        result = company.to_schema_org()
        if "sameAs" in result:
            assert isinstance(result["sameAs"], list)
            for item in result["sameAs"]:
                assert isinstance(item, str)

    def test_company_mention_count_is_int(self, company: Company) -> None:
        result = company.to_schema_org()
        assert isinstance(result["mentionCount"], int)

    def test_person_mention_count_is_int(self, person: Person) -> None:
        result = person.to_schema_org()
        assert isinstance(result["mentionCount"], int)

    def test_location_geo_is_object(self, place_location: Location) -> None:
        result = place_location.to_schema_org()
        assert "geo" in result
        assert isinstance(result["geo"], dict)
        assert result["geo"]["@type"] == "GeoCoordinates"
        assert isinstance(result["geo"]["latitude"], (int, float))
        assert isinstance(result["geo"]["longitude"], (int, float))

    def test_location_address_is_object(self, place_location: Location) -> None:
        result = place_location.to_schema_org()
        assert "address" in result
        assert isinstance(result["address"], dict)
        assert result["address"]["@type"] == "PostalAddress"

    def test_category_in_defined_term_set_is_object(self, category: Category) -> None:
        result = category.to_schema_org()
        term_set = result["inDefinedTermSet"]
        assert isinstance(term_set, dict)
        assert "@type" in term_set
        assert "name" in term_set

    def test_date_fields_are_iso_strings(self, company: Company) -> None:
        result = company.to_schema_org()
        for field in ("dateCreated", "dateModified", "dateFounded"):
            if field in result:
                assert isinstance(result[field], str)
                # Verify it's a parseable date string
                value = result[field]
                # Accept ISO 8601 date or datetime strings
                assert len(value) >= 10
                assert value[4] == "-"

    def test_person_email_is_string(self, person: Person) -> None:
        result = person.to_schema_org()
        if "email" in result:
            assert isinstance(result["email"], str)

    def test_person_job_title_is_string(self, person: Person) -> None:
        result = person.to_schema_org()
        if "jobTitle" in result:
            assert isinstance(result["jobTitle"], str)
