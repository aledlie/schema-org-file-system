"""
Unit tests for storage models.

Tests model methods, ID generation, and serialization.
"""

import pytest
import uuid

from src.storage.models import (
    File,
    Category,
    Company,
    Person,
    Location,
    FileStatus,
    RelationshipType,
    MergeEvent,
    MergeEventType,
    NAMESPACES,
)


class TestFileModel:
    """Tests for File model."""

    def test_generate_id_deterministic(self):
        """Test that ID generation is deterministic."""
        path = "/tmp/test/file.jpg"
        id1 = File.generate_id(path)
        id2 = File.generate_id(path)

        assert id1 == id2
        assert len(id1) == 64  # SHA-256 hex

    def test_generate_id_different_paths(self):
        """Test different paths generate different IDs."""
        id1 = File.generate_id("/tmp/file1.jpg")
        id2 = File.generate_id("/tmp/file2.jpg")

        assert id1 != id2

    def test_generate_canonical_id(self):
        """Test canonical ID generation."""
        path = "/tmp/test.jpg"
        canonical = File.generate_canonical_id(path)

        assert canonical.startswith("urn:sha256:")
        assert len(canonical) == len("urn:sha256:") + 64

    def test_get_iri_with_canonical(self):
        """Test get_iri returns canonical_id when set."""
        file = File(
            id="abc123",
            canonical_id="urn:sha256:test",
            filename="test.jpg",
            original_path="/tmp/test.jpg",
        )

        assert file.get_iri() == "urn:sha256:test"

    def test_get_iri_fallback(self):
        """Test get_iri falls back to id-based URN."""
        file = File(id="abc123", filename="test.jpg", original_path="/tmp/test.jpg")

        assert file.get_iri() == "urn:sha256:abc123"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        file = File(
            id="abc123",
            canonical_id="urn:sha256:abc123",
            filename="test.jpg",
            original_path="/tmp/test.jpg",
            mime_type="image/jpeg",
            status=FileStatus.ORGANIZED,
        )

        data = file.to_dict()

        assert data["id"] == "abc123"
        assert data["filename"] == "test.jpg"
        assert data["status"] == "organized"
        assert "@id" in data

    @pytest.mark.parametrize(
        "mime_type,expected_type",
        [
            ("image/jpeg", "ImageObject"),
            ("image/png", "ImageObject"),
            ("video/mp4", "VideoObject"),
            ("audio/mpeg", "AudioObject"),
            ("application/pdf", "DigitalDocument"),
            ("text/html", "WebPage"),
            ("application/json", "SoftwareSourceCode"),
            ("text/plain", "DigitalDocument"),
            (None, "DigitalDocument"),
            ("unknown/type", "DigitalDocument"),
        ],
    )
    def test_get_schema_type_from_mime(self, mime_type, expected_type):
        """Test MIME type to schema.org type mapping, including fallbacks."""
        assert File.get_schema_type_from_mime(mime_type) == expected_type

    def test_to_schema_org_description_from_schema_data(self):
        """description is sourced from the persisted generated schema."""
        file = File(
            id="abc123",
            canonical_id="urn:sha256:abc123",
            filename="test.jpg",
            original_path="/tmp/test.jpg",
            mime_type="image/jpeg",
            schema_data={"description": "Content: a landscape or nature scene (84% confident)"},
        )

        jsonld = file.to_schema_org()

        assert jsonld["description"] == ("Content: a landscape or nature scene (84% confident)")

    @pytest.mark.parametrize(
        "schema_data",
        [
            None,
            {},
            {"description": ""},
            {"name": "no description key"},
            ["not-a-dict"],
        ],
    )
    def test_to_schema_org_omits_description_without_schema_data(self, schema_data):
        """No description property when schema_data lacks a usable one."""
        file = File(
            id="abc123",
            filename="test.jpg",
            original_path="/tmp/test.jpg",
            schema_data=schema_data,
        )

        assert "description" not in file.to_schema_org()


class TestCategoryModel:
    """Tests for Category model."""

    def test_generate_canonical_id(self):
        """Test UUID v5 generation from name."""
        canonical = Category.generate_canonical_id("Documents")

        # Should be valid UUID
        uuid.UUID(canonical)

        # Should be deterministic
        assert canonical == Category.generate_canonical_id("Documents")

    def test_canonical_id_normalized(self):
        """Test canonical ID is normalized."""
        id1 = Category.generate_canonical_id("Documents")
        id2 = Category.generate_canonical_id("  DOCUMENTS  ")

        assert id1 == id2

    def test_get_iri(self):
        """Test IRI generation."""
        category = Category(
            id=1, name="GameAssets", canonical_id=Category.generate_canonical_id("GameAssets")
        )

        iri = category.get_iri()

        assert iri.startswith("urn:uuid:")
        assert category.canonical_id in iri

    def test_to_dict(self):
        """Test serialization."""
        category = Category(
            id=1,
            name="Documents",
            canonical_id=Category.generate_canonical_id("Documents"),
            full_path="Documents",
            level=0,
        )

        data = category.to_dict()

        assert data["name"] == "Documents"
        assert "file_count" in data  # derived from edges; see TestDerivedFileCount
        assert "@id" in data


