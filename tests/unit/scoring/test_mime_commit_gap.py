"""Mime commit-gap calibration invariants (BACKLOG Phase-3 item #1).

W_MIME was raised 0.3 → 0.4 so an extension-only file commits (restoring the
legacy tier-6 MIME rescue) without letting MIME override genuine content.
These tests pin the numeric relationship between W_MIME and the decision
thresholds, and the emergent scorer behavior, so a future re-tune that breaks
either trips here.
"""

from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.scorer import Scorer
from src.scoring.signals.mime_fallback import MIME_MATCH_CONFIDENCE
from src.scoring.types import CategoryScore
from src.scoring.weights import (
    MIN_DECISION_CONFIDENCE,
    MIN_DECISION_MARGIN,
    W_MIME,
)


class TestThresholdInvariants:
    def test_mime_commits_alone(self):
        """A mime-only file must clear the confidence floor."""
        assert W_MIME * MIME_MATCH_CONFIDENCE >= MIN_DECISION_CONFIDENCE

    def test_mime_cannot_outcommit_floor_clearing_content(self):
        """MIME must never commit *over* a content signal that itself clears
        the floor: a MIME guess disagreeing with content at exactly the floor
        leads by < MIN_DECISION_MARGIN, so both route to fallback."""
        assert W_MIME * MIME_MATCH_CONFIDENCE < MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN


class FakeSignal:
    def __init__(self, name, weight, cost_tier, scores):
        self.name = name
        self.weight = weight
        self.cost_tier = cost_tier
        self._scores = scores

    def applies_to(self, ctx):
        return True

    def run(self, ctx):
        return [CategoryScore(cat, sub, conf, self.name, {}) for cat, sub, conf in self._scores]


def mime_signal():
    return FakeSignal("mime_fallback", W_MIME, "cheap", [("media", "graphics_other", 1.0)])


def make_ctx():
    return FileContext(path=Path("/tmp/x.png"), schema_type="ImageObject")


class TestEmergentBehavior:
    def test_mime_only_commits(self):
        decision = Scorer([mime_signal()]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("media", "graphics_other")
        assert decision.decision_state == "committed"

    def test_confident_content_out_commits_mime(self):
        # Content winner at 0.6 weighted beats mime's 0.4 by ≥ margin.
        content = FakeSignal("text_content", 0.8, "heavy", [("technical", "other", 0.75)])
        decision = Scorer([mime_signal(), content]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("technical", "other")
        assert decision.decision_state == "committed"

    def test_mime_vs_floor_clearing_content_disagreement_falls_to_fallback(self):
        # Content clears the floor (0.9*0.4=0.36 ≥ 0.35) but mime (0.4)
        # disagrees; lead 0.04 < margin → neither commits, no MIME override.
        content = FakeSignal("text_content", 0.4, "heavy", [("legal", "contracts", 0.9)])
        decision = Scorer([mime_signal(), content]).classify(make_ctx())
        assert decision.decision_state == "low_margin"
        assert (decision.category, decision.subcategory) == ("uncategorized", "other")

    def test_mime_outcommits_only_subfloor_content(self):
        # Content below the floor (0.3 weighted) can't commit anyway; mime
        # committing its own category here is not overriding a valid decision.
        content = FakeSignal("filepath", 0.6, "cheap", [("technical", "logs", 0.5)])
        decision = Scorer([mime_signal(), content]).classify(make_ctx())
        # filepath 0.6*0.5=0.30 < floor; mime 0.40 wins by 0.10 == margin.
        assert (decision.category, decision.subcategory) == ("media", "graphics_other")
        assert decision.decision_state == "committed"


@pytest.mark.parametrize(
    "weaker",
    [
        ("filepath", 0.6),
        ("media_heuristic", 0.65),
        ("clip_vision", 0.7),
        ("screenshot_ocr", 0.75),
        ("text_content", 0.8),
    ],
)
def test_mime_loses_to_every_stronger_signal_at_full_confidence(weaker):
    """At full signal confidence every non-mime signal outweighs mime."""
    name, weight = weaker
    other = FakeSignal(name, weight, "cheap", [("technical", "other", 1.0)])
    decision = Scorer([mime_signal(), other]).classify(make_ctx())
    assert (decision.category, decision.subcategory) == ("technical", "other")
