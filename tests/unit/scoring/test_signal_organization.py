"""OrganizationKeywordSignal tests (UNIFIED_SCORING_PLAN §4 row 5)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.organization import (
    ORG_CONFIDENCE_BASE,
    ORG_MIN_TEXT_CHARS,
    OrganizationKeywordSignal,
    detect_organization,
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
