"""PersonalDocSignal tests (UNIFIED_SCORING_PLAN §4 row 6, Option C)."""

from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.personal_doc import (
    PERSON_GATED_CONFIDENCE,
    PERSON_MIN_TEXT_CHARS,
    PERSON_UNGATED_CONFIDENCE,
    PersonalDocSignal,
    detect_person_indicators,
    is_resume_filename,
)
from src.scoring.weights import W_PERSON

# Three "employees" hits; 'date of birth' passes the real human-name gate.
EMPLOYEE_TEXT_GATED = (
    "Employee: John Smith. Hire date: 2024-01-15. Position: Senior Analyst. "
    "Date of birth: 1990-05-04."
)
# Three "employees" hits; no title/phrase, so the human-name gate fails.
EMPLOYEE_TEXT_UNGATED = (
    "Employee: John Smith. Hire date: 2024-01-15. Position: Senior Analyst "
    "reporting to operations."
)
# Four "references" hits; two of them are also human-name gate phrases.
REFERENCE_TEXT = (
    "To whom it may concern: I am pleased to provide this letter of "
    "recommendation for my colleague."
)
# Only two "contacts" hits — below the raised contacts threshold.
LETTERHEAD_TEXT = (
    "Thank you for your inquiry about our spring schedule. Contact the "
    "front office with questions. Phone: 555-0100."
)
# Six "contacts" hits, no human-name phrase → ungated contact card.
CONTACT_CARD_TEXT = (
    "Jane Doe contact card. Phone: 555-0100. Mobile: 555-0101. "
    "Email: jane@example.com. Address: 123 Main St."
)
# Court notice with a clerk contact block (four "contacts" hits). The legacy
# tier vetoes this on legal signals; the signal must emit anyway (§3.3).
COURT_NOTICE_TEXT = (
    "NOTICE OF COURT SETTING. Cause No 24-1234. A hearing is set. Contact "
    "the clerk with questions. Phone: 512-555-0100. Email: clerk@county.gov."
)
# 50+ chars with no person indicators at all.
NEUTRAL_TEXT = "The quarterly report shows steady growth across all business units " "this season."
RESUME_BODY = "Experienced engineer with ten years of distributed systems background."


class FakeClassifier:
    def __init__(self, people=None):
        self.people = people if people is not None else []
        self.calls = 0

    def extract_people_names(self, text):
        self.calls += 1
        return list(self.people)


def make_ctx(text, path="/tmp/record.pdf", display_path=None):
    return FileContext(
        path=Path(path),
        schema_type="DigitalDocument",
        display_path=Path(display_path) if display_path else None,
        text_provider=lambda _p: text,
    )


class TestSignalContract:
    def test_identity(self):
        signal = PersonalDocSignal(FakeClassifier())
        assert signal.name == "personal_doc"
        assert signal.weight == W_PERSON
        assert signal.cost_tier == "mid"

    def test_scores_tagged_with_signal_name(self):
        signal = PersonalDocSignal(FakeClassifier(["John Smith"]))
        (score,) = signal.run(make_ctx(EMPLOYEE_TEXT_GATED))
        assert score.signal_name == signal.name


class TestAppliesTo:
    def test_text_length_gate(self):
        signal = PersonalDocSignal(FakeClassifier())
        assert not signal.applies_to(make_ctx("x" * (PERSON_MIN_TEXT_CHARS - 1)))
        assert signal.applies_to(make_ctx("x" * PERSON_MIN_TEXT_CHARS))


class TestResumeFilename:
    def test_resume_filename_emits_gated_contacts(self):
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        (score,) = signal.run(make_ctx(RESUME_BODY, path="/tmp/Jane_Doe_Resume.pdf"))
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.confidence == pytest.approx(PERSON_GATED_CONFIDENCE)
        assert score.evidence["people_names"] == ["Jane Doe"]
        assert score.evidence["resume_filename"] is True
        assert score.evidence["person_type"] == "contacts"

    def test_resume_detected_on_display_path(self):
        # pattern_path prefers display_path — the renamer's name drives it.
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        ctx = make_ctx(RESUME_BODY, path="/tmp/scan001.pdf", display_path="/tmp/Jane Resume.pdf")
        (score,) = signal.run(ctx)
        assert score.subcategory == "contacts"

    def test_resume_emits_even_without_people(self):
        signal = PersonalDocSignal(FakeClassifier([]))
        (score,) = signal.run(make_ctx(RESUME_BODY, path="/tmp/resume_2026.pdf"))
        assert score.confidence == pytest.approx(PERSON_GATED_CONFIDENCE)
        assert "people_names" not in score.evidence


