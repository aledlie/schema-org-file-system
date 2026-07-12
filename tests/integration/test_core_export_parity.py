"""Parity: Core-query export (use_core=True) must match ORM export byte-for-byte.

Both paths share the build_*_jsonld functions in models.py, so any divergence
here means the Core relationship-loading or column selection drifted from what
the ORM relationships/attributes yield. The seed exercises every serialization
branch: relationship ordering, parent/child taxonomy, multi vs single location,
image + GPS fields, empty-field fallbacks, and 2-char vs long country codes.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_SRC_DIR = Path(__file__).parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from storage.models import (  # noqa: E402
    Base,
    Category,
    Company,
    File,
    Location,
    Person,
)
from storage.schema_org_exporter import SchemaOrgExporter  # noqa: E402

from datetime import datetime  # noqa: E402


def _file(path, **kw):
    return File(
        id=File.generate_id(path),
        canonical_id=File.generate_canonical_id(path),
        original_path=path,
        filename=path.rsplit("/", 1)[-1],
        **kw,
    )


def _cat(name, **kw):
    return Category(name=name, canonical_id=Category.generate_canonical_id(name), **kw)


def _company(name, **kw):
    return Company(
        name=name,
        normalized_name=Company.normalize_name(name),
        canonical_id=Company.generate_canonical_id(name),
        **kw,
    )


def _person(name, **kw):
    return Person(
        name=name,
        normalized_name=Person.normalize_name(name),
        canonical_id=Person.generate_canonical_id(name),
        **kw,
    )


def _location(name, **kw):
    return Location(name=name, canonical_id=Location.generate_canonical_id(name), **kw)


@pytest.fixture
def rich_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()

    # Categories: a parent with two children, plus a bare category
    root = _cat(
        "Legal",
        full_path="Legal",
        level=0,
        description="Legal documents",
        icon="⚖️",
        color="#334455",
    )
    child_a = _cat("Contracts", full_path="Legal/Contracts", level=1)
    child_b = _cat("Terms", full_path="Legal/Terms", level=1)
    child_a.parent = root
    child_b.parent = root
    bare = _cat("Misc")  # no full_path/description/icon/color -> fallback definition

    # Companies: one full, one minimal
    acme = _company(
        "Acme Corp",
        domain="acme.com",
        industry="Software",
        first_seen=datetime(2020, 1, 2, 3, 4, 5),
        last_seen=datetime(2021, 6, 7, 8, 9, 10),
        file_count=3,
    )
    globex = _company("Globex", domain="https://globex.io", file_count=1)

    # People: one full, one minimal
    ada = _person(
        "Ada Lovelace",
        email="ada@x.com",
        role="Engineer",
        first_seen=datetime(2019, 5, 5),
        file_count=2,
    )
    bob = _person("Bob")

    # Locations: full address, country-only, 2-char country, geo + geohash
    austin = _location(
        "Austin",
        city="Austin",
        state="Texas",
        country="United States",
        latitude=30.27,
        longitude=-97.74,
        geohash="9v6m",
        created_at=datetime(2022, 2, 2),
        file_count=5,
    )
    france = _location("France", country="France")
    us2 = _location("US2", city="NYC", country="US")  # 2-char country stays as-is

    # Files
    f_rich = _file(
        "/docs/report.png",
        mime_type="image/png",
        file_size=2048,
        extracted_text="hello " * 500,
        detected_language="en",
        image_width=800,
        image_height=600,
        has_faces=True,
        exif_datetime=datetime(2023, 3, 3, 3, 3, 3),
        gps_latitude=1.5,
        gps_longitude=2.5,
        created_at=datetime(2023, 1, 1),
        modified_at=datetime(2023, 1, 2),
    )
    f_rich.categories = [child_a, root, child_b]  # primary + two "about" (order matters)
    f_rich.companies = [acme, globex]
    f_rich.people = [ada, bob]
    f_rich.locations = [austin, france]  # multiple -> list

    f_pdf = _file("/docs/plain.pdf", mime_type="application/pdf")  # no rels, minimal

    f_img = _file(
        "/docs/one.jpg", mime_type="image/jpeg", gps_latitude=0.0, gps_longitude=5.0
    )  # lat falsy -> no contentLocation
    f_img.categories = [root]  # single category, no "about"
    f_img.locations = [us2]  # single -> object

    s.add_all(
        [
            root,
            child_a,
            child_b,
            bare,
            acme,
            globex,
            ada,
            bob,
            austin,
            france,
            us2,
            f_rich,
            f_pdf,
            f_img,
        ]
    )
    s.commit()
    yield s
    s.close()


_ENTITIES = [File, Category, Company, Person, Location]


def _by_id(records):
    return {r["@id"]: r for r in records}


def test_core_matches_orm_full_graph(rich_session):
    orm = SchemaOrgExporter(rich_session, use_core=False)._collect_records(_ENTITIES)
    core = SchemaOrgExporter(rich_session, use_core=True)._collect_records(_ENTITIES)

    # Same set of entities, and identical content per entity (incl. relationship
    # ordering, nested objects, custom extensions).
    assert _by_id(core) == _by_id(orm)
    # Same number of records (no dupes/drops)
    assert len(core) == len(orm)


def test_core_matches_orm_per_entity(rich_session):
    for cls in _ENTITIES:
        orm = SchemaOrgExporter(rich_session, use_core=False)._collect_records([cls])
        core = SchemaOrgExporter(rich_session, use_core=True)._collect_records([cls])
        assert _by_id(core) == _by_id(orm), f"Core/ORM mismatch for {cls.__name__}"


def test_core_export_file_roundtrip(rich_session, tmp_path):
    """End-to-end: use_core export writes the same @graph document as ORM."""
    orm_doc = SchemaOrgExporter(rich_session, use_core=False).get_graph_document(_ENTITIES)
    core_doc = SchemaOrgExporter(rich_session, use_core=True).get_graph_document(_ENTITIES)
    assert _by_id(core_doc["@graph"]) == _by_id(orm_doc["@graph"])
    assert core_doc["@context"] == orm_doc["@context"]
