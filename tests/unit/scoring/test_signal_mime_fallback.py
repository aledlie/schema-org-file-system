"""MimeFallbackSignal tests (UNIFIED_SCORING_PLAN §4 row 15)."""

from pathlib import Path

import pytest

from src.scoring.signals.mime_fallback import (
    MIME_MATCH_CONFIDENCE,
    MimeFallbackSignal,
    mime_result_to_content_category,
)
from src.scoring.context import FileContext
from src.scoring.scorer import Scorer
from src.scoring.weights import LOW_CONFIDENCE_FALLBACK, W_MIME


def make_ctx(path, schema_type="DigitalDocument"):
    return FileContext(path=Path(path), schema_type=schema_type)


class TestTranslation:
    @pytest.mark.parametrize(
        ("mime_result", "expected"),
        [
            (("images", "screenshots"), ("media", "photos_screenshots")),
            (("images", "graphics"), ("media", "graphics_other")),
            (("images", "photos"), ("media", "photos_other")),  # None-key default
            (("media", "music"), ("media", "audio_music")),
            (("media", "videos"), ("media", "videos_other")),
            (("media", "audio"), ("media", "audio_other")),  # None-key default
            (("software", "installers"), ("technical", "software_packages")),
            (("code", "web"), ("technical", "web")),
            (("code", "python"), ("technical", "other")),  # None-key default
            (("data", "config"), ("technical", "config")),
            (("data", "json"), ("technical", "data")),  # None-key default
            (("research", "papers"), ("research", "other")),
            (("fonts", "truetype"), ("fonts", "truetype")),  # identity passthrough
        ],
    )
    def test_translates_into_content_taxonomy(self, mime_result, expected):
        assert mime_result_to_content_category(*mime_result) == expected

    @pytest.mark.parametrize(
        "mime_result",
        [("documents", "pdf"), ("archives", "zip"), ("other", "other")],
    )
    def test_no_content_home_returns_none(self, mime_result):
        assert mime_result_to_content_category(*mime_result) is None


class TestSignalRun:
    def test_music_file_routes_to_audio_music(self):
        scores = MimeFallbackSignal().run(make_ctx("/tmp/song.mp3", "AudioObject"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "audio_music")
        assert score.confidence == MIME_MATCH_CONFIDENCE
        assert score.signal_name == "mime_fallback"
        assert score.evidence == {"mime_category": "media", "mime_subcategory": "music"}

    def test_photo_routes_to_photos_other(self):
        scores = MimeFallbackSignal().run(make_ctx("/tmp/photo.jpg", "ImageObject"))
        assert (scores[0].category, scores[0].subcategory) == ("media", "photos_other")

    def test_font_passthrough(self):
        scores = MimeFallbackSignal().run(make_ctx("/tmp/font.ttf"))
        assert (scores[0].category, scores[0].subcategory) == ("fonts", "truetype")

    def test_video_routes_to_videos_other(self):
        scores = MimeFallbackSignal().run(make_ctx("/tmp/movie.mp4", "VideoObject"))
        assert (scores[0].category, scores[0].subcategory) == ("media", "videos_other")

    def test_code_routes_to_technical(self):
        scores = MimeFallbackSignal().run(make_ctx("/tmp/page.html"))
        assert (scores[0].category, scores[0].subcategory) == ("technical", "web")

    def test_documents_stay_unforced(self):
        assert MimeFallbackSignal().run(make_ctx("/tmp/doc.pdf")) == []

    def test_archives_stay_unforced(self):
        assert MimeFallbackSignal().run(make_ctx("/tmp/archive.zip")) == []

    def test_unknown_formats_stay_unforced(self):
        assert MimeFallbackSignal().run(make_ctx("/tmp/mystery.xyz")) == []

    def test_applies_to_everything(self):
        assert MimeFallbackSignal().applies_to(make_ctx("/any/file.bin")) is True

    def test_signal_metadata(self):
        signal = MimeFallbackSignal()
        assert signal.name == "mime_fallback"
        assert signal.weight == W_MIME
        assert signal.cost_tier == "cheap"


class TestTooWeakToCommitAlone:
    def test_mime_only_match_routes_to_low_confidence_fallback(self):
        """Deliberate §4 property: W_MIME (0.3) < MIN_DECISION_CONFIDENCE (0.35),
        so an unopposed mime vote never commits — Phase-3 calibration revisits."""
        decision = Scorer([MimeFallbackSignal()]).classify(make_ctx("/tmp/song.mp3"))
        assert (decision.category, decision.subcategory) == LOW_CONFIDENCE_FALLBACK
        assert decision.decision_state == "low_confidence"
        assert decision.winning_signals == ["mime_fallback"]
