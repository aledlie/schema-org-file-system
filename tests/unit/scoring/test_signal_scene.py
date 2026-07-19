"""SceneSignal tests — multinomial scene probe (MEDIA_EXTERIORS_PLAN step 2).

Fake pipeline + monkeypatched embedding accessor — no joblib artifact, no CLIP
model. Covers the image/artifact applies_to gates, per-class routing and
schema.org overrides, the ``neither`` reject class, the probability threshold,
predict_proba column-order mapping, artifact loading, and graceful no-ops.
"""

from pathlib import Path

import numpy as np
import pytest

from src.scoring.context import FileContext
from src.scoring.signals import scene as scene_mod
from src.scoring.signals.scene import (
    EVIDENCE_SCENE_CLASS,
    EVIDENCE_SCENE_PROB,
    SCENE_MIN_PROB,
    SceneSignal,
    load_probe,
)
from src.scoring.types import EVIDENCE_SCHEMA_TYPE

# Trainer default column order: neither, interior, exterior, place.
DEFAULT_ORDER = ["neither", "interior", "exterior", "place"]


class FakePipeline:
    def __init__(self, probs):
        self._probs = list(probs)

    def predict_proba(self, X):
        return np.array([self._probs])


def make_ctx(schema_type="ImageObject"):
    return FileContext(path=Path("/tmp/x.jpg"), schema_type=schema_type)


def signal_with(probs=None, class_order=DEFAULT_ORDER):
    # Nonexistent artifact -> _pipeline None; inject a fake when probs given.
    signal = SceneSignal(probe_path=Path("/nonexistent.joblib"))
    if probs is not None:
        signal._pipeline = FakePipeline(probs)
        signal._class_order = list(class_order)
    return signal


class TestAppliesTo:
    def test_missing_artifact_gated(self):
        signal = signal_with()
        assert signal.is_loaded is False
        assert signal.applies_to(make_ctx()) is False

    def test_image_with_pipeline_applies(self):
        signal = signal_with(probs=[0.0, 0.9, 0.05, 0.05])
        assert signal.is_loaded is True
        assert signal.applies_to(make_ctx())

    def test_document_gated(self):
        signal = signal_with(probs=[0.0, 0.9, 0.05, 0.05])
        assert not signal.applies_to(make_ctx(schema_type="DigitalDocument"))


class TestRun:
    @pytest.fixture(autouse=True)
    def _stub_embedding(self, monkeypatch):
        monkeypatch.setattr(scene_mod, "_get_embedding", lambda p: np.zeros(512))

    @pytest.mark.parametrize(
        "probs,subcategory,schema_type,scene_class",
        [
            ([0.01, 0.95, 0.02, 0.02], "interiors_other", "Room", "interior"),
            ([0.01, 0.02, 0.95, 0.02], "exteriors_other", "House", "exterior"),
            ([0.01, 0.02, 0.02, 0.95], "place_other", "Place", "place"),
        ],
    )
    def test_positive_argmax_routes_class(self, probs, subcategory, schema_type, scene_class):
        scores = signal_with(probs=probs).run(make_ctx())
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", subcategory)
        assert score.confidence == pytest.approx(0.95)
        assert score.evidence[EVIDENCE_SCHEMA_TYPE] == schema_type
        assert score.evidence[EVIDENCE_SCENE_CLASS] == scene_class
        assert score.evidence[EVIDENCE_SCENE_PROB] == pytest.approx(0.95, abs=1e-3)

    def test_graphic_argmax_routes_to_graphics_other(self):
        # 5-class artifact (graphic added): the graphic column winning routes to
        # media/graphics_other with the generic ImageObject @type. A pre-graphic
        # 4-class artifact still loads — SceneSignal ignores unknown columns.
        scores = signal_with(
            probs=[0.01, 0.02, 0.01, 0.02, 0.94],
            class_order=DEFAULT_ORDER + ["graphic"],
        ).run(make_ctx())
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "graphics_other")
        assert score.evidence[EVIDENCE_SCHEMA_TYPE] == "ImageObject"
        assert score.evidence[EVIDENCE_SCENE_CLASS] == "graphic"
        assert score.evidence[EVIDENCE_SCENE_PROB] == pytest.approx(0.94, abs=1e-3)

    def test_neither_argmax_emits_nothing(self):
        # Reject class wins -> no positive class clears the threshold.
        assert signal_with(probs=[0.85, 0.05, 0.05, 0.05]).run(make_ctx()) == []

    def test_positive_below_threshold_emits_nothing(self):
        probs = [1.0 - (SCENE_MIN_PROB - 0.01) - 0.02, SCENE_MIN_PROB - 0.01, 0.01, 0.01]
        assert signal_with(probs=probs).run(make_ctx()) == []

    def test_permuted_column_order_maps_correctly(self):
        # Column order comes from meta.classes, not the canonical label ints.
        scores = signal_with(
            probs=[0.9, 0.05, 0.03, 0.02],
            class_order=["place", "neither", "interior", "exterior"],
        ).run(make_ctx())
        assert len(scores) == 1
        assert scores[0].subcategory == "place_other"
        assert scores[0].evidence[EVIDENCE_SCHEMA_TYPE] == "Place"

    def test_no_embedding_emits_nothing(self, monkeypatch):
        # CLIP unavailable / unreadable image -> accessor returns None -> no-op.
        monkeypatch.setattr(scene_mod, "_get_embedding", lambda p: None)
        assert signal_with(probs=[0.0, 0.99, 0.005, 0.005]).run(make_ctx()) == []


