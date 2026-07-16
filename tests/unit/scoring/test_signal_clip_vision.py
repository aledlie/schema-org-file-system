"""ClipVisionSignal tests (UNIFIED_SCORING_PLAN §4 row 11).

Synthetic FileContext with fake CLIP/metadata providers — no models, no
disk I/O. Covers the image gate, top-N emission at raw scores (soft floor —
no CLIP_ENHANCE_THRESHOLD hard gate), the GPS travel upgrade, unmapped-label
skips, evidence payloads, and the legacy _GEOGRAPHIC_LABELS alias.
"""

from pathlib import Path

import pytest

from src.organizers.content_organizer import ContentOrganizer
from src.scoring.context import FileContext
from src.scoring.signals.clip_vision import (
    CLIP_TOP_EMISSIONS,
    GEOGRAPHIC_LABELS,
    ClipVisionSignal,
    map_clip_label,
)

GPS_METADATA = {"gps_coordinates": (30.27, -97.74)}


def make_ctx(clip_scores=None, image_metadata=None, schema_type="ImageObject"):
    return FileContext(
        path=Path("/tmp/img.png"),
        schema_type=schema_type,
        clip_provider=(lambda _path: clip_scores) if clip_scores is not None else None,
        image_metadata_provider=(
            (lambda _path: image_metadata) if image_metadata is not None else None
        ),
    )


@pytest.fixture()
def signal() -> ClipVisionSignal:
    return ClipVisionSignal()


class TestMapClipLabel:
    LABEL_MAP = {
        "food or a meal": ("media", "photos_lifestyle"),
        "a landscape or nature scene": ("media", "photos_nature"),
    }

    def test_known_label_maps(self) -> None:
        result = map_clip_label("food or a meal", None, self.LABEL_MAP, GEOGRAPHIC_LABELS)
        assert result == ("media", "photos_lifestyle")

    def test_unknown_label_returns_none(self) -> None:
        assert map_clip_label("mystery", None, self.LABEL_MAP, GEOGRAPHIC_LABELS) is None

    def test_geographic_label_with_gps_upgrades_to_travel(self) -> None:
        result = map_clip_label(
            "a landscape or nature scene", GPS_METADATA, self.LABEL_MAP, GEOGRAPHIC_LABELS
        )
        assert result == ("media", "photos_travel")

    def test_geographic_label_without_gps_keeps_mapping(self) -> None:
        result = map_clip_label(
            "a landscape or nature scene", {}, self.LABEL_MAP, GEOGRAPHIC_LABELS
        )
        assert result == ("media", "photos_nature")

    def test_non_geographic_label_ignores_gps(self) -> None:
        result = map_clip_label("food or a meal", GPS_METADATA, self.LABEL_MAP, GEOGRAPHIC_LABELS)
        assert result == ("media", "photos_lifestyle")

    def test_organizer_class_attr_aliases_module_constant(self) -> None:
        assert ContentOrganizer._GEOGRAPHIC_LABELS is GEOGRAPHIC_LABELS


class TestAppliesTo:
    def test_image_applies(self, signal: ClipVisionSignal) -> None:
        assert signal.applies_to(make_ctx({}))

    def test_document_gated(self, signal: ClipVisionSignal) -> None:
        assert not signal.applies_to(make_ctx({}, schema_type="DigitalDocument"))


class TestRun:
    def test_empty_scores_emit_nothing(self, signal: ClipVisionSignal) -> None:
        assert signal.run(make_ctx({})) == []
        assert signal.run(make_ctx(None)) == []

    def test_top_labels_emitted_at_raw_score(self, signal: ClipVisionSignal) -> None:
        scores = {"food or a meal": 0.5, "a document or text": 0.4}
        emissions = signal.run(make_ctx(scores))
        assert [(e.category, e.subcategory, e.confidence) for e in emissions] == [
            ("media", "photos_lifestyle", 0.5),
            ("media", "photos_documents", 0.4),
        ]

    def test_only_top_n_labels_considered(self, signal: ClipVisionSignal) -> None:
        scores = {
            "food or a meal": 0.5,
            "a document or text": 0.4,
            "people or portrait": 0.3,
            "an animal or pet": 0.2,
        }
        assert len(scores) > CLIP_TOP_EMISSIONS
        emissions = signal.run(make_ctx(scores))
        labels = [e.evidence["clip_label"] for e in emissions]
        assert labels == ["food or a meal", "a document or text", "people or portrait"]

    def test_unmapped_label_occupies_slot_but_is_skipped(self, signal: ClipVisionSignal) -> None:
        scores = {
            "not a real clip label": 0.9,
            "food or a meal": 0.5,
            "a document or text": 0.4,
            "people or portrait": 0.3,
        }
        emissions = signal.run(make_ctx(scores))
        # The unknown label ranks first in the top-3 window and is skipped;
        # the fourth label falls outside the window.
        labels = [e.evidence["clip_label"] for e in emissions]
        assert labels == ["food or a meal", "a document or text"]

    def test_weak_scores_still_emitted_soft_floor(self, signal: ClipVisionSignal) -> None:
        # Below the legacy CLIP_ENHANCE_THRESHOLD hard gate: by design the
        # unified signal emits anyway and lets aggregation weigh it down.
        emissions = signal.run(make_ctx({"food or a meal": 0.05}))
        assert len(emissions) == 1
        assert emissions[0].confidence == pytest.approx(0.05)

    def test_gps_upgrades_geographic_label(self, signal: ClipVisionSignal) -> None:
        emissions = signal.run(
            make_ctx({"a landscape or nature scene": 0.6}, image_metadata=GPS_METADATA)
        )
        assert (emissions[0].category, emissions[0].subcategory) == ("media", "photos_travel")

    def test_no_gps_keeps_nature_mapping(self, signal: ClipVisionSignal) -> None:
        emissions = signal.run(make_ctx({"a landscape or nature scene": 0.6}))
        assert (emissions[0].category, emissions[0].subcategory) == ("media", "photos_nature")

    def test_evidence_payload_and_signal_name(self, signal: ClipVisionSignal) -> None:
        emissions = signal.run(make_ctx({"food or a meal": 0.42}))
        score = emissions[0]
        assert score.signal_name == "clip_vision"
        assert score.evidence == {"clip_label": "food or a meal", "clip_score": 0.42}
