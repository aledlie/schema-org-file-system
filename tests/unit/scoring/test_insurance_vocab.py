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


MEDICAL = "medical"

# SCRUBBED synthetic health-insurance EOB — invented member/claim numbers.
HEALTH_INSURANCE_EOB_TEXT = (
    "Explanation of benefits from your health plan. This is not a bill. Your copay and "
    "coinsurance for the visit are shown. You saw an in-network provider. The health "
    "insurance deductible and out-of-pocket maximum apply to your medical coverage. "
    "Member id and claim number are listed. Patient responsibility is summarized. "
    "Health plan coverage, premium, and deductible details follow."
)

# Property/auto policy heavy on domain context (no health terms).
AUTO_POLICY_TEXT = (
    "Private passenger auto insurance policy. Coverage for the insured vehicle and "
    "policyholder. Collision and comprehensive coverage. Liability coverage limits. "
    "The premium and deductible apply. Homeowner and dwelling coverage optional. "
    "Property damage protection included. Policy number and claim number listed."
)


class TestHealthVsPropertyDiscrimination:
    """Regression guard (item #4): the generic insurance vocabulary is shared by
    the financial and medical category lists, so DOMAIN context — not the shared
    terms — decides. Health-plan/clinical context wins medical; property/casualty
    context wins financial."""

    def test_health_insurance_eob_routes_medical(self, clf: ContentClassifier) -> None:
        category, subcategory, _company, _people = clf.classify_content(HEALTH_INSURANCE_EOB_TEXT)
        assert (category, subcategory) == (MEDICAL, INSURANCE)

    def test_property_auto_policy_routes_financial(self, clf: ContentClassifier) -> None:
        category, subcategory, _company, _people = clf.classify_content(AUTO_POLICY_TEXT)
        assert (category, subcategory) == (FINANCIAL, INSURANCE)

    def test_clinical_document_unaffected(self, clf: ContentClassifier) -> None:
        # A clinical record with no insurance vocabulary still routes to
        # medical/records — the added insurance terms don't disturb it.
        category, subcategory, _company, _people = clf.classify_content(
            "Patient medical record. Doctor reviewed the diagnosis and treatment plan. "
            "Prescription filled at the pharmacy. Lab results attached."
        )
        assert category == MEDICAL

    def test_health_specific_terms_registered_on_medical(self, clf: ContentClassifier) -> None:
        medical_insurance = clf.patterns[MEDICAL]["subcategories"][INSURANCE]
        for term in ("copay", "coinsurance", "explanation of benefits", "health plan"):
            assert term in medical_insurance
