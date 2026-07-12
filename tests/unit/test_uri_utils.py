"""
Unit tests for URI / IRI generation (P1-3).

The system has no standalone `src/uri_utils.py`; canonical-ID and JSON-LD @id
(IRI) generation live as pure static methods on the ORM models
(`src/storage/models.py`). These tests pin the *cross-cutting* URI-generation
contract that per-model tests in ``test_storage_models.py`` don't cover:

  - File IDs are SHA-256 URNs; named entities are deterministic UUIDv5 URNs.
  - The ``urn:sha256:`` / ``urn:uuid:`` format invariants.
  - Namespace isolation: the same name in different entity types yields
    different canonical IDs (each entity uses a distinct UUIDv5 namespace).
  - Name normalization (case/whitespace) is stable across entity types.
  - The ``get_iri()`` @id contract for each entity, including File's fallback.

All methods under test are pure (no DB session required).
"""

import uuid

import pytest

from src.storage.models import (
    File,
    Category,
    Company,
    Person,
    Location,
    NAMESPACES,
)

# Entity types whose canonical_id is a deterministic UUIDv5 of a normalized name.
UUID_NAMED_ENTITIES = [
    (Category, "category"),
    (Company, "company"),
    (Person, "person"),
    (Location, "location"),
]

URN_SHA256_PREFIX = "urn:sha256:"
URN_UUID_PREFIX = "urn:uuid:"
SHA256_HEX_LEN = 64


class TestFileUri:
    """File uses content-address (SHA-256 of path), not a UUIDv5 name hash."""

    def test_generate_id_is_sha256_hex(self):
        file_id = File.generate_id("/tmp/a/b.jpg")
        assert len(file_id) == SHA256_HEX_LEN
        assert all(c in "0123456789abcdef" for c in file_id)

    def test_canonical_id_is_generate_id_as_urn(self):
        # The canonical IRI must be exactly the URN form of the raw id, so the
        # two ID surfaces can never drift apart.
        path = "/Users/me/Documents/report.pdf"
        assert File.generate_canonical_id(path) == URN_SHA256_PREFIX + File.generate_id(path)

    def test_canonical_id_deterministic(self):
        path = "/tmp/x.png"
        assert File.generate_canonical_id(path) == File.generate_canonical_id(path)

    def test_distinct_paths_yield_distinct_ids(self):
        assert File.generate_canonical_id("/tmp/one") != File.generate_canonical_id("/tmp/two")

    def test_canonical_id_is_path_sensitive_not_normalized(self):
        # Unlike named entities, File IDs are NOT case/whitespace-normalized:
        # a different path string is a different file.
        assert File.generate_canonical_id("/tmp/A") != File.generate_canonical_id("/tmp/a")

    def test_get_iri_prefers_canonical_id(self):
        f = File(id="deadbeef", canonical_id="urn:sha256:custom")
        assert f.get_iri() == "urn:sha256:custom"

    def test_get_iri_falls_back_to_id_urn(self):
        f = File(id="abc123", canonical_id=None)
        assert f.get_iri() == URN_SHA256_PREFIX + "abc123"


class TestNamedEntityCanonicalId:
    """Category/Company/Person/Location share the UUIDv5-of-normalized-name scheme."""

    @pytest.mark.parametrize("model, ns_key", UUID_NAMED_ENTITIES)
    def test_canonical_id_is_valid_uuid5(self, model, ns_key):
        raw = model.generate_canonical_id("Example Name")
        parsed = uuid.UUID(raw)  # raises if not a valid UUID string
        assert parsed.version == 5
        # And it must be exactly the uuid5 of the entity's own namespace.
        assert raw == str(uuid.uuid5(NAMESPACES[ns_key], "example name"))

    @pytest.mark.parametrize("model, _ns_key", UUID_NAMED_ENTITIES)
    def test_canonical_id_deterministic(self, model, _ns_key):
        assert model.generate_canonical_id("Repeatable") == model.generate_canonical_id("Repeatable")

    @pytest.mark.parametrize("model, _ns_key", UUID_NAMED_ENTITIES)
    def test_canonical_id_normalizes_case_and_whitespace(self, model, _ns_key):
        assert model.generate_canonical_id("Acme Corp") == model.generate_canonical_id("  acme corp  ")

    @pytest.mark.parametrize("model, _ns_key", UUID_NAMED_ENTITIES)
    def test_distinct_names_yield_distinct_ids(self, model, _ns_key):
        assert model.generate_canonical_id("Alice") != model.generate_canonical_id("Bob")

    def test_namespace_isolation_across_entity_types(self):
        # The same name must map to a different canonical ID per entity type,
        # so a Company and a Person named "Apple" never collide on @id.
        name = "Apple"
        ids = {model.generate_canonical_id(name) for model, _ in UUID_NAMED_ENTITIES}
        assert len(ids) == len(UUID_NAMED_ENTITIES)

    def test_namespaces_are_all_distinct(self):
        # Guards the isolation property above at its source.
        assert len(set(NAMESPACES.values())) == len(NAMESPACES)


class TestNamedEntityIri:
    """get_iri() wraps the canonical UUID in the urn:uuid: scheme."""

    @pytest.mark.parametrize("model, _ns_key", UUID_NAMED_ENTITIES)
    def test_get_iri_is_urn_uuid_of_canonical(self, model, _ns_key):
        cid = model.generate_canonical_id("Widget Inc")
        entity = model(canonical_id=cid)
        iri = entity.get_iri()
        assert iri == URN_UUID_PREFIX + cid
        # The tail must be a parseable UUID.
        uuid.UUID(iri[len(URN_UUID_PREFIX):])

    def test_file_and_named_entity_iris_use_different_schemes(self):
        f = File(id="f" * SHA256_HEX_LEN, canonical_id=None)
        c = Company(canonical_id=Company.generate_canonical_id("SomeCo"))
        assert f.get_iri().startswith(URN_SHA256_PREFIX)
        assert c.get_iri().startswith(URN_UUID_PREFIX)
