"""LegalContentSignal tests (UNIFIED_SCORING_PLAN §4 row 7, §3.3)."""

from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.legal_content import (
    LEGAL_CONFIDENCE_BASE,
    LEGAL_MIN_TEXT_CHARS,
    LEGAL_PERSONAL_CONFIDENCE,
    LegalContentSignal,
    count_legal_signals,
    legal_confidence,
    score_legal_subcategory,
)
from src.scoring.signals.personal_doc import PersonalDocSignal
from src.scoring.weights import W_LEGAL, W_PERSON

# Mirrors ContentClassifier.patterns["legal"]["subcategories"] (subset shape).
LEGAL_SUBCATEGORIES = {
    "contracts": ["contract", "agreement", "terms", "subscription", "saas"],
    "real_estate": ["lease", "deed", "property", "real estate", "mortgage"],
    "litigation": [
        "court",
        "hearing",
        "docket",
        "plaintiff",
        "defendant",
        "petitioner",
        "respondent",
        "cause no",
        "judgment",
        "motion to",
        "motion for",
    ],
    "corporate": ["llc", "corporation", "operating agreement", "bylaws", "articles"],
    "other": [],
}
# Mirrors ContentClassifier.patterns["personal"]["subcategories"]["legal"].
PERSONAL_LEGAL_CUES = ["dui", "court", "citation", "traffic ticket", "hearing", "dmv"]

# One legal signal only ('court').
ONE_HIT_TEXT = "The court will publish the season schedule shortly for all teams."
# Exactly two legal signals: 'plaintiff' + 'court'.
TWO_HIT_TEXT = "The plaintiff filed the required paperwork with the court on Monday morning."
# Three legal signals: 'court', 'cause no', 'hearing' (clerk contact block).
COURT_NOTICE_TEXT = (
    "NOTICE OF COURT SETTING. Cause No 24-1234. A hearing is set. Contact "
    "the clerk with questions. Phone: 512-555-0100. Email: clerk@county.gov."
)
# All nine legal signals — enough extra hits to reach the cap.
ALL_SIGNALS_TEXT = (
    "The court docket lists plaintiff and defendant for the hearing; "
    "petitioner and respondent await judicial review. Cause no 5."
)
# Four legal signals + dui/citation personal cues.
DUI_TEXT = (
    "Notice of DUI citation. The defendant must appear at the court hearing "
    "listed on the docket."
)
# Three legal signals, none of which hit the fake contracts-only subcats.
NO_SUBCAT_TEXT = "The petitioner and respondent met before the judicial panel yesterday."


class FakeClassifier:
    def __init__(self, people=None, legal_subcategories=None, personal_cues=None):
        self.patterns = {
            "legal": {
                "subcategories": (
                    legal_subcategories if legal_subcategories is not None else LEGAL_SUBCATEGORIES
                )
            },
            "personal": {
                "subcategories": {
                    "legal": personal_cues if personal_cues is not None else PERSONAL_LEGAL_CUES
                }
            },
        }
        self.people = people if people is not None else []

    def extract_people_names(self, text):
        return list(self.people)


def make_ctx(text, path="/tmp/notice.pdf"):
    return FileContext(
        path=Path(path),
        schema_type="DigitalDocument",
        text_provider=lambda _p: text,
    )


class TestSignalContract:
    def test_identity(self):
        signal = LegalContentSignal(FakeClassifier())
        assert signal.name == "legal_content"
        assert signal.weight == W_LEGAL
        assert signal.cost_tier == "mid"

    def test_scores_tagged_with_signal_name(self):
        signal = LegalContentSignal(FakeClassifier())
        for score in signal.run(make_ctx(TWO_HIT_TEXT)):
            assert score.signal_name == signal.name


class TestAppliesTo:
    def test_text_length_gate(self):
        signal = LegalContentSignal(FakeClassifier())
        assert not signal.applies_to(make_ctx("x" * (LEGAL_MIN_TEXT_CHARS - 1)))
        assert signal.applies_to(make_ctx("x" * LEGAL_MIN_TEXT_CHARS))


