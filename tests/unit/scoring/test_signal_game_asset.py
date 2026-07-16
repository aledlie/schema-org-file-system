"""GameAssetSignal tests (UNIFIED_SCORING_PLAN §4 row 8)."""

import re
from pathlib import Path

from shared.constants import (
    GAME_AUDIO_KEYWORDS,
    GAME_FONT_KEYWORDS,
    GAME_MUSIC_KEYWORDS,
    GAME_SPRITE_KEYWORDS,
)

from src.scoring.signals.game_asset import (
    GAME_KEYWORD_CONFIDENCE,
    GAME_SPRITE_PATTERNS,
    GAME_STRONG_CONFIDENCE,
    SPRITE_DISCRIMINATOR_KEYWORDS,
    GameAssetSignal,
    detect_game_asset,
    detect_game_asset_match,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_GAME

DEFAULT_KWARGS = dict(
    music_keywords=GAME_MUSIC_KEYWORDS,
    audio_keywords=GAME_AUDIO_KEYWORDS,
    font_keywords=GAME_FONT_KEYWORDS,
    sprite_patterns=GAME_SPRITE_PATTERNS,
    sprite_keywords=GAME_SPRITE_KEYWORDS,
    sprite_discriminators=SPRITE_DISCRIMINATOR_KEYWORDS,
)


def detect(path):
    return detect_game_asset(Path(path), **DEFAULT_KWARGS)


def detect_match(path):
    return detect_game_asset_match(Path(path), **DEFAULT_KWARGS)


def make_ctx(path, schema_type="ImageObject"):
    return FileContext(path=Path(path), schema_type=schema_type)


class TestDetectGameAsset:
    def test_ogg_music_keyword(self):
        assert detect("/sounds/dungeon.ogg") == ("game_assets", "music")

    def test_wav_audio_keyword(self):
        assert detect("/sounds/sword_attack.wav") == ("game_assets", "audio")

    def test_font_keyword_sheet(self):
        assert detect("/assets/broguefont_sheet.png") == ("game_assets", "fonts")

    def test_numbered_sprite_pattern(self):
        assert detect("/sprites/frame_1.png") == ("game_assets", "sprites")

    def test_timestamp_suffix_stripped_before_matching(self):
        assert detect("/sprites/frame_1_20251120_164506.png") == ("game_assets", "sprites")

    def test_keyword_with_discriminator_is_sprite(self):
        assert detect("/sprites/hero_sword.png") == ("game_assets", "sprites")

    def test_keyword_without_discriminator_is_texture(self):
        assert detect("/assets/wood_texture.png") == ("game_assets", "textures")

    def test_screenshot_stem_excluded(self):
        assert detect("/shots/sprite_screenshot.png") is None

    def test_font_extensions(self):
        assert detect("/fonts/font.ttf") == ("fonts", "truetype")
        assert detect("/fonts/font.otf") == ("fonts", "opentype")
        assert detect("/fonts/font.woff2") == ("fonts", "web")
        assert detect("/fonts/font.fnt") == ("fonts", "other")

    def test_non_game_file_returns_none(self):
        assert detect("/photos/vacation.jpg") is None
        assert detect("/music/meeting.mp3") is None


class TestMatchKinds:
    def test_match_kinds_reported(self):
        assert detect_match("/sounds/dungeon.ogg").match_kind == "music_keyword"
        assert detect_match("/sounds/sword_attack.wav").match_kind == "audio_keyword"
        assert detect_match("/assets/broguefont_sheet.png").match_kind == "font_keyword"
        assert detect_match("/sprites/frame_1.png").match_kind == "sprite_pattern"
        assert detect_match("/sprites/hero_sword.png").match_kind == "sprite_keyword"
        assert detect_match("/assets/wood_texture.png").match_kind == "texture_keyword"
        assert detect_match("/fonts/font.ttf").match_kind == "font_extension"

    def test_matched_token_reported(self):
        assert detect_match("/sounds/dungeon.ogg").matched == "dungeon"
        assert detect_match("/fonts/font.ttf").matched == ".ttf"


class TestSignalRun:
    def test_strong_confidence_for_sprite_pattern(self):
        scores = GameAssetSignal().run(make_ctx("/sprites/frame_1.png"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("game_assets", "sprites")
        assert score.confidence == GAME_STRONG_CONFIDENCE
        assert score.signal_name == "game_asset"
        assert score.evidence["match_kind"] == "sprite_pattern"
        assert score.evidence["pattern"] == r"^[a-z]+_\d+$"

    def test_strong_confidence_for_music_audio_font(self):
        for path in (
            "/sounds/dungeon.ogg",
            "/sounds/sword_attack.wav",
            "/assets/broguefont_sheet.png",
            "/fonts/font.ttf",
        ):
            scores = GameAssetSignal().run(make_ctx(path))
            assert scores[0].confidence == GAME_STRONG_CONFIDENCE, path

    def test_keyword_confidence_for_bare_keyword_matches(self):
        # "bloodwork"-style collisions must stay beatable by document OCR.
        texture = GameAssetSignal().run(make_ctx("/scans/medellin_bloodwork.png"))
        assert len(texture) == 1
        assert texture[0].confidence == GAME_KEYWORD_CONFIDENCE
        assert texture[0].evidence["match_kind"] == "texture_keyword"
        assert texture[0].evidence["matched_keyword"] == "blood"

        sprite = GameAssetSignal().run(make_ctx("/sprites/hero_sword.png"))
        assert sprite[0].confidence == GAME_KEYWORD_CONFIDENCE
        assert sprite[0].evidence["match_kind"] == "sprite_keyword"

    def test_non_match_emits_nothing(self):
        assert GameAssetSignal().run(make_ctx("/photos/vacation.jpg")) == []

    def test_applies_to_everything(self):
        assert GameAssetSignal().applies_to(make_ctx("/any/file.bin")) is True


class TestConstructorOverrides:
    def test_custom_keyword_lists(self):
        signal = GameAssetSignal(
            music_keywords=["zeldatheme"],
            audio_keywords=[],
            font_keywords=[],
            sprite_patterns=[],
            sprite_keywords=[],
            sprite_discriminators=[],
        )
        scores = signal.run(make_ctx("/music/zeldatheme_loop.ogg"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("game_assets", "music")
        # Default vocabulary no longer applies under the overrides.
        assert signal.run(make_ctx("/sprites/frame_1.png")) == []

    def test_custom_sprite_pattern(self):
        signal = GameAssetSignal(
            font_keywords=[],
            sprite_patterns=[re.compile(r"^custom_\d+$")],
            sprite_keywords=[],
        )
        scores = signal.run(make_ctx("/sprites/custom_7.png"))
        assert scores[0].evidence["match_kind"] == "sprite_pattern"

    def test_signal_metadata(self):
        signal = GameAssetSignal()
        assert signal.name == "game_asset"
        assert signal.weight == W_GAME
        assert signal.cost_tier == "cheap"
