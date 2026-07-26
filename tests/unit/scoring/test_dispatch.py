"""ContentOrganizer scorer dispatch tests.

Phase 5 removed the legacy tier chain and shadow mode; ``unified`` is the
only engine. Pins mode validation, the unified fallback/commit contract,
per-file state reset, and schema-type derivation.
"""

import pytest

from src.organizers.content_organizer import ContentOrganizer, _derive_schema_type
from src.scoring.types import SCORER_DEFAULT, SCORER_MODES, SCORER_UNIFIED


def make_organizer(tmp_path, **kwargs):
    return ContentOrganizer(base_path=tmp_path, content_classifier=None, **kwargs)


class TestScorerModePlumbing:
    def test_default_is_unified(self, tmp_path):
        organizer = make_organizer(tmp_path)
        assert organizer.scorer_mode == SCORER_DEFAULT == SCORER_UNIFIED

    @pytest.mark.parametrize("mode", SCORER_MODES)
    def test_valid_modes_accepted(self, tmp_path, mode):
        assert make_organizer(tmp_path, scorer=mode).scorer_mode == mode

    @pytest.mark.parametrize("mode", ["legacy", "shadow", "quantum"])
    def test_invalid_mode_rejected(self, tmp_path, mode):
        # legacy/shadow were removed in Phase 5 and now reject like any
        # unknown mode.
        with pytest.raises(ValueError, match="scorer must be one of"):
            make_organizer(tmp_path, scorer=mode)


class TestUnifiedDispatch:
    def test_unified_no_signal_match_returns_fallback_tuple(self, tmp_path):
        """A file no registered signal can commit on routes to the fallback
        bucket (classifier=None here, so only the degraded registry runs)."""
        organizer = make_organizer(tmp_path)
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
        organizer = make_organizer(tmp_path)
        sample = tmp_path / "frame_1.png"
        sample.write_bytes(b"\x89PNG\r\n")
        category, subcategory, *_ = organizer.detect_file_category(sample)
        assert (category, subcategory) == ("game_assets", "sprites")
        snapshot = organizer._last_file_state["scoring_decision"]
        assert snapshot["decision"]["decision_state"] == "committed"
        assert snapshot["scorer"] == "unified"

    def test_unified_resets_per_file_state(self, tmp_path):
        organizer = make_organizer(tmp_path)
        organizer._last_file_ocr_text = "stale"
        organizer._last_file_state["kie_result"] = "stale"
        sample = tmp_path / "mystery.bin"
        sample.write_bytes(b"\x00\x01")
        organizer.detect_file_category(sample)
        assert organizer._last_file_ocr_text is None
        assert "kie_result" not in organizer._last_file_state


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