class TestRun:
    def test_below_min_hits_emits_nothing(self):
        signal = LegalContentSignal(FakeClassifier())
        assert signal.run(make_ctx(ONE_HIT_TEXT)) == []

    def test_two_hits_base_confidence_with_subcategory(self):
        signal = LegalContentSignal(FakeClassifier(people=["Alyshia Ledlie"]))
        scores = signal.run(make_ctx(TWO_HIT_TEXT))
        legal = scores[0]
        assert (legal.category, legal.subcategory) == ("legal", "litigation")
        assert legal.confidence == pytest.approx(LEGAL_CONFIDENCE_BASE)
        assert legal.evidence["legal_hits"] == 2
        assert legal.evidence["matched_signals"] == ["court", "plaintiff"]
        assert legal.evidence["people_names"] == ["Alyshia Ledlie"]

    def test_confidence_scales_per_extra_hit(self):
        signal = LegalContentSignal(FakeClassifier())
        legal = signal.run(make_ctx(COURT_NOTICE_TEXT))[0]
        assert legal.evidence["legal_hits"] == 3
        assert legal.confidence == pytest.approx(0.8)
        assert legal.evidence["matched_signals"] == ["cause no", "court", "hearing"]

    def test_confidence_capped_at_one(self):
        signal = LegalContentSignal(FakeClassifier())
        legal = signal.run(make_ctx(ALL_SIGNALS_TEXT))[0]
        assert legal.evidence["legal_hits"] == 9
        assert legal.confidence == 1.0

    def test_subcategory_defaults_to_other(self):
        classifier = FakeClassifier(
            legal_subcategories={"contracts": ["notarized agreement"], "other": []},
            personal_cues=["dui"],
        )
        signal = LegalContentSignal(classifier)
        scores = signal.run(make_ctx(NO_SUBCAT_TEXT))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("legal", "other")

    def test_personal_legal_cues_add_second_emission(self):
        signal = LegalContentSignal(FakeClassifier(people=["Jane Doe"]))
        scores = signal.run(make_ctx(DUI_TEXT))
        assert len(scores) == 2
        legal, personal = scores
        assert (legal.category, legal.subcategory) == ("legal", "litigation")
        assert legal.confidence == pytest.approx(0.9)
        assert (personal.category, personal.subcategory) == ("personal", "legal")
        assert personal.confidence == pytest.approx(LEGAL_PERSONAL_CONFIDENCE)
        assert personal.evidence["personal_legal_cues"] == ["dui", "court", "citation", "hearing"]
        # Option C: people evidence rides on both emissions.
        assert personal.evidence["people_names"] == ["Jane Doe"]

    def test_people_names_key_present_even_when_empty(self):
        signal = LegalContentSignal(FakeClassifier(people=[]))
        legal = signal.run(make_ctx(TWO_HIT_TEXT))[0]
        assert legal.evidence["people_names"] == []


class TestCompetitionShape:
    def test_legal_and_person_both_emit_on_court_notice(self):
        # §3.3: the hard person-tier veto becomes competition. Both signals
        # emit on a clerk-contact court notice; legal's weighted contribution
        # outscores the ungated person emission on this fixture.
        classifier = FakeClassifier(people=["Alyshia Ledlie"])
        ctx = make_ctx(COURT_NOTICE_TEXT)

        legal_scores = LegalContentSignal(classifier).run(ctx)
        person_scores = PersonalDocSignal(classifier).run(ctx)

        assert legal_scores, "legal must emit at >=2 signal hits"
        assert person_scores, "person must emit without the legacy veto"
        legal_weighted = W_LEGAL * legal_scores[0].confidence
        person_weighted = W_PERSON * person_scores[0].confidence
        assert legal_weighted > person_weighted


class TestPureHelpers:
    def test_count_legal_signals_sorted(self):
        hits, matched = count_legal_signals(COURT_NOTICE_TEXT.lower())
        assert hits == 3
        assert matched == ["cause no", "court", "hearing"]

    def test_legal_confidence_scaling(self):
        assert legal_confidence(2) == pytest.approx(0.7)
        assert legal_confidence(4) == pytest.approx(0.9)
        assert legal_confidence(9) == 1.0

    def test_score_legal_subcategory_first_max_wins(self):
        text = "lease agreement"  # contracts: 'agreement'; real_estate: 'lease'
        assert score_legal_subcategory(text, LEGAL_SUBCATEGORIES) == "contracts"

    def test_score_legal_subcategory_default(self):
        assert score_legal_subcategory("nothing legal here", LEGAL_SUBCATEGORIES) == "other"
