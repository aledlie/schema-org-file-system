"""TextContentSignal tests (UNIFIED_SCORING_PLAN §4 row 9).

Synthetic FileContext + the real (pure keyword) ContentClassifier — no
models, no disk I/O. Covers the language/length applies_to gates, winner vs
damped runner-up confidence grades, length scaling, entity evidence, and
[]-emission on uncategorized text.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.classifiers import ContentClassifier
from src.scoring.context import FileContext
from src.scoring.signals.text_content import TEXT_RUNNERUP_DAMPING, TextContentSignal
from src.scoring.weights import TEXT_LENGTH_FULL_CHARS, TEXT_MIN_CHARS

LEGAL_TEXT = (
    "This contract and agreement sets out the terms and conditions between the parties. "
    "The agreement includes a settlement executed before a notary with exhibits attached. "
    "Each party shall honor the contract terms."
)
# Equal keyword counts for legal + financial; legal wins classify_content's
# insertion-order tie-break. Padding clears TEXT_MIN_CHARS without keywords.
TIE_TEXT = "invoice contract " + "z" * 40
NO_KEYWORD_TEXT = "zzzz qqqq wwww eeee rrrr " * 4


def make_ocr(text, confidence=0.9, language="en"):
    return SimpleNamespace(text=text, confidence=confidence, language=language)


def make_document_ctx(text, filename="sample.txt"):
    return FileContext(
        path=Path(f"/tmp/{filename}"),
        schema_type="DigitalDocument",
        text_provider=lambda _path: text,
    )


def make_image_ctx(ocr, filename="scan.png"):
    return FileContext(
        path=Path(f"/tmp/{filename}"),
        schema_type="ImageObject",
        ocr_provider=lambda _path: ocr,
    )


@pytest.fixture()
def signal() -> TextContentSignal:
    return TextContentSignal(ContentClassifier())


class TestSignalContract:
    def test_identity(self, signal: TextContentSignal) -> None:
        assert signal.name == "text_content"
        assert signal.cost_tier == "heavy"

    def test_emissions_tagged_with_signal_name(self, signal: TextContentSignal) -> None:
        for score in signal.run(make_document_ctx(LEGAL_TEXT)):
            assert score.signal_name == "text_content"
            assert 0.0 <= score.confidence <= 1.0


class TestAppliesTo:
    def test_document_text_applies(self, signal: TextContentSignal) -> None:
        assert signal.applies_to(make_document_ctx(LEGAL_TEXT))

    def test_short_text_gated(self, signal: TextContentSignal) -> None:
        assert not signal.applies_to(make_document_ctx("x" * (TEXT_MIN_CHARS - 1)))

    def test_min_length_boundary_applies(self, signal: TextContentSignal) -> None:
        assert signal.applies_to(make_document_ctx("x" * TEXT_MIN_CHARS))

    def test_non_english_ocr_gated(self, signal: TextContentSignal) -> None:
        ctx = make_image_ctx(make_ocr("contrat et accord " + "x" * 40, language="fr"))
        assert not signal.applies_to(ctx)

    def test_english_ocr_applies(self, signal: TextContentSignal) -> None:
        ctx = make_image_ctx(make_ocr(LEGAL_TEXT, language="en"))
        assert signal.applies_to(ctx)

    def test_missing_language_applies(self, signal: TextContentSignal) -> None:
        ctx = make_image_ctx(make_ocr(LEGAL_TEXT, language=None))
        assert signal.applies_to(ctx)


class TestWinnerEmission:
    def test_full_length_text_scores_length_factor_one(self, signal: TextContentSignal) -> None:
        assert len(LEGAL_TEXT) >= TEXT_LENGTH_FULL_CHARS
        emissions = signal.run(make_document_ctx(LEGAL_TEXT))
        winner = emissions[0]
        assert (winner.category, winner.subcategory) == ("legal", "contracts")
        assert winner.confidence == pytest.approx(1.0)

    def test_confidence_scales_with_length(self, signal: TextContentSignal) -> None:
        half_text = "contract agreement terms " + "z" * (TEXT_LENGTH_FULL_CHARS // 2 - 25)
        assert len(half_text) == TEXT_LENGTH_FULL_CHARS // 2
        winner = signal.run(make_document_ctx(half_text))[0]
        assert winner.confidence == pytest.approx(0.5)

    def test_winner_evidence_payload(self, signal: TextContentSignal) -> None:
        winner = signal.run(make_document_ctx(LEGAL_TEXT))[0]
        assert winner.evidence["company_name"] is None
        assert winner.evidence["people_names"] == []
        assert winner.evidence["length_factor"] == pytest.approx(1.0)
        assert winner.evidence["scores"]["legal"] == pytest.approx(1.0)

    def test_company_entity_attached_to_winner(self, signal: TextContentSignal) -> None:
        # Known-company shortcut: winner comes from classify_content even when
        # absent from the keyword distribution (no runner-up emissions here).
        text = "Thank you for your business with Integrity Studio."
        emissions = signal.run(make_document_ctx(text))
        assert len(emissions) == 1
        winner = emissions[0]
        assert (winner.category, winner.subcategory) == ("organization", "vendors")
        assert winner.evidence["company_name"] == "Integrity Studio"

    def test_image_text_via_ocr(self, signal: TextContentSignal) -> None:
        emissions = signal.run(make_image_ctx(make_ocr(LEGAL_TEXT)))
        assert (emissions[0].category, emissions[0].subcategory) == ("legal", "contracts")


class TestRunnerUpEmissions:
    def test_tied_runner_up_damped_below_winner(self, signal: TextContentSignal) -> None:
        emissions = signal.run(make_document_ctx(TIE_TEXT))
        by_category = {score.category: score for score in emissions}
        winner = by_category["legal"]
        runner_up = by_category["financial"]
        length_factor = len(TIE_TEXT) / TEXT_LENGTH_FULL_CHARS
        assert winner.confidence == pytest.approx(length_factor)
        assert runner_up.confidence == pytest.approx(length_factor * TEXT_RUNNERUP_DAMPING)
        assert runner_up.confidence < winner.confidence

    def test_runner_up_scaled_by_normalized_score(self, signal: TextContentSignal) -> None:
        # financial counts 3 (invoice, payment, bill) vs legal 1 (contract).
        text = "invoice payment bill contract " + "z" * 10
        emissions = signal.run(make_document_ctx(text))
        by_category = {score.category: score for score in emissions}
        length_factor = len(text) / TEXT_LENGTH_FULL_CHARS
        assert by_category["financial"].confidence == pytest.approx(length_factor)
        assert by_category["legal"].confidence == pytest.approx(
            length_factor * (1 / 3) * TEXT_RUNNERUP_DAMPING
        )
        assert by_category["legal"].subcategory == "contracts"

    def test_runner_up_evidence_payload(self, signal: TextContentSignal) -> None:
        emissions = signal.run(make_document_ctx(TIE_TEXT))
        runner_up = next(score for score in emissions if score.category == "financial")
        assert runner_up.evidence["normalized_score"] == pytest.approx(1.0)
        assert runner_up.evidence["length_factor"] == pytest.approx(
            len(TIE_TEXT) / TEXT_LENGTH_FULL_CHARS
        )


class TestUncategorized:
    def test_no_keyword_text_emits_nothing(self, signal: TextContentSignal) -> None:
        assert signal.run(make_document_ctx(NO_KEYWORD_TEXT)) == []
