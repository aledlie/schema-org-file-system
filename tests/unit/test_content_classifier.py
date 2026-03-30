"""Unit tests for ContentClassifier."""

import pytest

from src.classifiers import ContentClassifier

@pytest.fixture()
def clf() -> ContentClassifier:
    return ContentClassifier()

class TestClassifyContent:
    def test_empty_text_returns_uncategorized(self, clf: ContentClassifier) -> None:
        cat, subcat, company, people = clf.classify_content("")
        assert cat == "uncategorized"
        assert subcat == "other"
        assert company is None
        assert people == []

    def test_legal_text_categorized(self, clf: ContentClassifier) -> None:
        text = "This contract and agreement sets out the terms and conditions between the parties."
        cat, subcat, company, people = clf.classify_content(text)
        assert cat == "legal"

    def test_financial_text_categorized(self, clf: ContentClassifier) -> None:
        text = "Invoice #1234. Payment due upon receipt. Tax ID: 12-3456789."
        cat, subcat, company, people = clf.classify_content(text)
        assert cat == "financial"

    def test_known_company_shortcut(self, clf: ContentClassifier) -> None:
        text = "Thank you for your business with Integrity Studio."
        cat, subcat, company, people = clf.classify_content(text)
        assert cat == "organization"
        assert company == "Integrity Studio"

    def test_returns_four_tuple(self, clf: ContentClassifier) -> None:
        result = clf.classify_content("Some text about a medical prescription from a doctor.")
        assert len(result) == 4

    def test_filename_influences_classification(self, clf: ContentClassifier) -> None:
        # "invoice" in filename should push financial score up
        cat, subcat, company, people = clf.classify_content(
            "payment amount due", filename="invoice_2024.pdf"
        )
        assert cat == "financial"

class TestExtractCompanyNames:
    def test_extracts_llc(self, clf: ContentClassifier) -> None:
        text = "We signed a deal with Acme Solutions LLC today."
        companies = clf.extract_company_names(text)
        assert any("Acme Solutions" in c for c in companies)

    def test_extracts_inc(self, clf: ContentClassifier) -> None:
        text = "Global Tech Inc. provided the software."
        companies = clf.extract_company_names(text)
        assert any("Global Tech" in c for c in companies)

    def test_no_duplicates(self, clf: ContentClassifier) -> None:
        text = "Acme Solutions LLC and Acme Solutions LLC agreed."
        companies = clf.extract_company_names(text)
        lower_names = [c.lower() for c in companies]
        assert len(lower_names) == len(set(lower_names))

    def test_empty_text_returns_empty(self, clf: ContentClassifier) -> None:
        assert clf.extract_company_names("") == []

    def test_no_company_returns_empty(self, clf: ContentClassifier) -> None:
        assert clf.extract_company_names("the quick brown fox") == []

class TestExtractPeopleNames:
    def test_extracts_name_from_resume_header(self, clf: ContentClassifier) -> None:
        text = "John Smith Resume\nSoftware Engineer"
        people = clf.extract_people_names(text)
        assert any("John" in p and "Smith" in p for p in people)

    def test_extracts_name_with_title_prefix(self, clf: ContentClassifier) -> None:
        text = "Please contact Dr. Jane Doe for more information."
        people = clf.extract_people_names(text)
        assert any("Jane" in p and "Doe" in p for p in people)

    def test_extracts_name_from_credential_suffix(self, clf: ContentClassifier) -> None:
        text = "Prepared by Alice Brown, PhD"
        people = clf.extract_people_names(text)
        assert any("Alice" in p and "Brown" in p for p in people)

    def test_no_duplicates(self, clf: ContentClassifier) -> None:
        text = "John Smith Resume\nJohn Smith Resume"
        people = clf.extract_people_names(text)
        lower_names = [p.lower() for p in people]
        assert len(lower_names) == len(set(lower_names))

    def test_all_caps_converted_to_title_case(self, clf: ContentClassifier) -> None:
        text = "JANE DOE\nSoftware Engineer"
        people = clf.extract_people_names(text)
        # Should not contain all-caps version
        for p in people:
            assert not p.isupper()

class TestIsValidCompanyName:
    def test_valid_short_company_name(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("Acme Solutions") is True

    def test_valid_two_word_name(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("Blue Ridge") is True

    def test_invalid_empty_string(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("") is False

    def test_invalid_starts_with_the(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("The Agreement between parties") is False

    def test_invalid_too_many_words(self, clf: ContentClassifier) -> None:
        long_name = "This Is A Very Long And Invalid Company Name Here"
        assert clf.is_valid_company_name(long_name) is False

    def test_invalid_contains_pronoun(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("We Are The Champions Corp") is False

    def test_invalid_ends_with_conjunction(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("Smith And") is False

    def test_invalid_problematic_phrase(self, clf: ContentClassifier) -> None:
        assert clf.is_valid_company_name("Agreement between parties") is False

class TestNormalizeCompanyName:
    def test_strips_llc_suffix(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("Acme Solutions LLC") == "Acme Solutions"

    def test_strips_inc_suffix(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("Global Tech Inc.") == "Global Tech"

    def test_strips_corporation_suffix(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("Acme Corporation") == "Acme"

    def test_strips_ltd_suffix(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("Euro Goods Ltd") == "Euro Goods"

    def test_copyright_notice_extracted(self, clf: ContentClassifier) -> None:
        result = clf.normalize_company_name("Copyright 2024 Google")
        assert "Google" in result

    def test_empty_string_returned_as_is(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("") == ""

    def test_plain_name_unchanged(self, clf: ContentClassifier) -> None:
        assert clf.normalize_company_name("Acme") == "Acme"

    def test_year_prefix_stripped(self, clf: ContentClassifier) -> None:
        result = clf.normalize_company_name("2024 Microsoft")
        assert "Microsoft" in result