class TestGraduatedConfidence:
    def test_gated_indicator_match(self):
        signal = PersonalDocSignal(FakeClassifier(["John Smith"]))
        (score,) = signal.run(make_ctx(EMPLOYEE_TEXT_GATED))
        assert (score.category, score.subcategory) == ("personal", "employment")
        assert score.confidence == pytest.approx(PERSON_GATED_CONFIDENCE)
        assert score.evidence["name_gate"] is True
        assert score.evidence["person_type"] == "employees"
        assert score.evidence["keyword_hits"] == 3
        assert score.evidence["people_names"] == ["John Smith"]

    def test_ungated_indicator_match_emits_reduced(self):
        # Legacy returned None here; the signal emits the graduated 0.4.
        signal = PersonalDocSignal(FakeClassifier(["John Smith"]))
        (score,) = signal.run(make_ctx(EMPLOYEE_TEXT_UNGATED))
        assert (score.category, score.subcategory) == ("personal", "employment")
        assert score.confidence == pytest.approx(PERSON_UNGATED_CONFIDENCE)
        assert score.evidence["name_gate"] is False
        # Option C: graph-edge evidence attaches even on ungated emissions.
        assert score.evidence["people_names"] == ["John Smith"]

    def test_references_map_to_employment_gated(self):
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        (score,) = signal.run(make_ctx(REFERENCE_TEXT))
        assert (score.category, score.subcategory) == ("personal", "employment")
        assert score.confidence == pytest.approx(PERSON_GATED_CONFIDENCE)
        assert score.evidence["person_type"] == "references"

    def test_ungated_contact_card(self):
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        (score,) = signal.run(make_ctx(CONTACT_CARD_TEXT))
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.confidence == pytest.approx(PERSON_UNGATED_CONFIDENCE)


class TestEmptyEmissions:
    def test_no_people_extracted_emits_nothing(self):
        signal = PersonalDocSignal(FakeClassifier([]))
        assert signal.run(make_ctx(EMPLOYEE_TEXT_GATED)) == []

    def test_no_indicator_match_emits_nothing(self):
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        assert signal.run(make_ctx(NEUTRAL_TEXT)) == []

    def test_two_contact_hits_below_threshold(self):
        signal = PersonalDocSignal(FakeClassifier(["Jane Doe"]))
        assert signal.run(make_ctx(LETTERHEAD_TEXT)) == []


class TestNoLegalVeto:
    def test_court_notice_emits_despite_legal_signals(self):
        # The legacy tier vetoes; the signal competes with LegalContentSignal
        # instead (§3.3) — clerk contact blocks still emit (ungated) here.
        signal = PersonalDocSignal(FakeClassifier(["Alyshia Ledlie"]))
        (score,) = signal.run(make_ctx(COURT_NOTICE_TEXT))
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.confidence == pytest.approx(PERSON_UNGATED_CONFIDENCE)
        assert score.evidence["people_names"] == ["Alyshia Ledlie"]


class TestPureHelpers:
    def test_is_resume_filename(self):
        assert is_resume_filename("Jane_Doe_Resume.pdf")
        assert is_resume_filename("curriculum-vitae.docx")
        assert is_resume_filename("my_cv.pdf")
        assert not is_resume_filename("invoice.pdf")

    def test_detect_person_indicators_none_when_no_type_clears(self):
        result = detect_person_indicators(
            NEUTRAL_TEXT,
            extract_people_names=lambda _t: ["Jane Doe"],
            has_human_name_signal=lambda _t: True,
        )
        assert result is None

    def test_detect_person_indicators_match_shape(self):
        result = detect_person_indicators(
            EMPLOYEE_TEXT_UNGATED,
            extract_people_names=lambda _t: ["John Smith"],
            has_human_name_signal=lambda _t: False,
        )
        assert result is not None
        assert result.person_type == "employees"
        assert result.subcategory == "employment"
        assert result.keyword_hits == 3
        assert result.people == ["John Smith"]
        assert result.name_gate is False

    def test_gate_not_called_without_people(self):
        calls = []

        def gate(_text):
            calls.append(1)
            return True

        result = detect_person_indicators(
            EMPLOYEE_TEXT_GATED,
            extract_people_names=lambda _t: [],
            has_human_name_signal=gate,
        )
        assert result is not None
        assert result.people == []
        assert result.name_gate is False
        assert calls == []
