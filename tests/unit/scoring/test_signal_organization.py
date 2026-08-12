"""OrganizationKeywordSignal tests (UNIFIED_SCORING_PLAN §4 row 5)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.organization import (
    ORG_CONFIDENCE_BASE,
    ORG_MIN_KEYWORD_HITS,
    OrgIdentity,
    ORG_MIN_TEXT_CHARS,
    OrganizationKeywordSignal,
    detect_organization,
    detect_organization_domain,
    organization_confidence,
)
from src.scoring.weights import W_ORG

# Exactly two "vendors" indicator hits: 'invoice' + 'purchase order'.
VENDOR_TEXT_2_HITS = (
    "Please review the attached invoice covering the recent purchase order "
    "for lab equipment and supplies."
)
# Four "vendors" hits: + 'payment terms' + 'net 30'.
VENDOR_TEXT_4_HITS = (
    "Please review the attached invoice for the purchase order. "
    "Payment terms: net 30 per the signed schedule."
)
# All nine "vendors" indicators — enough extra hits to reach the cap.
VENDOR_TEXT_9_HITS = (
    "Invoice attached for the purchase order. PO number: 12. Vendor ID: 7. "
    "Supplier: Acme. Bill to: HQ. Ship to: warehouse. Payment terms: net 30."
)
# Two "government" hits AND two "vendors" hits — dict order must win.
GOV_AND_VENDOR_TEXT = (
    "The Department of the Treasury issued this invoice under purchase "
    "order 5 covering the fiscal year."
)
# One vendors hit only.
SINGLE_HIT_TEXT = (
    "This invoice covers consulting delivered during the spring engagement " "window for the team."
)


class FakeClassifier:
    def __init__(self, companies=None):
        self.companies = companies if companies is not None else []
        self.calls = 0

    def extract_company_names(self, text):
        self.calls += 1
        return list(self.companies)


def make_ctx(text, schema_type="DigitalDocument", path="/tmp/doc.pdf"):
    return FileContext(
        path=Path(path),
        schema_type=schema_type,
        text_provider=lambda _p: text,
    )


def make_image_ctx(text, path="/tmp/scan.png"):
    ocr = SimpleNamespace(text=text, confidence=0.9, language="en")
    return FileContext(
        path=Path(path),
        schema_type="ImageObject",
        ocr_provider=lambda _p: ocr,
    )


class TestSignalContract:
    def test_identity(self):
        signal = OrganizationKeywordSignal(FakeClassifier())
        assert signal.name == "organization_keyword"
        assert signal.weight == W_ORG
        assert signal.cost_tier == "mid"

    def test_scores_tagged_with_signal_name(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        (score,) = signal.run(make_ctx(VENDOR_TEXT_2_HITS))
        assert score.signal_name == signal.name


class TestAppliesTo:
    def test_short_text_gated(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        assert not signal.applies_to(make_ctx("x" * (ORG_MIN_TEXT_CHARS - 1)))
        assert signal.applies_to(make_ctx("x" * ORG_MIN_TEXT_CHARS))

    def test_applies_to_images_via_ocr_text(self):
        # Intentional broadening vs the legacy documents/PDF-only tier: org
        # evidence must accumulate on image OCR text too (§4 format drift).
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        assert signal.applies_to(make_image_ctx(VENDOR_TEXT_2_HITS))


class TestRun:
    def test_two_hits_base_confidence(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        (score,) = signal.run(make_ctx(VENDOR_TEXT_2_HITS))
        assert (score.category, score.subcategory) == ("organization", "vendors")
        assert score.confidence == pytest.approx(ORG_CONFIDENCE_BASE)
        assert score.evidence == {
            "company_name": "Acme Corp",
            "org_type": "vendors",
            "keyword_hits": 2,
        }

    def test_confidence_scales_per_extra_hit(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        (score,) = signal.run(make_ctx(VENDOR_TEXT_4_HITS))
        assert score.confidence == pytest.approx(0.9)
        assert score.evidence["keyword_hits"] == 4

    def test_confidence_capped_at_one(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        (score,) = signal.run(make_ctx(VENDOR_TEXT_9_HITS))
        assert score.confidence == 1.0
        assert 0.0 <= score.confidence <= 1.0

    def test_first_matching_type_in_dict_order_wins(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Treasury Corp"]))
        (score,) = signal.run(make_ctx(GOV_AND_VENDOR_TEXT))
        assert score.subcategory == "government"

    def test_single_hit_emits_nothing(self):
        classifier = FakeClassifier(["Acme Corp"])
        signal = OrganizationKeywordSignal(classifier)
        assert signal.run(make_ctx(SINGLE_HIT_TEXT)) == []
        assert classifier.calls == 0

    def test_no_company_name_emits_nothing(self):
        signal = OrganizationKeywordSignal(FakeClassifier([]))
        assert signal.run(make_ctx(VENDOR_TEXT_2_HITS)) == []

    def test_image_ocr_text_emits_org(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["Acme Corp"]))
        (score,) = signal.run(make_image_ctx(VENDOR_TEXT_2_HITS))
        assert (score.category, score.subcategory) == ("organization", "vendors")


class TestDetectOrganization:
    def test_returns_type_name_and_hits(self):
        result = detect_organization(
            VENDOR_TEXT_4_HITS, extract_company_names=lambda _t: ["Acme Corp"]
        )
        assert result == ("vendors", "Acme Corp", 4)

    def test_none_without_company(self):
        result = detect_organization(VENDOR_TEXT_2_HITS, extract_company_names=lambda _t: [])
        assert result is None

    def test_none_without_enough_hits(self):
        result = detect_organization(
            SINGLE_HIT_TEXT, extract_company_names=lambda _t: ["Acme Corp"]
        )
        assert result is None


class TestOrganizationConfidence:
    def test_base_and_scaling_and_cap(self):
        assert organization_confidence(2) == pytest.approx(0.7)
        assert organization_confidence(3) == pytest.approx(0.8)
        assert organization_confidence(9) == 1.0


class TestGenomicsLabDetection:
    """Regression for GeneDx Variant Classification Process mis-route.

    Before the fix, ORG_INDICATORS lacked genomics vocabulary so detect_organization
    returned None (0 keyword hits across all types) for documents about variant
    classification, sequencing, and pathogenicity — even when OCR correctly surfaces
    the company name via domain cue.  The 'healthcare' type now includes genomics
    keywords so these documents are routed to Organization/{company}/.
    """

    # Matches real GeneDx Variant Classification Process PDF OCR output.
    GENEDX_TEXT = (
        "General Variant Classification Assertion Criteria\n"
        "Data analysis and variant classification at GeneDx is a multi-step process.\n"
        "Variant interpretation at GeneDx combines automated algorithms and internal "
        "databases. GeneDx classifies sequencing variants into five categories: "
        "pathogenic, likely pathogenic, variant of uncertain significance (VUS), "
        "likely benign, and benign.\n"
        "207 Perry Parkway - Gaithersburg, MD 20877\n"
        "zebras@genedx.com - genedx.com\n"
    )

    def test_genomics_lab_keywords_reach_minimum_hits(self):
        # At least 3 of the added keywords appear in a real variant classification doc
        # ("variant classification", "sequencing", "pathogenic") → 3 hits ≥ MIN 2.
        result = detect_organization(self.GENEDX_TEXT, extract_company_names=lambda _t: ["GeneDx"])
        assert result is not None, "detect_organization must not return None for genomics docs"
        org_type, org_name, hits = result
        assert org_type == "healthcare"
        assert org_name == "GeneDx"
        assert hits >= 2

    def test_genomics_lab_routes_to_healthcare_subcategory(self):
        signal = OrganizationKeywordSignal(FakeClassifier(["GeneDx"]))
        scores = signal.run(make_ctx(self.GENEDX_TEXT))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("organization", "healthcare")
        assert scores[0].evidence["company_name"] == "GeneDx"


class TestInsurancePolicyPrecedence:
    """Insurance POLICY vocabulary must NOT trip the org gate.

    History: the USAA homeowners policy mis-route (uncategorized/other) was
    first fixed by adding insurance vocabulary to ORG_INDICATORS['financial'],
    routing policies to organization/financial. That fix was superseded the
    same day by the financial/insurance taxonomy: policy documents now route
    financial/insurance via text content (pinned by the named-insurer golden
    pair in tests/integration/test_unified_scoring_golden.py), which requires
    the org signal to stay quiet on policy-only vocabulary — org keywords
    would score 1.0 and, at W_ORG 1.0 > W_TEXT 0.8, steal every policy page.
    """

    # Insurance vocabulary only — no banking terms.
    POLICY_TEXT_NO_MORTGAGE = (
        "HOMEOWNERS INSURANCE POLICY SUMMARY\n"
        "USAA Casualty Insurance Company\n"
        "Existing USAA Homeowners Insurance Policy Summary\n"
        "Policy Number: CIC 000000000 00A\n"
        "Named Insured: JANE Q MEMBER\n"
        "Deductible(s) All other perils: $2,000\n"
        "Revised Annual Premium: $2,666.82\n"
    )
    # Full shape of the real document, mortgagee clause included — the only
    # financial indicators are the clause's banking terms ('bank', 'mortgage').
    POLICY_TEXT = POLICY_TEXT_NO_MORTGAGE + (
        "Mortgage Clause: EXAMPLE BANK, N.A. ITS SUCCESSORS AND/OR ASSIGNS\n"
    )

    def test_policy_vocabulary_alone_stays_below_keyword_gate(self):
        result = detect_organization(
            self.POLICY_TEXT_NO_MORTGAGE,
            extract_company_names=lambda _t: ["USAA Casualty Insurance"],
        )
        assert result is None, (
            "policy vocabulary must not clear the org keyword gate — "
            "financial/insurance owns policy documents"
        )

    def test_mortgagee_clause_fires_at_base_confidence_only(self):
        # The clause's banking terms ('bank', 'mortgage') legitimately trip the
        # 2-hit gate, but confidence must stay at base 0.7 (2 hits, no extras)
        # so a strong text_content financial/insurance vote can still compete.
        signal = OrganizationKeywordSignal(FakeClassifier(["USAA Casualty Insurance"]))
        scores = signal.run(make_ctx(self.POLICY_TEXT))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("organization", "financial")
        assert scores[0].confidence == pytest.approx(0.7)


class TestGovernmentIdentityRequirement:
    """Topical government words alone must not type an org as government.

    ``government`` is first in ORG_INDICATORS (dict order is load-bearing), so
    any two of its keywords used to claim the file. In a domestic-violence
    survivor intake form that is "agency" and "immigration" — both incidental
    to a form that asks about immigration status — which typed an Austin
    nonprofit as a government body.
    """

    # Two government indicators, both topical, no government body named.
    TOPICAL_ONLY = (
        "Contact the agency handling your case if your immigration status "
        "changes during the course of this matter, so the file stays current."
    )
    # Two topical hits PLUS an identity-bearing indicator.
    NAMES_A_BODY = (
        "The Department of the Treasury notified the agency about your "
        "immigration filing and the associated federal record for this year."
    )

    def test_topical_words_alone_do_not_type_as_government(self):
        result = detect_organization(
            self.TOPICAL_ONLY, extract_company_names=lambda _t: ["Some Org"]
        )
        assert result is None or result[0] != "government"

    def test_named_government_body_still_detected(self):
        result = detect_organization(
            self.NAMES_A_BODY, extract_company_names=lambda _t: ["Department of the Treasury"]
        )
        assert result is not None
        assert result[0] == "government"


class TestOrgDomainIdentity:
    """A curated domain resolves organizations whose documents never name them.

    The SAFE Alliance's legal intake form says only "SAFE Legal Department"
    and "legal@safeaustin.org" — company extraction lands on the department,
    and keyword typing lands on government.
    """

    SAFE_TEXT = (
        "Legal Intake Form | (512) 356-1682 legal@safeaustin.org. This intake "
        "form does not constitute an attorney/client relationship and is solely "
        "for the purpose of seeking services from SAFE Legal Department."
    )

    def test_domain_supplies_canonical_name_and_type(self):
        assert detect_organization_domain(self.SAFE_TEXT) == OrgIdentity(
            name="The SAFE Alliance", org_type="nonprofit"
        )

    def test_domain_overrides_extracted_name_and_keyword_type(self):
        result = detect_organization(
            self.SAFE_TEXT, extract_company_names=lambda _t: ["SAFE Legal Department"]
        )
        assert result is not None
        org_type, org_name, _hits = result
        assert (org_type, org_name) == ("nonprofit", "The SAFE Alliance")

    def test_unknown_domain_leaves_detection_unchanged(self):
        result = detect_organization(
            VENDOR_TEXT_4_HITS.replace("lab equipment", "lab equipment (billing@example.com)"),
            extract_company_names=lambda _t: ["Acme Corp"],
        )
        assert result == ("vendors", "Acme Corp", 4)

    def test_no_domain_in_text_returns_none(self):
        assert detect_organization_domain(VENDOR_TEXT_4_HITS) is None


class TestDomainIdentityHitCount:
    """A domain result reports base hits, not another type's keyword count.

    The SAFE Alliance intake form clears ``government`` on "agency" and
    "immigration" while resolving to ``nonprofit`` via its domain. Reporting
    the government count would scale a nonprofit's confidence by how much
    government vocabulary the page happened to contain.
    """

    def test_domain_result_reports_base_hits(self):
        text = TestOrgDomainIdentity.SAFE_TEXT + (
            " Contact the agency about your immigration filing and the "
            "federal government bureau handling this commission."
        )
        result = detect_organization(text, extract_company_names=lambda _t: ["SAFE Legal Dept"])
        assert result is not None
        org_type, org_name, hits = result
        assert (org_type, org_name) == ("nonprofit", "The SAFE Alliance")
        assert hits == ORG_MIN_KEYWORD_HITS

    def test_domain_result_scores_base_confidence(self):
        text = TestOrgDomainIdentity.SAFE_TEXT
        result = detect_organization(text, extract_company_names=lambda _t: ["SAFE Legal Dept"])
        assert result is not None
        assert organization_confidence(result[2]) == pytest.approx(ORG_CONFIDENCE_BASE)

    def test_keyword_path_still_reports_real_hits(self):
        # No curated domain -> the honest running count is preserved.
        result = detect_organization(
            VENDOR_TEXT_4_HITS, extract_company_names=lambda _t: ["Acme Corp"]
        )
        assert result == ("vendors", "Acme Corp", 4)
