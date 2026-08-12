"""MediaHeuristicSignal tests (UNIFIED_SCORING_PLAN §4 row 12)."""

from pathlib import Path

from src.scoring.signals.media_heuristic import (
    MEDIA_MATCH_CONFIDENCE,
    MediaHeuristicSignal,
    detect_media_category,
    detect_media_match,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_MEDIA


class CountingProvider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return self.result


def make_ctx(path, schema_type="ImageObject", metadata_provider=None):
    return FileContext(
        path=Path(path),
        schema_type=schema_type,
        image_metadata_provider=metadata_provider,
    )


class TestDetectMediaCategory:
    def test_screen_recording_video(self):
        assert detect_media_category(Path("/v/screen_rec.mp4")) == (
            "media",
            "videos",
            "screencasts",
        )

    def test_export_video(self):
        assert detect_media_category(Path("/v/final_cut.mov")) == ("media", "videos", "exports")

    def test_default_video_is_recording(self):
        assert detect_media_category(Path("/v/holiday.mkv")) == ("media", "videos", "recordings")

    def test_podcast_audio(self):
        assert detect_media_category(Path("/a/podcast_ep1.mp3")) == ("media", "audio", "podcasts")

    def test_music_audio(self):
        assert detect_media_category(Path("/a/road_trip_song.m4a")) == ("media", "audio", "music")

    def test_voice_memo_audio(self):
        assert detect_media_category(Path("/a/voice_memo.m4a")) == ("media", "audio", "recordings")

    def test_default_audio_is_recording(self):
        assert detect_media_category(Path("/a/ballad.wma")) == ("media", "audio", "recordings")

    def test_screenshot_named_photo_returns_none(self):
        assert detect_media_category(Path("/p/Screenshot 2026-01-01.png")) is None
        assert detect_media_category(Path("/p/Screen Shot 2026.png")) is None

    def test_receipt_photo_is_document(self):
        assert detect_media_category(Path("/p/receipt_hotel.jpg")) == (
            "media",
            "photos",
            "documents",
        )

    def test_gps_far_from_home_routes_to_travel(self):
        # Paris — beyond TRAVEL_MIN_DISTANCE_KM of home.
        metadata = {"gps_coordinates": (48.85, 2.35)}
        assert detect_media_category(Path("/p/beach.png"), metadata) == (
            "media",
            "photos",
            "travel",
        )

    def test_gps_near_home_abstains(self):
        """Coordinates say where the shutter fired, not that it was a trip.

        Near home this signal returns None rather than falling through to the
        extension branch: that would re-assert the same fact MimeFallbackSignal
        already carries, and two votes stacked on one piece of evidence
        outscore SceneSignal (0.92 vs 0.85 x 0.998) — which is how a lake at
        99.8% confidence lost Media/Place to the generic photo bucket.
        """
        metadata = {"gps_coordinates": (30.27, -97.74)}
        assert detect_media_category(Path("/p/kitchen.jpg"), metadata) is None

    def test_datetime_metadata_routes_to_other(self):
        metadata = {"datetime": "2026-01-01T10:00:00"}
        assert detect_media_category(Path("/p/party.png"), metadata) == (
            "media",
            "photos",
            "other",
        )

    def test_bare_jpg_defaults_to_other(self):
        assert detect_media_category(Path("/p/holiday.jpg")) == ("media", "photos", "other")

    def test_bare_png_falls_through(self):
        assert detect_media_category(Path("/p/diagram.png")) is None

    def test_non_media_returns_none(self):
        assert detect_media_category(Path("/d/notes.pdf")) is None


class TestMatchBasis:
    def test_matched_basis_reported(self):
        assert detect_media_match(Path("/v/screen_rec.mp4")).matched == "stem"
        assert detect_media_match(Path("/v/holiday.mkv")).matched == "extension"
        assert detect_media_match(Path("/a/ballad.wma")).matched == "extension"
        # (1.0, 2.0) is the Gulf of Guinea — far from home, so still "gps".
        gps = detect_media_match(Path("/p/beach.png"), {"gps_coordinates": (1.0, 2.0)})
        assert gps.matched == "gps"
        dated = detect_media_match(Path("/p/party.png"), {"datetime": "2026-01-01"})
        assert dated.matched == "datetime"
        assert detect_media_match(Path("/p/holiday.jpg")).matched == "extension"


class TestSignalRun:
    def test_emits_flattened_subcategory(self):
        scores = MediaHeuristicSignal().run(make_ctx("/v/screen_rec.mp4", "VideoObject"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "videos_screencasts")
        assert score.confidence == MEDIA_MATCH_CONFIDENCE
        assert score.signal_name == "media_heuristic"
        assert score.evidence == {"media_type": "videos", "matched": "stem"}

    def test_gps_far_from_home_routes_to_travel(self):
        provider = CountingProvider({"gps_coordinates": (48.85, 2.35)})
        ctx = make_ctx("/p/beach.jpg", metadata_provider=provider)
        scores = MediaHeuristicSignal().run(ctx)
        assert (scores[0].category, scores[0].subcategory) == ("media", "photos_travel")
        assert scores[0].evidence == {"media_type": "photos", "matched": "gps"}
        assert provider.calls == 1

    def test_gps_near_home_emits_nothing(self):
        """A spice rack on a kitchen wall in Austin is not a trip.

        Abstaining (rather than voting photos_other) keeps this signal from
        stacking with MimeFallbackSignal on the same extension evidence.
        """
        provider = CountingProvider({"gps_coordinates": (30.27, -97.74)})
        ctx = make_ctx("/p/spice_rack.jpg", metadata_provider=provider)
        assert MediaHeuristicSignal().run(ctx) == []
        assert provider.calls == 1

    def test_gps_near_home_abstains_even_with_exif_datetime(self):
        provider = CountingProvider(
            {"gps_coordinates": (30.27, -97.74), "datetime": "2026:07:23 18:19:07"}
        )
        ctx = make_ctx("/p/bedroom.jpg", metadata_provider=provider)
        assert MediaHeuristicSignal().run(ctx) == []

    def test_metadata_not_fetched_for_videos(self):
        provider = CountingProvider({"gps_coordinates": (1.0, 2.0)})
        ctx = make_ctx("/v/screen_rec.mp4", "VideoObject", metadata_provider=provider)
        MediaHeuristicSignal().run(ctx)
        assert provider.calls == 0

    def test_metadata_not_fetched_for_audio(self):
        provider = CountingProvider({"datetime": "2026-01-01"})
        ctx = make_ctx("/a/ballad.wma", "AudioObject", metadata_provider=provider)
        MediaHeuristicSignal().run(ctx)
        assert provider.calls == 0

    def test_screenshot_named_photo_emits_nothing(self):
        assert MediaHeuristicSignal().run(make_ctx("/p/Screenshot 2026-01-01.png")) == []

    def test_ambiguous_png_emits_nothing(self):
        provider = CountingProvider({})
        ctx = make_ctx("/p/diagram.png", metadata_provider=provider)
        assert MediaHeuristicSignal().run(ctx) == []
        # The photo branch was entered, so metadata was consulted once.
        assert provider.calls == 1

    def test_applies_to_everything(self):
        assert MediaHeuristicSignal().applies_to(make_ctx("/any/file.bin")) is True

    def test_signal_metadata(self):
        signal = MediaHeuristicSignal()
        assert signal.name == "media_heuristic"
        assert signal.weight == W_MEDIA
        assert signal.cost_tier == "cheap"
