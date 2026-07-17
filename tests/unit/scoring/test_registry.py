"""Registry population tests (UNIFIED_SCORING_PLAN §3.4 / §4)."""

from unittest.mock import MagicMock

from src.scoring.registry import build_default_signals
from src.scoring.scorer import Scorer
from src.scoring.types import COST_TIER_PRIORITY, Signal

# §4 table order, priors descending — registration order is load-bearing.
FULL_REGISTRY_ORDER = [
    "renamed_screenshot",
    "filename_pattern",
    "kie_structured",
    "identity_document",
    "organization_keyword",
    "personal_doc",
    "legal_content",
    "interior",
    "game_asset",
    "text_content",
    "screenshot_ocr",
    "clip_vision",
    "media_heuristic",
    "photo_composition",
    "filepath",
    "mime_fallback",
]

CLASSIFIER_DEPENDENT = {
    "kie_structured",
    "identity_document",
    "organization_keyword",
    "personal_doc",
    "legal_content",
    "text_content",
}


def build_full():
    return build_default_signals(
        classifier=MagicMock(),
        screenshot_classifier=MagicMock(),
        image_analyzer=MagicMock(),
        category_paths={"media": {"photos": {"screenshots": {"terminal": "T", "other": "O"}}}},
        game_sprite_keywords=["sprite"],
    )


class TestFullRegistry:
    def test_all_sixteen_signals_in_plan_order(self):
        assert [s.name for s in build_full()] == FULL_REGISTRY_ORDER

    def test_every_entry_satisfies_signal_protocol(self):
        for signal in build_full():
            assert isinstance(signal, Signal)
            assert signal.cost_tier in COST_TIER_PRIORITY
            assert 0.0 < signal.weight <= 1.2

    def test_weights_descend_in_registry_order(self):
        weights = [s.weight for s in build_full()]
        assert weights == sorted(weights, reverse=True)

    def test_scorer_accepts_registry(self):
        # Names unique, tiers valid — the Scorer constructor validates both.
        Scorer(build_full())


class TestDegradedRegistry:
    def test_no_classifier_omits_dependent_signals(self):
        names = {s.name for s in build_default_signals()}
        assert names == set(FULL_REGISTRY_ORDER) - CLASSIFIER_DEPENDENT

    def test_no_classifier_preserves_relative_order(self):
        names = [s.name for s in build_default_signals()]
        expected = [n for n in FULL_REGISTRY_ORDER if n not in CLASSIFIER_DEPENDENT]
        assert names == expected

    def test_missing_category_paths_defaults_empty(self):
        # No screenshots taxonomy → renamed/ocr signals get empty key sets.
        signals = build_default_signals()
        assert any(s.name == "renamed_screenshot" for s in signals)