class TestLoadProbe:
    def test_trainer_artifact_shape_loads(self, tmp_path):
        joblib = pytest.importorskip("joblib")
        artifact = tmp_path / "scene_probe.joblib"
        joblib.dump(
            {
                "pipeline": {"stub": True},
                "meta": {
                    "classes": [0, 1, 2, 3],
                    "class_names": {0: "neither", 1: "interior", 2: "exterior", 3: "place"},
                },
            },
            artifact,
        )
        loaded = load_probe(artifact)
        assert loaded is not None
        pipeline, order = loaded
        assert pipeline == {"stub": True}
        assert order == DEFAULT_ORDER

    def test_missing_class_names_falls_back_to_label_ints(self, tmp_path):
        joblib = pytest.importorskip("joblib")
        artifact = tmp_path / "scene_probe.joblib"
        joblib.dump({"pipeline": {"stub": True}, "meta": {"classes": [3, 0, 1, 2]}}, artifact)
        loaded = load_probe(artifact)
        assert loaded is not None
        assert loaded[1] == ["place", "neither", "interior", "exterior"]

    def test_missing_meta_contract_returns_none(self, tmp_path):
        joblib = pytest.importorskip("joblib")
        artifact = tmp_path / "scene_probe.joblib"
        joblib.dump({"pipeline": {"stub": True}}, artifact)
        assert load_probe(artifact) is None

    def test_corrupt_artifact_returns_none(self, tmp_path):
        corrupt = tmp_path / "corrupt.joblib"
        corrupt.write_bytes(b"not a joblib payload")
        assert load_probe(corrupt) is None

    def test_absent_artifact_returns_none(self, tmp_path):
        assert load_probe(tmp_path / "absent.joblib") is None


class TestSceneTaxonomyParity:
    """Lock the scene maps against taxonomy drift (moved from the retired
    photo_composition interior vote): every ROOM_SUBTYPE_SCHEMA key must have
    a Media/Interiors folder path, and every SCENE_CATEGORY target must
    resolve to its Media/<Scene> folder."""

    def test_room_schema_keys_match_folder_keys(self) -> None:
        from src.organizers.category_config import CONTENT_CATEGORY_PATHS
        from src.scoring.signals.scene import ROOM_SUBTYPE_SCHEMA

        folder = CONTENT_CATEGORY_PATHS["media"]["interiors"]
        assert set(folder) == set(ROOM_SUBTYPE_SCHEMA)

    def test_every_room_subtype_resolves_under_media_interiors(self) -> None:
        from src.organizers.category_config import CONTENT_CATEGORY_PATHS
        from src.scoring.signals.scene import ROOM_SUBTYPE_SCHEMA

        folder = CONTENT_CATEGORY_PATHS["media"]["interiors"]
        for key in ROOM_SUBTYPE_SCHEMA:
            assert folder[key].startswith("Media/Interiors")

    def test_scene_targets_resolve_in_media_taxonomy(self) -> None:
        from src.organizers.category_config import CONTENT_CATEGORY_PATHS
        from src.scoring.signals.scene import SCENE_CATEGORY

        media = CONTENT_CATEGORY_PATHS["media"]
        for scene_class, (category, subcategory) in SCENE_CATEGORY.items():
            assert category == "media"
            branch, key = subcategory.rsplit("_", 1)
            assert key in media[branch], (scene_class, subcategory)

    def test_interior_schema_is_generic_room(self) -> None:
        from src.scoring.signals.scene import ROOM_SUBTYPE_SCHEMA, SCENE_SCHEMA

        assert SCENE_SCHEMA["interior"] == ROOM_SUBTYPE_SCHEMA["other"] == "Room"
