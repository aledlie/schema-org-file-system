"""Tests for src.storage.entity_metadata class-based standalone entities."""

import json
from pathlib import Path

import pytest

from src.storage.entity_metadata import (
    EventEntity,
    PersonEntity,
    PlaceEntity,
    ResidenceEntity,
    SchemaOrgEntity,
)
from src.storage.graph_store import GraphStore
from src.storage.models import SchemaMetadata

ENTITY_ID = "house-test-residence"


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(str(tmp_path / "graph.db"))


def _residence() -> ResidenceEntity:
    entity = ResidenceEntity(ENTITY_ID, name="Willow Street", additional_type="Accommodation")
    entity.set_address("2702 Willow Street", "Austin", "TX", "78702")
    entity.set_geo(30.252659, -97.7141653)
    return entity


def test_to_jsonld_shape():
    jsonld = _residence().to_jsonld()
    assert jsonld["@context"] == "https://schema.org"
    assert jsonld["@type"] == "Residence"
    assert jsonld["additionalType"] == "https://schema.org/Accommodation"
    assert jsonld["address"]["@type"] == "PostalAddress"
    assert jsonld["address"]["postalCode"] == "78702"
    assert jsonld["geo"]["@type"] == "GeoCoordinates"


def test_generic_entity_any_type():
    event = EventEntity("event-1", name="Launch Party")
    event.set_property("startDate", "2026-08-01")
    jsonld = event.to_jsonld()
    assert jsonld["@type"] == "Event"
    assert jsonld["startDate"] == "2026-08-01"
    assert "additionalType" not in jsonld


def test_from_jsonld_round_trip():
    original = _residence()
    rebuilt = ResidenceEntity.from_jsonld(original.to_jsonld())
    assert rebuilt.entity_id == ENTITY_ID
    assert rebuilt.name == "Willow Street"
    assert rebuilt.additional_type == "Accommodation"
    assert rebuilt.to_jsonld() == original.to_jsonld()


def test_save_creates_then_updates(store: GraphStore):
    entity = _residence()
    row = entity.save(store)
    assert row.schema_type == "Residence"

    entity.name = "Renamed"
    entity.save(store)

    session = store.get_session()
    try:
        rows = session.query(SchemaMetadata).all()
        assert len(rows) == 1
        assert rows[0].schema_json["name"] == "Renamed"
        assert rows[0].file_id is None
    finally:
        session.close()


def test_load_round_trip(store: GraphStore):
    _residence().save(store)
    loaded = ResidenceEntity.load(store, ENTITY_ID)
    assert loaded is not None
    assert loaded.name == "Willow Street"
    assert loaded.get_property("address")["streetAddress"] == "2702 Willow Street"


def test_load_missing(store: GraphStore):
    assert SchemaOrgEntity.load(store, "no-such-entity") is None


def test_person_from_graph_uses_canonical_id(store: GraphStore):
    person = PersonEntity.from_graph_person(store, "Alyshia Ledlie")
    assert person is not None
    person.owns(ENTITY_ID)
    jsonld = person.to_jsonld()
    assert jsonld["@type"] == "Person"
    assert jsonld["owns"] == {"@id": ENTITY_ID}

    session = store.get_session()
    try:
        stored = store.get_or_create_person("Alyshia Ledlie", session=session)
        assert stored is not None
        assert jsonld["@id"] == stored.canonical_id
    finally:
        session.close()


def test_person_owns_multiple(store: GraphStore):
    person = PersonEntity.from_graph_person(store, "Alyshia Ledlie")
    assert person is not None
    person.owns("a", "b")
    assert person.to_jsonld()["owns"] == [{"@id": "a"}, {"@id": "b"}]


def test_add_same_as_scalar_then_list():
    entity = SchemaOrgEntity("thing-1")
    entity.add_same_as("https://example.com/a")
    assert entity.get_property("sameAs") == "https://example.com/a"

    entity.add_same_as("https://example.com/a")  # duplicate ignored
    assert entity.get_property("sameAs") == "https://example.com/a"

    entity.add_same_as("https://example.com/b")
    assert entity.get_property("sameAs") == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_add_owns_appends_and_dedupes(store: GraphStore):
    person = PersonEntity.from_graph_person(store, "Alyshia Ledlie")
    assert person is not None
    person.add_owns("a")
    assert person.get_property("owns") == {"@id": "a"}

    person.add_owns("a", "b")  # duplicate ignored, b appended
    assert person.get_property("owns") == [{"@id": "a"}, {"@id": "b"}]


def test_add_main_entity_of_page():
    entity = SchemaOrgEntity("thing-1")
    entity.add_main_entity_of_page("https://example.com/page")
    assert entity.get_property("mainEntityOfPage") == "https://example.com/page"

    entity.add_main_entity_of_page("https://example.com/other")
    assert entity.get_property("mainEntityOfPage") == [
        "https://example.com/page",
        "https://example.com/other",
    ]


def test_geocode_without_address_is_noop():
    place = PlaceEntity("place-1", name="Nowhere")
    assert place.geocode() is False
    assert place.get_property("geo") is None


def test_export(tmp_path: Path):
    out = SchemaOrgEntity.export([_residence()], tmp_path / "entities.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["@id"] == ENTITY_ID
