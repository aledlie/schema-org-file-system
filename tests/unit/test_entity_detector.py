"""Unit tests for EntityDetector (extracted from ContentClassifier).

These pin the entity-extraction behavior directly on the collaborator, so a
future change to ``ContentClassifier`` can't silently drop it. The
ContentClassifier-level pass-throughs remain covered by
``test_content_classifier.py``.
"""

import pytest

from src.classifiers import ContentClassifier, EntityDetector


@pytest.fixture()
def det() -> EntityDetector:
    return EntityDetector()


class TestExtractCompanyNames:
    def test_extracts_llc(self, det: EntityDetector) -> None:
        companies = det.extract_company_names("We signed a deal with Acme Solutions LLC today.")
        assert any("Acme Solutions" in c for c in companies)

    def test_extracts_inc(self, det: EntityDetector) -> None:
        companies = det.extract_company_names("Global Tech Inc. provided the software.")
        assert any("Global Tech" in c for c in companies)

    def test_no_duplicates(self, det: EntityDetector) -> None:
        companies = det.extract_company_names("Acme Solutions LLC and Acme Solutions LLC agreed.")
        lower = [c.lower() for c in companies]
        assert len(lower) == len(set(lower))

    def test_empty_and_none_company(self, det: EntityDetector) -> None:
        assert det.extract_company_names("") == []
        assert det.extract_company_names("the quick brown fox") == []


class TestExtractPeopleNames:
    def test_resume_header(self, det: EntityDetector) -> None:
        people = det.extract_people_names("John Smith Resume\nSoftware Engineer")
        assert any("John" in p and "Smith" in p for p in people)

    def test_title_prefix(self, det: EntityDetector) -> None:
        people = det.extract_people_names("Please contact Dr. Jane Doe for more information.")
        assert any("Jane" in p and "Doe" in p for p in people)

    def test_all_caps_titlecased(self, det: EntityDetector) -> None:
        people = det.extract_people_names("JANE DOE\nSoftware Engineer")
        assert people and all(not p.isupper() for p in people)

    def test_collapses_spaced_letters(self, det: EntityDetector) -> None:
        # Stylized resume headers space out letters; they must still resolve.
        collapsed = det._collapse_spaced_text("I S A B E L B U D E N Z")
        assert "ISABEL" in collapsed and "BUDENZ" in collapsed


class TestRelationships:
    def test_person_at_company(self, det: EntityDetector) -> None:
        rels = det.extract_person_company_relationships("Jane Doe at Acme Solutions LLC")
        assert rels.get("Jane Doe", "").startswith("Acme Solutions")

    def test_email_domain_becomes_company(self, det: EntityDetector) -> None:
        # The email regex captures the domain label without its TLD, so the
        # "contains a dot" capitalization branch doesn't fire — it stays as-is.
        rels = det.extract_person_company_relationships("John Smith <john@acmecorp.com>")
        assert rels.get("John Smith") == "acmecorp"


class TestCompanyNameValidation:
    def test_valid(self, det: EntityDetector) -> None:
        assert det.is_valid_company_name("Acme Solutions") is True
        assert det.is_valid_company_name("Blue Ridge") is True

    def test_invalid(self, det: EntityDetector) -> None:
        assert det.is_valid_company_name("") is False
        assert det.is_valid_company_name("The Agreement between parties") is False
        assert det.is_valid_company_name("Smith And") is False


class TestNormalizeAndSanitize:
    def test_strips_suffixes(self, det: EntityDetector) -> None:
        assert det.normalize_company_name("Acme Solutions LLC") == "Acme Solutions"
        assert det.normalize_company_name("Acme Corporation") == "Acme"

    def test_copyright_and_year_prefix(self, det: EntityDetector) -> None:
        assert "Google" in det.normalize_company_name("Copyright 2024 Google")
        assert "Microsoft" in det.normalize_company_name("2024 Microsoft")

    def test_sanitize_rejects_fragment(self, det: EntityDetector) -> None:
        assert det.sanitize_company_name("Agreement between parties") is None

    def test_sanitize_strips_invalid_chars(self, det: EntityDetector) -> None:
        assert det.sanitize_company_name("Acme/Solutions LLC") == "AcmeSolutions"


def test_classifier_delegates_to_entity_detector() -> None:
    # The composed detector and the pass-throughs must agree.
    clf = ContentClassifier()
    assert isinstance(clf.entities, EntityDetector)
    text = "We signed a deal with Acme Solutions LLC today."
    assert clf.extract_company_names(text) == clf.entities.extract_company_names(text)
