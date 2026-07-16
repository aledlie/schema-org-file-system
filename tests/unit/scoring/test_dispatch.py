"""ContentOrganizer --scorer dispatch tests (UNIFIED_SCORING_PLAN §6 Phase 0).

Pins the Phase-0 contract: legacy default is bit-for-bit untouched, unified
mode routes through the (currently empty) registry, shadow mode returns the
legacy result while appending a JSONL comparison record.
"""

import json

import pytest

from src.organizers.content_organizer import ContentOrganizer, _derive_schema_type
from src.scoring.types import SCORER_LEGACY, SCORER_MODES


def make_organizer(tmp_path, **kwargs):
    return ContentOrganizer(base_path=tmp_path, content_classifier=None, **kwargs)


class TestScorerModePlumbing:
    def test_default_is_legacy(self, tmp_path):
        organizer = make_organizer(tmp_path)
        assert organizer.scorer_mode == SCORER_LEGACY

    @pytest.mark.parametrize("mode", SCORER_MODES)
    def test_valid_modes_accepted(self, tmp_path, mode):
        assert make_organizer(tmp_path, scorer=mode).scorer_mode == mode

    def test_invalid_mode_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="scorer must be one of"):
            make_organizer(tmp_path, scorer="quantum")


class TestUnifiedDispatch:
    def test_unified_no_signal_match_returns_fallback_tuple(self, tmp_path):
        """A file no registered signal can commit on routes to the fallback
        bucket (classifier=None here, so only the degraded registry runs)."""
        organizer = make_organizer(tmp_path, scorer="unified")
        sample = tmp_path / "mystery.bin"
        sample.write_bytes(b"\x00\x01")
        category, subcategory, schema_type, text, company, people, metadata = (
            organizer.detect_file_category(sample)
        )
        assert (category, subcategory) == ("uncategorized", "other")
        assert schema_type == "DigitalDocument"
        assert text == ""
        assert company is None
        assert people == []
        assert metadata == {}

    def test_unified_commits_on_strong_cheap_signal(self, tmp_path):
        """Populated registry: a numbered-sprite filename commits via
        GameAssetSignal (+ FilenamePatternSignal) without content extraction."""
        organizer = make_organizer(tmp_path, scorer="unified")
        sample = tmp_path / "frame_1.png"
        sample.write_bytes(b"\x89PNG\r\n")
        category, subcategory, *_ = organizer.detect_file_category(sample)
        assert (category, subcategory) == ("game_assets", "sprites")
        snapshot = organizer._last_file_state["scoring_decision"]
        assert snapshot["decision"]["decision_state"] == "committed"
        assert snapshot["scorer"] == "unified"

    def test_unified_resets_per_file_state(self, tmp_path):
        organizer = make_organizer(tmp_path, scorer="unified")
        organizer._last_file_ocr_text = "stale"
        organizer._last_file_state["kie_result"] = "stale"
        sample = tmp_path / "mystery.bin"
        sample.write_bytes(b"\x00\x01")
        organizer.detect_file_category(sample)
        assert organizer._last_file_ocr_text is None
        assert "kie_result" not in organizer._last_file_state


class TestShadowDispatch:
    def test_shadow_returns_legacy_and_logs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        organizer = make_organizer(tmp_path, scorer="shadow")
        sample = tmp_path / "frame_1.png"
        sample.write_bytes(b"\x89PNG\r\n")

        legacy_expected = make_organizer(tmp_path).detect_file_category(sample)
        shadow_result = organizer.detect_file_category(sample)
        assert shadow_result == legacy_expected

        log_path = tmp_path / "results" / "scoring_shadow.jsonl"
        assert log_path.exists()
        record = json.loads(log_path.read_text().splitlines()[-1])
        assert record["path"] == str(sample)
        assert record["legacy_decision"]["category"] == legacy_expected[0]
        # frame_1.png: both engines resolve game_assets/sprites (cheap signals).
        assert record["decision"]["decision_state"] == "committed"
        assert (record["decision"]["category"], record["decision"]["subcategory"]) == (
            legacy_expected[0],
            legacy_expected[1],
        )
        assert record["agrees"] is True

    def test_shadow_never_breaks_classification(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        organizer = make_organizer(tmp_path, scorer="shadow")

        def explode(*args, **kwargs):
            raise RuntimeError("scorer exploded")

        monkeypatch.setattr(organizer, "_build_file_context", explode)
        sample = tmp_path / "frame_1.png"
        sample.write_bytes(b"\x89PNG\r\n")
        legacy_expected = make_organizer(tmp_path).detect_file_category(sample)
        assert organizer.detect_file_category(sample) == legacy_expected


class TestSchemaTypeDerivation:
    @pytest.mark.parametrize(
        ("mime_type", "expected"),
        [
            ("image/png", "ImageObject"),
            ("application/pdf", "DigitalDocument"),
            ("video/mp4", "VideoObject"),
            ("audio/mpeg", "AudioObject"),
            ("text/plain", "DigitalDocument"),
            (None, "DigitalDocument"),
        ],
    )
    def test_mapping(self, mime_type, expected):
        assert _derive_schema_type(mime_type) == expected
