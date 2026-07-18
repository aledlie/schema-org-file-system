"""InteriorSignal tests — trained CLIP-embedding probe (C1).

Fake pipeline + monkeypatched embedding accessor — no joblib artifact, no CLIP
model. Covers the image/artifact applies_to gates, the probability threshold,
the schema.org ``Room`` override, and graceful no-ops.
"""

from pathlib import Path

import numpy as np
import pytest

from src.scoring.context import FileContext
from src.scoring.signals import interior as interior_mod
from src.scoring.signals.interior import (
    EVIDENCE_INTERIOR_PROB,
    INTERIOR_MIN_PROB,
    InteriorSignal,
)
from src.scoring.types import EVIDENCE_SCHEMA_TYPE


class FakePipeline:
    def __init__(self, prob):
        self._p = prob

    def predict_proba(self, X):
        return np.array([[1.0 - self._p, self._p]])


def make_ctx(schema_type="ImageObject"):
    return FileContext(path=Path("/tmp/x.jpg"), schema_type=schema_type)


def signal_with(prob=None):
    # Nonexistent artifact -> _pipeline None; inject a fake when a prob is given.
    signal = InteriorSignal(probe_path=Path("/nonexistent.joblib"))
    if prob is not None:
        signal._pipeline = FakePipeline(prob)
    return signal


class TestAppliesTo:
    def test_missing_artifact_gated(self):
        assert signal_with().applies_to(make_ctx()) is False

    def test_image_with_pipeline_applies(self):
        assert signal_with(prob=0.9).applies_to(make_ctx())

    def test_document_gated(self):
        assert not signal_with(prob=0.9).applies_to(make_ctx(schema_type="DigitalDocument"))


class TestRun:
    def test_high_prob_emits_room(self, monkeypatch):
        monkeypatch.setattr(interior_mod, "_get_embedding", lambda p: np.zeros(512))
        scores = signal_with(prob=0.97).run(make_ctx())
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "interiors_other")
        assert score.confidence == pytest.approx(0.97)
        assert score.evidence[EVIDENCE_SCHEMA_TYPE] == "Room"
        assert score.evidence[EVIDENCE_INTERIOR_PROB] == pytest.approx(0.97, abs=1e-3)

    def test_below_threshold_emits_nothing(self, monkeypatch):
        monkeypatch.setattr(interior_mod, "_get_embedding", lambda p: np.zeros(512))
        assert signal_with(prob=INTERIOR_MIN_PROB - 0.01).run(make_ctx()) == []

    def test_no_embedding_emits_nothing(self, monkeypatch):
        # CLIP unavailable / unreadable image -> accessor returns None -> no-op.
        monkeypatch.setattr(interior_mod, "_get_embedding", lambda p: None)
        assert signal_with(prob=0.99).run(make_ctx()) == []
