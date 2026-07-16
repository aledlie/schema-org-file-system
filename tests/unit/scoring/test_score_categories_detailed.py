"""ContentClassifier.score_categories_detailed tests (UNIFIED_SCORING_PLAN §10).

Covers distribution normalization, subcategory resolution parity with
``classify_content``, and empty/uncategorized cases for the new
subcategory-aware scoring consumed by TextContentSignal. The existing
``classify_content`` pins live in tests/unit/test_content_classifier.py and
stay untouched.
"""

import pytest

from src.classifiers import ContentClassifier

LEASE_TEXT = (
    "This lease agreement concerns the lease of the property at 12 Oak. "
    "The lease term begins June 1; the lease renews annually per the "
    "property schedule."
)
COURT_TEXT = (
    "Notice of court setting. Cause No 24-1234. The court will hold a "
    "hearing before the presiding judge. Plaintiff and defendant shall "
    "appear at the court at the date set by the court clerk."
)
INVOICE_TEXT = "Invoice #1234. Payment due upon receipt. Tax ID: 12-3456789."
MIXED_TEXT = "invoice payment bill contract"


@pytest.fixture()
def clf() -> ContentClassifier:
    return ContentClassifier()


class TestNormalization:
    def test_top_category_normalizes_to_one(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed(MIXED_TEXT)
        assert detailed["financial"] == ("invoices", pytest.approx(1.0))

    def test_runner_up_scores_count_ratio(self, clf: ContentClassifier) -> None:
        # financial hits invoice+payment+bill (3), legal hits contract (1).
        detailed = clf.score_categories_detailed(MIXED_TEXT)
        assert detailed["legal"] == ("contracts", pytest.approx(1 / 3))

    def test_all_scores_within_unit_interval(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed(COURT_TEXT)
        assert detailed
        for _, normalized in detailed.values():
            assert 0.0 < normalized <= 1.0

    def test_tied_categories_both_normalize_to_one(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed("invoice contract")
        assert detailed["financial"][1] == pytest.approx(1.0)
        assert detailed["legal"][1] == pytest.approx(1.0)

    def test_filename_contributes_to_counts(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed("payment amount due", "invoice_2024.pdf")
        assert "financial" in detailed
        assert detailed["financial"][1] == pytest.approx(1.0)


class TestSubcategoryParityWithClassifyContent:
    @pytest.mark.parametrize("text", [LEASE_TEXT, COURT_TEXT, INVOICE_TEXT, MIXED_TEXT])
    def test_winner_subcategory_matches_classify_content(
        self, clf: ContentClassifier, text: str
    ) -> None:
        category, subcategory, _, _ = clf.classify_content(text)
        detailed = clf.score_categories_detailed(text)
        assert detailed[category] == (subcategory, pytest.approx(1.0))

    def test_category_without_subcat_hits_defaults_to_other(self, clf: ContentClassifier) -> None:
        # 'notary' is a top-level legal keyword absent from every legal
        # subcategory list, so subcategory resolution falls back to 'other'.
        detailed = clf.score_categories_detailed("executed before a notary")
        assert detailed["legal"] == ("other", pytest.approx(1.0))

    def test_business_clients_override_excluded(self, clf: ContentClassifier) -> None:
        # classify_content flips business → clients when a company was
        # extracted; the detailed distribution is pure keyword counting and
        # must keep the keyword-resolved subcategory instead.
        text = "Acme Corp business plan strategy meeting"
        category, subcategory, company, _ = clf.classify_content(text)
        assert (category, subcategory) == ("business", "clients")
        assert company
        detailed = clf.score_categories_detailed(text)
        assert detailed["business"] == ("planning", pytest.approx(1.0))

    def test_known_company_shortcut_excluded(self, clf: ContentClassifier) -> None:
        # classify_content short-circuits on known company phrases before any
        # keyword counting; the detailed distribution never does.
        text = "Thank you for your business with Integrity Studio."
        assert clf.classify_content(text)[0] == "organization"
        assert clf.score_categories_detailed(text) == {}


class TestEmptyAndUncategorized:
    def test_empty_text_returns_empty(self, clf: ContentClassifier) -> None:
        assert clf.score_categories_detailed("") == {}

    def test_empty_text_ignores_filename(self, clf: ContentClassifier) -> None:
        # Mirrors classify_content's empty-text early return: with no text the
        # filename alone must not produce a distribution.
        assert clf.score_categories_detailed("", "invoice_2024.pdf") == {}

    def test_no_keyword_hits_returns_empty(self, clf: ContentClassifier) -> None:
        text = "zzzz qqqq wwww eeee rrrr"
        assert clf.classify_content(text)[0] == "uncategorized"
        assert clf.score_categories_detailed(text) == {}