class TestCompanyModel:
    """Tests for Company model."""

    def test_normalize_name(self):
        """Test name normalization."""
        assert Company.normalize_name("Acme Corp") == "acme corp"
        assert Company.normalize_name("  TEST  ") == "test"
        assert Company.normalize_name("MixedCase") == "mixedcase"

    def test_generate_canonical_id(self):
        """Test UUID v5 generation."""
        canonical = Company.generate_canonical_id("Acme Corp")

        uuid.UUID(canonical)  # Valid UUID
        assert canonical == Company.generate_canonical_id("acme corp")  # Normalized

    def test_get_iri(self):
        """Test IRI generation."""
        company = Company(
            id=1,
            name="Test Corp",
            normalized_name="test corp",
            canonical_id=Company.generate_canonical_id("Test Corp"),
        )

        iri = company.get_iri()

        assert iri.startswith("urn:uuid:")

    def test_to_dict(self):
        """Test serialization."""
        company = Company(
            id=1,
            name="Acme Corp",
            normalized_name="acme corp",
            canonical_id=Company.generate_canonical_id("Acme Corp"),
            domain="acme.com",
        )

        data = company.to_dict()

        assert data["name"] == "Acme Corp"
        assert data["domain"] == "acme.com"


class TestPersonModel:
    """Tests for Person model."""

    def test_normalize_name(self):
        """Test name normalization."""
        assert Person.normalize_name("John Doe") == "john doe"
        assert Person.normalize_name("  JANE SMITH  ") == "jane smith"

    def test_generate_canonical_id(self):
        """Test UUID v5 generation."""
        canonical = Person.generate_canonical_id("John Doe")

        uuid.UUID(canonical)
        assert canonical == Person.generate_canonical_id("john doe")

    def test_to_dict(self):
        """Test serialization."""
        person = Person(
            id=1,
            name="John Doe",
            normalized_name="john doe",
            canonical_id=Person.generate_canonical_id("John Doe"),
            email="john@example.com",
        )

        data = person.to_dict()

        assert data["name"] == "John Doe"
        assert data["email"] == "john@example.com"


class TestLocationModel:
    """Tests for Location model."""

    def test_generate_canonical_id(self):
        """Test UUID v5 generation."""
        canonical = Location.generate_canonical_id("San Francisco")

        uuid.UUID(canonical)
        assert canonical == Location.generate_canonical_id("  san francisco  ")

    def test_to_dict(self):
        """Test serialization."""
        location = Location(
            id=1,
            name="San Francisco",
            canonical_id=Location.generate_canonical_id("San Francisco"),
            city="San Francisco",
            state="CA",
            country="USA",
            latitude=37.7749,
            longitude=-122.4194,
        )

        data = location.to_dict()

        assert data["name"] == "San Francisco"
        assert data["city"] == "San Francisco"
        assert data["latitude"] == 37.7749


class TestFileStatus:
    """Tests for FileStatus enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert FileStatus.PENDING.value == "pending"
        assert FileStatus.ORGANIZED.value == "organized"
        assert FileStatus.SKIPPED.value == "skipped"
        assert FileStatus.ERROR.value == "error"
        assert FileStatus.ALREADY_ORGANIZED.value == "already_organized"


class TestRelationshipType:
    """Tests for RelationshipType enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert RelationshipType.DUPLICATE.value == "duplicate"
        assert RelationshipType.SIMILAR.value == "similar"
        assert RelationshipType.VERSION.value == "version"
        assert RelationshipType.DERIVED.value == "derived"
        assert RelationshipType.RELATED.value == "related"
        assert RelationshipType.PARENT_CHILD.value == "parent_child"
        assert RelationshipType.REFERENCES.value == "references"


class TestMergeEvent:
    """Tests for MergeEvent model."""

    def test_generate_jsonld(self):
        """Test JSON-LD generation."""
        from src.storage._time import utcnow

        merge = MergeEvent(
            id="test-merge-id",
            target_entity_type=MergeEventType.COMPANY,
            target_entity_id=1,
            target_canonical_id="abc-123",
            source_entity_ids=[2, 3],
            source_canonical_ids=["def-456", "ghi-789"],
            merge_reason="Duplicate companies",
            confidence=0.95,
            performed_by="system",
            performed_at=utcnow(),
        )

        jsonld = merge.generate_jsonld()

        assert jsonld["@type"] == "MergeAction"
        assert "@context" in jsonld
        assert "owl" in jsonld["@context"]
        assert "targetEntity" in jsonld
        assert jsonld["targetEntity"]["@id"] == "urn:uuid:abc-123"
        assert "owl:sameAs" in jsonld["targetEntity"]

    def test_to_dict(self):
        """Test serialization."""
        merge = MergeEvent(
            id="test-merge-id",
            target_entity_type=MergeEventType.PERSON,
            target_entity_id=1,
            source_entity_ids=[2],
            merge_reason="Same person",
        )

        data = merge.to_dict()

        assert data["id"] == "test-merge-id"
        assert data["target_entity_type"] == "person"
        assert data["merge_reason"] == "Same person"


class TestNamespaces:
    """Tests for namespace UUIDs."""

    def test_all_namespaces_valid(self):
        """Test all namespaces are valid UUIDs."""
        for name, ns_uuid in NAMESPACES.items():
            assert isinstance(ns_uuid, uuid.UUID), f"{name} is not a UUID"

    def test_namespaces_unique(self):
        """Test all namespace UUIDs are unique."""
        values = list(NAMESPACES.values())
        assert len(values) == len(set(values))

    def test_expected_namespaces(self):
        """Test expected namespaces exist."""
        expected = ["file", "category", "company", "person", "location", "session", "merge_event"]
        for ns in expected:
            assert ns in NAMESPACES, f"Missing namespace: {ns}"
