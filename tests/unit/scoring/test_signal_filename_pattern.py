"""FilenamePatternSignal tests (UNIFIED_SCORING_PLAN §4 row 2)."""

from pathlib import Path

from shared.constants import GAME_SPRITE_KEYWORDS

from src.scoring.signals.filename_pattern import (
    FILENAME_MATCH_CONFIDENCE,
    FILENAME_WEAK_CONFIDENCE,
    FilenamePatternSignal,
    graduated_filename_confidence,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_FILENAME


def make_ctx(path, display_path=None, schema_type="DigitalDocument"):
    return FileContext(
        path=Path(path),
        schema_type=schema_type,
        display_path=Path(display_path) if display_path else None,
    )


def make_signal(keywords=None):
    return FilenamePatternSignal(GAME_SPRITE_KEYWORDS if keywords is None else keywords)


class TestAppliesTo:
    def test_always_applies(self):
        assert make_signal().applies_to(make_ctx("/tmp/anything.bin")) is True


class TestRun:
    def test_no_pattern_emits_nothing(self):
        ctx = make_ctx("/random/xyzxyz_unique_file.pdf")
        assert make_signal().run(ctx) == []

    def test_log_file_routes_to_technical(self):
        scores = make_signal().run(make_ctx("/logs/error.log"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("technical", "logs")
        assert score.confidence == FILENAME_MATCH_CONFIDENCE
        assert score.signal_name == "filename_pattern"
        assert "company_name" not in score.evidence
        assert "people_names" not in score.evidence

    def test_weak_photos_other_result_emits_graduated_confidence(self):
        """The 'Named image'/'Hash/ID image' catch-alls are enhancement
        triggers in the legacy chain (Point A), not answers — they must not
        early-exit the cheap wave ahead of OCR/CLIP evidence."""
        scores = make_signal().run(make_ctx("/photos/medellin_bloodwork.png"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "photos_other")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE
        assert FILENAME_WEAK_CONFIDENCE < FILENAME_MATCH_CONFIDENCE

    def test_duplicate_passes_through_as_skip_score(self):
        scores = make_signal().run(make_ctx("/photos/photo_20250101_123456.png"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("skip", "duplicate")

    def test_people_names_land_in_evidence(self):
        scores = make_signal().run(make_ctx("/docs/Alyshia_Ledlie_Resume.pdf"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.evidence["people_names"]

    def test_display_path_preferred_over_physical(self):
        ctx = make_ctx("/tmp/blob.bin", display_path="/tmp/error.log")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("technical", "logs")


class TestResearchEvidence:
    def test_research_pdf_carries_schema_type_and_provenance(self):
        scores = make_signal().run(make_ctx("/papers/arxiv-2401.12345.pdf"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("research", "arxiv")
        assert score.evidence["schema_type"] == "ScholarlyArticle"
        assert score.evidence["company_name"] == "arXiv"
        assert score.evidence["research"] == (
            "arxiv",
            "2401.12345",
            "arXiv",
            "https://arxiv.org/abs/2401.12345",
        )

    def test_non_research_has_no_schema_type_override(self):
        scores = make_signal().run(make_ctx("/docs/nda_2024.pdf"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("legal", "contracts")
        assert "schema_type" not in scores[0].evidence
        assert "research" not in scores[0].evidence


class TestGameSpriteKeywordGating:
    def test_keyword_enables_named_game_asset_rule(self):
        signal = FilenamePatternSignal(["salamander"])
        scores = signal.run(make_ctx("/tmp/salamander_walk.png"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("game_assets", "sprites")

    def test_without_keyword_named_rule_does_not_fire(self):
        signal = FilenamePatternSignal([])
        scores = signal.run(make_ctx("/tmp/salamander_walk.png"))
        assert not any(
            (score.category, score.subcategory) == ("game_assets", "sprites") for score in scores
        )


class TestGraduatedConfidence:
    """Downgrade helper for the legacy filename naming traps (item #5)."""

    def test_photos_other_catch_all_stays_weak(self):
        assert (
            graduated_filename_confidence("some_photo", "media", "photos_other", ".png")
            == FILENAME_WEAK_CONFIDENCE
        )

    def test_camera_prefix_sprite_downgrades(self):
        for stem in ("img_2043", "pxl_20250425", "dsc_1234", "dsc1234", "dcim_0001"):
            assert (
                graduated_filename_confidence(stem, "game_assets", "sprites", ".jpg")
                == FILENAME_WEAK_CONFIDENCE
            ), stem

    def test_scanner_prefix_sprite_downgrades(self):
        for stem in ("scan_0023", "scan0001"):
            assert (
                graduated_filename_confidence(stem, "game_assets", "sprites", ".png")
                == FILENAME_WEAK_CONFIDENCE
            ), stem

    def test_genuine_numbered_sprite_stays_strong(self):
        # frame_1 is a real sprite (non-camera, non-scanner) — precision guard.
        for stem in ("frame_1", "item_42", "2h_axe_3", "10_grey"):
            assert (
                graduated_filename_confidence(stem, "game_assets", "sprites", ".png")
                == FILENAME_MATCH_CONFIDENCE
            ), stem

    def test_weak_shape_sprite_naming_traps_downgrade(self):
        # Bare word / word+number / two-letter / hyphenated stems attest
        # nothing game-related — measured on 13 misfiled social photos
        # (scoring-calibration-20260726 §3.2). Content signals must be able
        # to outscore the sprite verdict.
        for stem in (
            "joke",
            "silly",
            "apartment",
            "brothers",
            "aw",
            "love10",
            "love2",
            "ganesh5",
            "blue-ai-digital-cube",
        ):
            assert (
                graduated_filename_confidence(stem, "game_assets", "sprites", ".jpg")
                == FILENAME_WEAK_CONFIDENCE
            ), stem

    def test_attested_sprite_stems_stay_strong(self):
        # Curated game vocabulary + number ("Game asset (dungeon)") and hex
        # unicode/emoji sheet stems are real attestations — never downgraded.
        for stem in ("dungeon2", "kitchen4", "npc7", "1f60a", "face12"):
            assert (
                graduated_filename_confidence(stem, "game_assets", "sprites", ".png")
                == FILENAME_MATCH_CONFIDENCE
            ), stem

    def test_bare_audio_extension_downgrades(self):
        # Generic "Audio file" rule → weak so MediaHeuristic can refine.
        for ext in (".mp3", ".m4a", ".aac", ".flac", ".wma"):
            assert (
                graduated_filename_confidence("some_clip", "media", "audio_other", ext)
                == FILENAME_WEAK_CONFIDENCE
            ), ext

    def test_non_refinable_audio_extension_stays_strong(self):
        # .wav/.ogg are not in MediaHeuristic's refinable set (game-asset
        # detection owns them), so there is no refiner to defer to.
        for ext in (".wav", ".ogg"):
            assert (
                graduated_filename_confidence("some_clip", "media", "audio_other", ext)
                == FILENAME_MATCH_CONFIDENCE
            ), ext

    def test_strong_result_stays_strong(self):
        assert (
            graduated_filename_confidence("error", "technical", "logs", ".log")
            == FILENAME_MATCH_CONFIDENCE
        )

    def test_source_provenance_results_downgrade(self):
        # ChatGPT / Facebook stems record source, not content — content signals
        # must be able to outscore them (content-agnostic-filename fix).
        for cat, sub, stem in (
            ("media", "photos_chatgpt", "chatgptimagenov1,2025,01_49_23am"),
            ("media", "photos_facebook", "481566579_10162021550590804_5823185318886800843_n"),
        ):
            assert (
                graduated_filename_confidence(stem, cat, sub, ".png") == FILENAME_WEAK_CONFIDENCE
            ), sub


class TestPersonNameImageGraduation:
    """Person-name stems on images get weak confidence (contacts vs photos fix)."""

    def test_person_name_image_emits_weak_confidence(self):
        # An image named after a known person should let content signals decide
        # the bucket — it is a photo of the person, not a contact record.
        ctx = make_ctx("/photos/Alyshia_Ledlie.jpg", schema_type="ImageObject")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE

    def test_person_name_document_keeps_full_confidence(self):
        # A PDF resume named after a person correctly files to contacts at
        # full strength — the graduation applies to images only.
        ctx = make_ctx("/docs/Alyshia_Ledlie_Resume.pdf")  # default: DigitalDocument
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.confidence == FILENAME_MATCH_CONFIDENCE


class TestStockAssetStemPromotion:
    """stock-vector-* and pngtree-* stems route to graphics_other, not sprites."""

    def test_stock_vector_stem_routes_to_graphics_other(self):
        ctx = make_ctx("/tmp/stock-vector-modeling-blue-red.jpeg")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "graphics_other")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE

    def test_pngtree_stem_routes_to_graphics_other(self):
        ctx = make_ctx("/tmp/pngtree-colorful-poster.png")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "graphics_other")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE

    def test_non_stock_hyphenated_sprite_keeps_sprites(self):
        # A genuinely hyphenated non-stock stem stays as a (weak) sprite.
        ctx = make_ctx("/tmp/blue-ai-digital-cube.png")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        assert scores[0].category != "media"  # still sprite (or weak), not graphics


class TestCameraScanSpriteDowngradeThroughSignal:
    def test_scan_prefixed_sprite_emits_weak_confidence(self):
        # Construct a scanner stem that the shared rule answers as a sprite by
        # feeding the scanner token as a game-sprite keyword; the signal must
        # still downgrade it (scanner prefix wins over the raw verdict).
        signal = FilenamePatternSignal(["scan"])
        scores = signal.run(make_ctx("/inbox/scan_0023_scan.png"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("game_assets", "sprites")
        assert scores[0].confidence == FILENAME_WEAK_CONFIDENCE


class TestEventMapStems:
    def test_placement_map_routes_to_events_at_weak_confidence(self):
        # Event/venue maps vote events but must not early-exit the cheap wave:
        # the Events/{EventName}/ folder name comes from EventContentSignal in
        # the mid wave (see EVENTS_MAP_RESULT in filename_pattern.py).
        scores = make_signal().run(make_ctx("/downloads/3'x5'_PlacementMap_Draft (1).pdf"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("events", "other")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE

    def test_event_map_stem_variants_route_to_events(self):
        for path in (
            "/maps/venue map.pdf",
            "/maps/FestivalMap.png",
            "/maps/event_map.svg",
        ):
            scores = make_signal().run(make_ctx(path))
            assert len(scores) == 1, path
            assert (scores[0].category, scores[0].subcategory) == ("events", "other"), path

    def test_placement_without_map_does_not_fire_events(self):
        scores = make_signal().run(make_ctx("/docs/placement_strategy.pdf"))
        assert all((s.category, s.subcategory) != ("events", "other") for s in scores)


class TestArchiveGraduation:
    def test_archive_verdict_emits_weak_confidence(self):
        # Extension-only evidence: the mid-wave manifest signal decides what
        # the archive holds (see ARCHIVE_RESULT in filename_pattern.py).
        scores = make_signal().run(make_ctx("/downloads/Photos.zip"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("technical", "archives")
        assert score.confidence == FILENAME_WEAK_CONFIDENCE


class TestSignalMetadata:
    def test_signal_metadata(self):
        signal = make_signal()
        assert signal.name == "filename_pattern"
        assert signal.weight == W_FILENAME
        assert signal.cost_tier == "cheap"
