"""KieStructuredSignal tests (UNIFIED_SCORING_PLAN §4 row 3, §11 OQ #7).

Fake KIEResult (SimpleNamespace with a ``.fields`` dict), fake classifier,
synthetic FileContext — no docTR/KIE models. Covers the image applies_to
gate, the ensure_kie OCR-confidence gate integration, []-emissions when KIE
is absent or inconclusive, and the vendor/people/field-class evidence at
KIE_MATCH_CONFIDENCE.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.kie_structured import KIE_MATCH_CONFIDENCE, KieStructuredSignal
from src.scoring.weights import OCR_CONFIDENCE_GATE

INVOICE_CLASSIFICATION = ("financial", "invoices", "Acme Corp", ["Jane Doe"])


def make_kie_result(field_classes=("vendor_name", "total_amount")):
    return SimpleNamespace(fields={name: [] for name in field_classes})


class FakeClassifier:
    def __init__(self, classification=INVOICE_CLASSIFICATION):
        self._classification = classification
        self.calls = []

    def classify_with_kie(self, kie_result, text, filename):
        self.calls.append((kie_result, text, filename))
        return self._classification


def make_ocr(text="INVOICE Acme Corp total $42.00", confidence=0.9, language="en"):
    return SimpleNamespace(text=text, confidence=confidence, language=language)


def make_ctx(kie_result, ocr=None, schema_type="ImageObject"):
    if ocr is None:
        ocr = make_ocr()
    return FileContext(
        path=Path("/tmp/invoice.png"),
        schema_type=schema_type,
        ocr_provider=lambda _path: ocr,
        kie_provider=(lambda _path: kie_result) if kie_result is not None else None,
    )


class TestAppliesTo:
    def test_image_applies(self) -> None:
        signal = KieStructuredSignal(FakeClassifier())
        assert signal.applies_to(make_ctx(make_kie_result()))

    def test_document_gated(self) -> None:
        signal = KieStructuredSignal(FakeClassifier())
        assert not signal.applies_to(make_ctx(make_kie_result(), schema_type="DigitalDocument"))


class TestRunGating:
    def test_no_kie_provider_emits_nothing(self) -> None:
        classifier = FakeClassifier()
        signal = KieStructuredSignal(classifier)
        assert signal.run(make_ctx(None)) == []
        assert classifier.calls == []

    def test_low_confidence_ocr_blocks_kie(self) -> None:
        # ensure_kie enforces the OCR-confidence gate; the signal must honor
        # the resulting None instead of re-running extraction.
        classifier = FakeClassifier()
        signal = KieStructuredSignal(classifier)
        ctx = make_ctx(make_kie_result(), ocr=make_ocr(confidence=OCR_CONFIDENCE_GATE - 0.01))
        assert signal.run(ctx) == []
        assert classifier.calls == []

    def test_inconclusive_kie_classification_emits_nothing(self) -> None:
        signal = KieStructuredSignal(FakeClassifier(classification=None))
        assert signal.run(make_ctx(make_kie_result())) == []


class TestRunEmission:
    def test_kie_classification_emitted(self) -> None:
        signal = KieStructuredSignal(FakeClassifier())
        emissions = signal.run(make_ctx(make_kie_result()))
        assert len(emissions) == 1
        score = emissions[0]
        assert (score.category, score.subcategory) == ("financial", "invoices")
        assert score.confidence == pytest.approx(KIE_MATCH_CONFIDENCE)
        assert score.signal_name == "kie_structured"

    def test_evidence_payload(self) -> None:
        signal = KieStructuredSignal(FakeClassifier())
        kie_result = make_kie_result(field_classes=("total_amount", "vendor_name"))
        score = signal.run(make_ctx(kie_result))[0]
        assert score.evidence == {
            "company_name": "Acme Corp",
            "people_names": ["Jane Doe"],
            "kie_field_classes": ["total_amount", "vendor_name"],
        }

    def test_field_classes_sorted(self) -> None:
        signal = KieStructuredSignal(FakeClassifier())
        kie_result = make_kie_result(field_classes=("vendor_name", "invoice_date"))
        score = signal.run(make_ctx(kie_result))[0]
        assert score.evidence["kie_field_classes"] == ["invoice_date", "vendor_name"]

    def test_classifier_receives_kie_text_and_filename(self) -> None:
        classifier = FakeClassifier()
        signal = KieStructuredSignal(classifier)
        kie_result = make_kie_result()
        ocr = make_ocr(text="INVOICE text body")
        signal.run(make_ctx(kie_result, ocr=ocr))
        assert classifier.calls == [(kie_result, "INVOICE text body", "invoice.png")]
