"""ContentClassifier insurance-vocabulary tests (Phase-3 calibration item #4).

Pins the ``financial → insurance`` subcategory added so property/auto/liability
policies have a taxonomy home (mirroring the existing ``medical → insurance``
precedent for the non-health case). The legacy ``classify_content`` pins live
in ``tests/unit/test_content_classifier.py`` and stay untouched; this file
only exercises the new vocabulary.
"""

import pytest

from src.classifiers import ContentClassifier
from src.organizers.category_config import CONTENT_CATEGORY_PATHS

# SCRUBBED synthetic policy prose — invented policy/claim numbers, no real data.
INSURANCE_POLICY_TEXT = (
    "Private passenger auto insurance policy declarations page. This policy provides "
    "coverage for the insured vehicle and the named policyholder. Policy number PA-88213 is "
    "shown above. The annual premium is due each term. A collision deductible applies to "
    "each covered loss. Liability coverage limits and underwriting notes appear in the "
    "policy. The insured must keep the premium current to maintain coverage. Refer to the "
    "policy number and claim number when reporting a covered loss. This insurance summary "
    "lists coverage, premium, deductible, and policyholder details."
)

FINANCIAL = "financial"
INSURANCE = "insurance"


@pytest.fixture()
def clf() -> ContentClassifier:
    return ContentClassifier()


class TestInsuranceSubcategory:
    def test_policy_routes_financial_insurance(self, clf: ContentClassifier) -> None:
        category, subcategory, company, _people = clf.classify_content(INSURANCE_POLICY_TEXT)
        assert (category, subcategory) == (FINANCIAL, INSURANCE)
        assert company is None  # no extractable insurer in the policy prose

    def test_insurance_dominates_financial_distribution(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed(INSURANCE_POLICY_TEXT)
        assert detailed[FINANCIAL] == (INSURANCE, pytest.approx(1.0))

    def test_insurance_subcategory_registered(self, clf: ContentClassifier) -> None:
        assert INSURANCE in clf.patterns[FINANCIAL]["subcategories"]

    def test_insurance_subcategory_has_destination_path(self) -> None:
        assert CONTENT_CATEGORY_PATHS[FINANCIAL][INSURANCE] == "Financial/Insurance"


class TestKeywordBoundaries:
    def test_word_boundary_keeps_reclaim_from_matching(self, clf: ContentClassifier) -> None:
        # "claim number" (multi-word) is used instead of a bare "claim" so
        # word-boundary matching does not fire on "reclaim"/"claimant".
        detailed = clf.score_categories_detailed("Please reclaim the parcel.")
        assert FINANCIAL not in detailed

    def test_bare_insurance_terms_score_financial(self, clf: ContentClassifier) -> None:
        detailed = clf.score_categories_detailed("coverage premium deductible policyholder")
        assert detailed[FINANCIAL][0] == INSURANCE
