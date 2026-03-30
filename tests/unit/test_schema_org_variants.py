"""
Integration tests for schema_org_variants.

Covers CategoryVariants, PersonVariants, and FileVariants — all representations
verified against real model instances and their to_schema_org() output.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add src/ to sys.path so storage.* modules resolve without triggering src/__init__.py
_SRC_DIR = Path(__file__).parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from storage.models import Base, File, Category, Company, Person, Location
from storage.schema_org_variants import (
    SCHEMA_ORG_CONTEXT,
    CategoryVariants,
    FileVariants,
    PersonVariants,
)

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# CategoryVariants
# ---------------------------------------------------------------------------


class TestCategoryVariantsToDefinedTerm:
    """CategoryVariants.to_defined_term against real Category model instances."""

    def test_basic_defined_term(self, db_session: Session):
        cat = Category(
            name="Legal",
            canonical_id="caa00001-0000-0000-0000-000000000001",
            description="Legal documents",
            full_path="Legal",
            level=0,
        )
        db_session.add(cat)
        db_session.commit()

        variant = CategoryVariants.to_defined_term(
            canonical_id=cat.canonical_id,
            name=cat.name,
            description=cat.description,
            full_path=cat.full_path,
        )

        assert variant["@context"] == SCHEMA_ORG_CONTEXT
        assert variant["@type"] == "DefinedTerm"
        assert variant["@id"] == f"urn:uuid:{cat.canonical_id}"
        assert variant["name"] == "Legal"
        assert variant["definition"] == "Legal documents"

    def test_identifier_derived_from_full_path(self, db_session: Session):
        cat = Category(
            name="Contracts",
            canonical_id="caa00002-0000-0000-0000-000000000002",
            full_path="Legal/Contracts",
            level=1,
        )
        db_session.add(cat)
        db_session.commit()

        variant = CategoryVariants.to_defined_term(
            canonical_id=cat.canonical_id,
            name=cat.name,
            full_path=cat.full_path,
        )

        assert variant["identifier"] == "legal-contracts"

    def test_parent_reference_included(self, db_session: Session):
        parent = Category(
            name="Legal",
            canonical_id="caa00003-0000-0000-0000-000000000003",
            full_path="Legal",
            level=0,
        )
        child = Category(
            name="NDAs",
            canonical_id="caa00004-0000-0000-0000-000000000004",
            full_path="Legal/NDAs",
            level=1,
            parent=parent,
        )
        db_session.add_all([parent, child])
        db_session.commit()

        variant = CategoryVariants.to_defined_term(
            canonical_id=child.canonical_id,
            name=child.name,
            full_path=child.full_path,
            parent_iri=parent.get_iri(),
        )

        assert "broader" in variant
        assert variant["broader"]["@id"] == parent.get_iri()

    def test_children_reference_included(self, db_session: Session):
        parent = Category(
            name="Media",
            canonical_id="caa00005-0000-0000-0000-000000000005",
            full_path="Media",
            level=0,
        )
        child_a = Category(
            name="Photos",
            canonical_id="caa00006-0000-0000-0000-000000000006",
            full_path="Media/Photos",
            level=1,
            parent=parent,
        )
        child_b = Category(
            name="Videos",
            canonical_id="caa00007-0000-0000-0000-000000000007",
            full_path="Media/Videos",
            level=1,
            parent=parent,
        )
        db_session.add_all([parent, child_a, child_b])
        db_session.commit()

        variant = CategoryVariants.to_defined_term(
            canonical_id=parent.canonical_id,
            name=parent.name,
            children_iris={
                child_a.get_iri(): child_a.name,
                child_b.get_iri(): child_b.name,
            },
        )

        assert "narrower" in variant
        names = {n["name"] for n in variant["narrower"]}
        assert names == {"Photos", "Videos"}

    def test_icon_and_color_included(self, db_session: Session):
        cat = Category(
            name="Finance",
            canonical_id="caa00008-0000-0000-0000-000000000008",
            icon="💰",
            color="#00FF00",
        )
        db_session.add(cat)
        db_session.commit()

        variant = CategoryVariants.to_defined_term(
            canonical_id=cat.canonical_id,
            name=cat.name,
            icon=cat.icon,
            color=cat.color,
        )

        assert variant["icon"] == "💰"
        assert variant["color"] == "#00FF00"

    def test_file_count_defaults_to_zero(self):
        variant = CategoryVariants.to_defined_term(
            canonical_id="caa00009-0000-0000-0000-000000000009",
            name="Empty",
        )
        assert variant["fileCount"] == 0

    def test_defined_term_set_always_present(self):
        variant = CategoryVariants.to_defined_term(
            canonical_id="caa00010-0000-0000-0000-000000000010",
            name="Test",
        )
        assert "inDefinedTermSet" in variant
        assert variant["inDefinedTermSet"]["@type"] == "DefinedTermSet"

    def test_matches_model_to_schema_org_shape(self, db_session: Session):
        """to_defined_term output mirrors model.to_schema_org() for key fields."""
        cat = Category(
            name="Technical",
            canonical_id="caa00011-0000-0000-0000-000000000011",
            description="Technical files",
            full_path="Technical",
            level=0,
        )
        db_session.add(cat)
        db_session.commit()

        model_output = cat.to_schema_org()
        variant = CategoryVariants.to_defined_term(
            canonical_id=cat.canonical_id,
            name=cat.name,
            description=cat.description,
            full_path=cat.full_path,
        )

        assert variant["@type"] == model_output["@type"]
        assert variant["@id"] == model_output["@id"]
        assert variant["name"] == model_output["name"]
        assert variant["definition"] == model_output["definition"]

    def test_output_is_json_serializable(self):
        variant = CategoryVariants.to_defined_term(
            canonical_id="caa00012-0000-0000-0000-000000000012",
            name="Serializable",
            description="test",
        )
        serialized = json.dumps(variant)
        parsed = json.loads(serialized)
        assert parsed["name"] == "Serializable"


class TestCategoryVariantsToIntangible:
    def test_basic_intangible(self):
        variant = CategoryVariants.to_intangible(
            canonical_id="cab00001-0000-0000-0000-000000000001",
            name="Misc",
        )
        assert variant["@context"] == SCHEMA_ORG_CONTEXT
        assert variant["@type"] == "Intangible"
        assert variant["@id"] == "urn:uuid:cab00001-0000-0000-0000-000000000001"
        assert variant["name"] == "Misc"

    def test_description_included_when_provided(self):
        variant = CategoryVariants.to_intangible(
            canonical_id="cab00002-0000-0000-0000-000000000002",
            name="Misc",
            description="Miscellaneous files",
        )
        assert variant["description"] == "Miscellaneous files"

    def test_description_absent_when_not_provided(self):
        variant = CategoryVariants.to_intangible(
            canonical_id="cab00003-0000-0000-0000-000000000003",
            name="Misc",
        )
        assert "description" not in variant

    def test_no_defined_term_set(self):
        variant = CategoryVariants.to_intangible(
            canonical_id="cab00004-0000-0000-0000-000000000004",
            name="Misc",
        )
        assert "inDefinedTermSet" not in variant


# ---------------------------------------------------------------------------
# PersonVariants
# ---------------------------------------------------------------------------


class TestPersonVariantsToPersonWithContext:
    def test_basic_person(self, db_session: Session):
        person = Person(
            name="Alice Example",
            canonical_id="pab00001-0000-0000-0000-000000000001",
            normalized_name="alice example",
            email="alice@example.com",
            role="Engineer",
        )
        db_session.add(person)
        db_session.commit()

        variant = PersonVariants.to_person_with_context(
            canonical_id=person.canonical_id,
            name=person.name,
            email=person.email,
            job_title=person.role,
        )

        assert variant["@context"] == SCHEMA_ORG_CONTEXT
        assert variant["@type"] == "Person"
        assert variant["@id"] == f"urn:uuid:{person.canonical_id}"
        assert variant["name"] == "Alice Example"
        assert variant["email"] == "alice@example.com"
        assert variant["jobTitle"] == "Engineer"

    def test_works_for_included(self, db_session: Session):
        company = Company(
            name="TechCo",
            canonical_id="cab00001-0000-0000-0000-000000000001",
            normalized_name="techco",
        )
        person = Person(
            name="Bob",
            canonical_id="pab00002-0000-0000-0000-000000000002",
            normalized_name="bob",
        )
        db_session.add_all([company, person])
        db_session.commit()

        variant = PersonVariants.to_person_with_context(
            canonical_id=person.canonical_id,
            name=person.name,
            works_for_iri=company.get_iri(),
            works_for_name=company.name,
        )

        assert "worksFor" in variant
        assert variant["worksFor"]["@type"] == "Organization"
        assert variant["worksFor"]["@id"] == company.get_iri()
        assert variant["worksFor"]["name"] == "TechCo"

    def test_work_location_included(self, db_session: Session):
        location = Location(
            name="London",
            canonical_id="lab00001-0000-0000-0000-000000000001",
            city="London",
        )
        person = Person(
            name="Carol",
            canonical_id="pab00003-0000-0000-0000-000000000003",
            normalized_name="carol",
        )
        db_session.add_all([location, person])
        db_session.commit()

        variant = PersonVariants.to_person_with_context(
            canonical_id=person.canonical_id,
            name=person.name,
            work_location_iri=location.get_iri(),
            work_location_name=location.name,
        )

        assert "workLocation" in variant
        assert variant["workLocation"]["@type"] == "Place"
        assert variant["workLocation"]["name"] == "London"

    def test_optional_fields_absent_when_not_provided(self):
        variant = PersonVariants.to_person_with_context(
            canonical_id="pab00004-0000-0000-0000-000000000004",
            name="Minimal",
        )
        assert "email" not in variant
        assert "jobTitle" not in variant
        assert "worksFor" not in variant
        assert "workLocation" not in variant

    def test_mention_count_included(self):
        variant = PersonVariants.to_person_with_context(
            canonical_id="pab00005-0000-0000-0000-000000000005",
            name="Counted",
            mention_count=42,
        )
        assert variant["mentionCount"] == 42

    def test_matches_model_to_schema_org_with_relationships(self, db_session: Session):
        """PersonVariants output is consistent with model.to_schema_org_with_relationships()."""
        company = Company(
            name="Corp",
            canonical_id="cab00002-0000-0000-0000-000000000002",
            normalized_name="corp",
        )
        location = Location(
            name="Paris",
            canonical_id="lab00002-0000-0000-0000-000000000002",
            city="Paris",
        )
        person = Person(
            name="Dave",
            canonical_id="pab00006-0000-0000-0000-000000000006",
            normalized_name="dave",
        )
        db_session.add_all([company, location, person])
        db_session.commit()

        model_output = person.to_schema_org_with_relationships(company=company, location=location)
        variant = PersonVariants.to_person_with_context(
            canonical_id=person.canonical_id,
            name=person.name,
            works_for_iri=company.get_iri(),
            works_for_name=company.name,
            work_location_iri=location.get_iri(),
            work_location_name=location.name,
        )

        assert variant["@type"] == model_output["@type"]
        assert variant["worksFor"]["@type"] == model_output["worksFor"]["@type"]
        assert variant["workLocation"]["@type"] == model_output["workLocation"]["@type"]

    def test_output_is_json_serializable(self):
        variant = PersonVariants.to_person_with_context(
            canonical_id="pab00007-0000-0000-0000-000000000007",
            name="Serializable",
            email="s@example.com",
        )
        serialized = json.dumps(variant)
        parsed = json.loads(serialized)
        assert parsed["name"] == "Serializable"


# ---------------------------------------------------------------------------
# FileVariants
# ---------------------------------------------------------------------------


class TestFileVariantsToCreativeWork:
    def test_basic_creative_work(self, db_session: Session):
        file_ = File(
            id="fab00001",
            filename="essay.pdf",
            original_path="/docs/essay.pdf",
            mime_type="application/pdf",
            file_size=4096,
            canonical_id="urn:sha256:fab00001",
        )
        db_session.add(file_)
        db_session.commit()

        variant = FileVariants.to_creative_work(
            iri=file_.get_iri(),
            name=file_.filename,
            encoding_format=file_.mime_type,
            content_size=file_.file_size,
        )

        assert variant["@context"] == SCHEMA_ORG_CONTEXT
        assert variant["@type"] == "CreativeWork"
        assert variant["@id"] == file_.get_iri()
        assert variant["name"] == "essay.pdf"
        assert variant["encodingFormat"] == "application/pdf"
        assert variant["contentSize"] == "4096"

    def test_text_truncated_to_2000_chars(self):
        long_text = "x" * 5000
        variant = FileVariants.to_creative_work(
            iri="urn:sha256:trunc001",
            name="text.txt",
            text=long_text,
        )
        assert len(variant["text"]) == 2000

    def test_about_and_mentions_included(self, db_session: Session):
        category = Category(
            name="Research",
            canonical_id="cac00001-0000-0000-0000-000000000001",
        )
        company = Company(
            name="ResearchCo",
            canonical_id="coc00001-0000-0000-0000-000000000001",
            normalized_name="researchco",
        )
        db_session.add_all([category, company])
        db_session.commit()

        about = [{"@type": "DefinedTerm", "@id": category.get_iri(), "name": category.name}]
        mentions = [{"@type": "Organization", "@id": company.get_iri(), "name": company.name}]

        variant = FileVariants.to_creative_work(
            iri="urn:sha256:withrels",
            name="doc.pdf",
            about_iris=about,
            mentions=mentions,
        )

        assert variant["mainEntityOfPage"]["name"] == "Research"
        assert variant["mentions"][0]["@type"] == "Organization"

    def test_optional_fields_absent_when_not_provided(self):
        variant = FileVariants.to_creative_work(
            iri="urn:sha256:minimal",
            name="minimal.txt",
        )
        for field in ("encodingFormat", "contentSize", "dateCreated", "dateModified", "url", "text", "about", "mentions"):
            assert field not in variant

    def test_output_is_json_serializable(self):
        variant = FileVariants.to_creative_work(
            iri="urn:sha256:serial",
            name="serial.txt",
            encoding_format="text/plain",
        )
        parsed = json.loads(json.dumps(variant))
        assert parsed["name"] == "serial.txt"


class TestFileVariantsToMediaObject:
    def test_image_object(self, db_session: Session):
        file_ = File(
            id="fab00002",
            filename="photo.jpg",
            original_path="/images/photo.jpg",
            mime_type="image/jpeg",
            image_width=1920,
            image_height=1080,
            canonical_id="urn:sha256:fab00002",
        )
        db_session.add(file_)
        db_session.commit()

        variant = FileVariants.to_media_object(
            iri=file_.get_iri(),
            name=file_.filename,
            schema_type="ImageObject",
            encoding_format=file_.mime_type,
            width=file_.image_width,
            height=file_.image_height,
        )

        assert variant["@context"] == SCHEMA_ORG_CONTEXT
        assert variant["@type"] == "ImageObject"
        assert variant["width"] == 1920
        assert variant["height"] == 1080

    def test_video_object_with_duration(self):
        variant = FileVariants.to_media_object(
            iri="urn:sha256:video001",
            name="clip.mp4",
            schema_type="VideoObject",
            duration="PT1M30S",
        )
        assert variant["@type"] == "VideoObject"
        assert variant["duration"] == "PT1M30S"

    def test_content_location_included(self):
        content_location = {
            "@type": "Place",
            "geo": {"@type": "GeoCoordinates", "latitude": 51.5, "longitude": -0.12},
        }
        variant = FileVariants.to_media_object(
            iri="urn:sha256:geo001",
            name="london.jpg",
            schema_type="ImageObject",
            content_location=content_location,
        )
        assert variant["contentLocation"]["@type"] == "Place"
        assert variant["contentLocation"]["geo"]["latitude"] == 51.5

    def test_optional_fields_absent_when_not_provided(self):
        variant = FileVariants.to_media_object(
            iri="urn:sha256:bare001",
            name="bare.jpg",
            schema_type="ImageObject",
        )
        for field in ("encodingFormat", "contentSize", "width", "height", "duration", "dateCreated", "url", "contentLocation"):
            assert field not in variant

    def test_consistent_with_file_to_schema_org_image_type(self, db_session: Session):
        """@type in variant matches what File.to_schema_org() produces for images."""
        file_ = File(
            id="fab00003",
            filename="img.png",
            original_path="/img.png",
            mime_type="image/png",
            canonical_id="urn:sha256:fab00003",
        )
        db_session.add(file_)
        db_session.commit()

        model_output = file_.to_schema_org()
        variant = FileVariants.to_media_object(
            iri=file_.get_iri(),
            name=file_.filename,
            schema_type=file_.get_schema_type(),
            encoding_format=file_.mime_type,
        )

        assert variant["@type"] == model_output["@type"]
        assert variant["@id"] == model_output["@id"]

    def test_output_is_json_serializable(self):
        variant = FileVariants.to_media_object(
            iri="urn:sha256:serial002",
            name="serial.mp4",
            schema_type="VideoObject",
        )
        parsed = json.loads(json.dumps(variant))
        assert parsed["name"] == "serial.mp4"
