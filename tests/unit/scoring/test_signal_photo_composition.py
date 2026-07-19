"""PhotoCompositionSignal tests (UNIFIED_SCORING_PLAN §4 row 13).

Fake image analyzer + synthetic FileContext — no CLIP model. Covers the
image/availability applies_to gates, the people flag, top-3 composition-score
evidence, and []-emission. The interior (``is_property_mgmt``) vote was
retired 2026-07-18 — interior detection belongs to SceneSignal
(test_signal_scene.py) — so the analyzer's property flag must be ignored.
"""

from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.photo_composition import (
    PHOTO_PEOPLE_CONFIDENCE,
    PhotoCompositionSignal,
)


class FakeImageAnalyzer:
    def __init__(self, has_people=False, is_property=False, scores=None, available=True):
        self.vision_available = available
        self._result = (has_people, is_property, scores if scores is not None else {})
        self.calls = 0

    def analyze_for_organization(self, path):
        self.calls += 1
        return self._result


def make_ctx(schema_type="ImageObject"):
    return FileContext(path=Path("/tmp/img.jpg"), schema_type=schema_type)


class TestAppliesTo:
    def test_image_with_vision_applies(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer())
        assert signal.applies_to(make_ctx())

    def test_document_gated(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer())
        assert not signal.applies_to(make_ctx(schema_type="DigitalDocument"))

    def test_missing_analyzer_gated(self) -> None:
        signal = PhotoCompositionSignal(None)
        assert not signal.applies_to(make_ctx())

    def test_vision_unavailable_gated(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer(available=False))
        assert not signal.applies_to(make_ctx())


class TestRun:
    def test_people_route_to_social(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer(has_people=True))
        emissions = signal.run(make_ctx())
        assert len(emissions) == 1
        score = emissions[0]
        assert (score.category, score.subcategory) == ("media", "photos_social")
        assert score.confidence == pytest.approx(PHOTO_PEOPLE_CONFIDENCE)
        assert score.signal_name == "photo_composition"

    def test_property_flag_alone_emits_nothing(self) -> None:
        # Retired vote: interiors are SceneSignal's job now.
        signal = PhotoCompositionSignal(FakeImageAnalyzer(is_property=True))
        assert signal.run(make_ctx()) == []

    def test_people_still_route_when_property_flag_set(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer(has_people=True, is_property=True))
        emissions = signal.run(make_ctx())
        assert (emissions[0].category, emissions[0].subcategory) == ("media", "photos_social")

    def test_no_composition_match_emits_nothing(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer())
        assert signal.run(make_ctx()) == []

    def test_single_analyzer_pass(self) -> None:
        analyzer = FakeImageAnalyzer(has_people=True)
        PhotoCompositionSignal(analyzer).run(make_ctx())
        assert analyzer.calls == 1


class TestEvidence:
    SCORES = {
        "a photo of people": 0.9,
        "an interior room": 0.5,
        "a photo of food": 0.3,
        "a screenshot": 0.1,
    }

    def test_top_three_scores_kept(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer(has_people=True, scores=self.SCORES))
        evidence = signal.run(make_ctx())[0].evidence
        assert evidence["composition_scores"] == {
            "a photo of people": 0.9,
            "an interior room": 0.5,
            "a photo of food": 0.3,
        }

    def test_empty_scores_leave_evidence_empty(self) -> None:
        signal = PhotoCompositionSignal(FakeImageAnalyzer(has_people=True, scores={}))
        assert signal.run(make_ctx())[0].evidence == {}
