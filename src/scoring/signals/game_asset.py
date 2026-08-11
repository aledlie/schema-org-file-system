"""GameAssetSignal — game sprite/texture/audio/font heuristics (§4 row 8).

Extracted from ``ContentOrganizer.classify_game_asset`` plus the
``_SPRITE_DISCRIMINATOR_KEYWORDS`` class attribute and the ``__init__``-built
``game_sprite_patterns`` regex list, both of which now live here as module
constants (the organizer keeps aliases so its legacy chain and existing
imports are unchanged). :func:`detect_game_asset_match` reproduces the legacy
method exactly and additionally reports which rule fired;
:func:`detect_game_asset` is the spec-shaped ``(category, subcategory)``
wrapper the organizer delegates to (discarding the match kind).

Behavior divergences from the legacy chain (by design):

- Graduated confidence (§4 row 8): regex-pattern sprite matches, font-keyword
  matches, music/audio keyword matches, and font-extension matches emit
  ``GAME_STRONG_CONFIDENCE`` (0.9); bare sprite/texture keyword matches emit
  ``GAME_KEYWORD_CONFIDENCE`` (0.5) so document OCR outscores
  "bloodwork"-style keyword collisions — this subsumes the legacy
  ``_ocr_document_override`` call-site special case, which stays intact in
  the legacy chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

import re
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from shared.constants import (
    CAMERA_VENDOR_PREFIX_PATTERNS,
    GAME_AUDIO_KEYWORDS,
    GAME_FONT_KEYWORDS,
    GAME_MUSIC_KEYWORDS,
    GAME_SPRITE_KEYWORDS,
)

from ..types import CategoryScore
from ..weights import W_GAME

# High-precision rules (numbered-sprite regexes, font sheets, music/audio
# keywords, font extensions) vs. bare sprite/texture keyword hits, which
# collide with real words ("blood" in "bloodwork") and must stay beatable.
GAME_STRONG_CONFIDENCE = 0.9
GAME_KEYWORD_CONFIDENCE = 0.5

GAME_ASSETS_CATEGORY = "game_assets"
FONTS_CATEGORY = "fonts"

MUSIC_SUBCATEGORY = "music"
AUDIO_SUBCATEGORY = "audio"
FONTS_SUBCATEGORY = "fonts"
SPRITES_SUBCATEGORY = "sprites"
TEXTURES_SUBCATEGORY = "textures"

# Which rule fired (evidence + confidence grading).
MATCH_KIND_MUSIC_KEYWORD = "music_keyword"
MATCH_KIND_AUDIO_KEYWORD = "audio_keyword"
MATCH_KIND_FONT_KEYWORD = "font_keyword"
MATCH_KIND_SPRITE_PATTERN = "sprite_pattern"
MATCH_KIND_SPRITE_KEYWORD = "sprite_keyword"
MATCH_KIND_TEXTURE_KEYWORD = "texture_keyword"
MATCH_KIND_FONT_EXTENSION = "font_extension"

STRONG_MATCH_KINDS = frozenset(
    {
        MATCH_KIND_MUSIC_KEYWORD,
        MATCH_KIND_AUDIO_KEYWORD,
        MATCH_KIND_FONT_KEYWORD,
        MATCH_KIND_SPRITE_PATTERN,
        MATCH_KIND_FONT_EXTENSION,
    }
)

# Extension gates (verbatim from the legacy method).
GAME_AUDIO_EXTENSIONS = (".wav", ".ogg", ".mp3", ".flac", ".aac")
GAME_MUSIC_EXTENSION = ".ogg"
GAME_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".dds")

# Font files route to the CreativeWork fonts taxonomy by extension.
FONT_EXTENSION_SUBCATEGORIES: Dict[str, str] = {
    ".ttf": "truetype",
    ".otf": "opentype",
    ".woff": "web",
    ".woff2": "web",
    ".eot": "web",
    ".fon": "other",
    ".fnt": "other",
}

# Files with 'screenshot' in the stem are screen captures, never game art.
SCREENSHOT_STEM_MARKER = "screenshot"

# Timestamp suffixes (e.g. _20251120_164506) are stripped before pattern
# matching so renamed copies still match.
_TIMESTAMP_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")

# Scanner stems (flatbed / document scanners) are photos/scans, not game art.
_SCAN_STEM_PREFIX_RE = r"^scan_?\d+"

# Camera-roll and scanner stems share the same exclusion logic as
# FilenamePatternSignal (see filename_pattern._CAMERA_OR_SCAN_STEM_PATTERNS);
# kept in sync so both signals agree on which stems to exclude from sprite
# pattern matching (which emits GAME_STRONG_CONFIDENCE that content signals
# cannot reliably outscore on low-content images).
_CAMERA_OR_SCAN_STEM_PATTERNS: Tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (*CAMERA_VENDOR_PREFIX_PATTERNS, _SCAN_STEM_PREFIX_RE)
)


def _is_camera_or_scan_stem(stem: str) -> bool:
    """True when *stem* (already case-folded) is a camera-roll or scanner name."""
    return any(p.match(stem) for p in _CAMERA_OR_SCAN_STEM_PATTERNS)


# Subset of game_sprite_keywords that implies sprite (vs texture)
# classification. Moved verbatim from the ContentOrganizer class attribute
# (which now aliases this constant).
SPRITE_DISCRIMINATOR_KEYWORDS = frozenset(
    {
        "frame",
        "sprite",
        "leg",
        "arm",
        "head",
        "torso",
        "body",
        "wing",
        "hair",
        "face",
        "mouth",
        "_grey",
        "_gray",
        "assassins",
        "atonement",
        "arrow_v",
        "arrow_h",
        "add",
        "2h_",
        "1h_",
        "dagger",
        "sword",
        "axe",
        "hammer",
        "mace",
        "beard",
        "bling",
        "hiero",
        "mustache",
        "scar",
        "tattoo",
        "earring",
        "necklace",
        "bracelet",
        "glasses",
        "mask",
        "hood",
    }
)

# Regex patterns for game asset detection (numbered sprites, variants).
# Moved verbatim from ContentOrganizer.__init__ (which now copies this tuple
# into its per-instance ``game_sprite_patterns`` list).
GAME_SPRITE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d+_\d+$"),  # 42_8, 51_3, 16_3 (sprite sheets)
    re.compile(r"^\d+_grey(_\d+)?$", re.IGNORECASE),  # 10_grey, 10_grey_1
    re.compile(r"^\d+_f(_\d+)?$", re.IGNORECASE),  # 283_f, 283_f_1
    re.compile(r"^[a-z]+_\d+$", re.IGNORECASE),  # frame_1, item_42
    re.compile(r"^[a-z]+_[a-z]+_\d+$", re.IGNORECASE),  # assassins_deed_1
    re.compile(r"^\d+h_[a-z]+(_\d+)?$", re.IGNORECASE),  # 2h_axe, 2h_axe_1
    re.compile(r"^[a-z]+_v(_\d+)?$", re.IGNORECASE),  # arrow_v, arrow_v_1
    re.compile(r"^[a-z]+_h(_\d+)?$", re.IGNORECASE),  # arrow_h, arrow_h_1
    re.compile(r"^(head|torso|arm|leg|body|wing|hair)_\w+", re.IGNORECASE),  # body parts
    re.compile(r"^(weapon|armor|item|sprite|frame|tile)\d*_", re.IGNORECASE),  # game prefixes
)


class GameAssetMatch(NamedTuple):
    """A game-asset detection plus which rule produced it."""

    category: str
    subcategory: str
    match_kind: str
    matched: str  # the keyword, regex pattern, or extension that fired


def detect_game_asset_match(
    path: Path,
    *,
    music_keywords: Iterable[str],
    audio_keywords: Iterable[str],
    font_keywords: Iterable[str],
    sprite_patterns: Iterable[re.Pattern[str]],
    sprite_keywords: Iterable[str],
    sprite_discriminators: Iterable[str],
) -> Optional[GameAssetMatch]:
    """Classify a file as a game asset, reporting which rule fired.

    Reproduces ``ContentOrganizer.classify_game_asset`` exactly (rule order,
    stem vs. timestamp-cleaned-stem checks, screenshot exclusion) and tags the
    result with a match kind; the legacy delegator discards the tag.
    """
    stem = path.stem.lower()
    ext = path.suffix.lower()

    # Remove timestamp suffixes for pattern matching (e.g., _20251120_164506)
    clean_stem = _TIMESTAMP_SUFFIX_RE.sub("", stem)

    # Audio files: game music (usually .ogg) first, then sound effects.
    if ext in GAME_AUDIO_EXTENSIONS:
        if ext == GAME_MUSIC_EXTENSION:
            for keyword in music_keywords:
                if keyword in stem:
                    return GameAssetMatch(
                        GAME_ASSETS_CATEGORY,
                        MUSIC_SUBCATEGORY,
                        MATCH_KIND_MUSIC_KEYWORD,
                        keyword,
                    )
        for keyword in audio_keywords:
            if keyword in stem:
                return GameAssetMatch(
                    GAME_ASSETS_CATEGORY,
                    AUDIO_SUBCATEGORY,
                    MATCH_KIND_AUDIO_KEYWORD,
                    keyword,
                )

    # Image files that are game sprites/textures; files with 'screenshot' in
    # the name are screen captures, not assets.
    if ext in GAME_IMAGE_EXTENSIONS and SCREENSHOT_STEM_MARKER not in stem:
        # Game font sprite sheets first.
        for keyword in font_keywords:
            if keyword in stem or keyword in clean_stem:
                return GameAssetMatch(
                    GAME_ASSETS_CATEGORY,
                    FONTS_SUBCATEGORY,
                    MATCH_KIND_FONT_KEYWORD,
                    keyword,
                )

        # Regex patterns for numbered sprites and variants.
        # Camera-roll and scanner stems (img_1234, scan_0023) are photos/scans,
        # not game art. The patterns emit GAME_STRONG_CONFIDENCE (0.9) — too high
        # for content signals to beat on low-content images — so skip the loop
        # entirely for these stems. Sprite/texture keyword matches remain
        # eligible because they emit the lower GAME_KEYWORD_CONFIDENCE (0.5).
        # Parity with FilenamePatternSignal which downgrades the sprite result
        # for the same stem prefixes via graduated_filename_confidence.
        if not _is_camera_or_scan_stem(stem):
            for pattern in sprite_patterns:
                if pattern.match(clean_stem):
                    return GameAssetMatch(
                        GAME_ASSETS_CATEGORY,
                        SPRITES_SUBCATEGORY,
                        MATCH_KIND_SPRITE_PATTERN,
                        pattern.pattern,
                    )

        # Sprite/texture keyword patterns; the discriminator subset
        # distinguishes sprites from textures.
        for keyword in sprite_keywords:
            if keyword in stem or keyword in clean_stem:
                if any(kw in stem or kw in clean_stem for kw in sprite_discriminators):
                    return GameAssetMatch(
                        GAME_ASSETS_CATEGORY,
                        SPRITES_SUBCATEGORY,
                        MATCH_KIND_SPRITE_KEYWORD,
                        keyword,
                    )
                return GameAssetMatch(
                    GAME_ASSETS_CATEGORY,
                    TEXTURES_SUBCATEGORY,
                    MATCH_KIND_TEXTURE_KEYWORD,
                    keyword,
                )

    # Font files by extension.
    font_subcategory = FONT_EXTENSION_SUBCATEGORIES.get(ext)
    if font_subcategory is not None:
        return GameAssetMatch(FONTS_CATEGORY, font_subcategory, MATCH_KIND_FONT_EXTENSION, ext)

    return None


def detect_game_asset(
    path: Path,
    *,
    music_keywords: Iterable[str],
    audio_keywords: Iterable[str],
    font_keywords: Iterable[str],
    sprite_patterns: Iterable[re.Pattern[str]],
    sprite_keywords: Iterable[str],
    sprite_discriminators: Iterable[str],
) -> Optional[Tuple[str, str]]:
    """Legacy-shaped wrapper: ``(category, subcategory)`` or ``None``."""
    match = detect_game_asset_match(
        path,
        music_keywords=music_keywords,
        audio_keywords=audio_keywords,
        font_keywords=font_keywords,
        sprite_patterns=sprite_patterns,
        sprite_keywords=sprite_keywords,
        sprite_discriminators=sprite_discriminators,
    )
    if match is None:
        return None
    return (match.category, match.subcategory)


# Signal-local evidence keys.
EVIDENCE_MATCH_KIND = "match_kind"
EVIDENCE_MATCHED_KEYWORD = "matched_keyword"
EVIDENCE_PATTERN = "pattern"


class GameAssetSignal:
    """Filename-heuristic game-asset detection with graduated confidence."""

    name = "game_asset"
    weight = W_GAME
    cost_tier = "cheap"

    def __init__(
        self,
        *,
        music_keywords: Optional[Iterable[str]] = None,
        audio_keywords: Optional[Iterable[str]] = None,
        font_keywords: Optional[Iterable[str]] = None,
        sprite_patterns: Optional[Iterable[re.Pattern[str]]] = None,
        sprite_keywords: Optional[Iterable[str]] = None,
        sprite_discriminators: Optional[Iterable[str]] = None,
    ) -> None:
        self._music_keywords = list(
            GAME_MUSIC_KEYWORDS if music_keywords is None else music_keywords
        )
        self._audio_keywords = list(
            GAME_AUDIO_KEYWORDS if audio_keywords is None else audio_keywords
        )
        self._font_keywords = list(GAME_FONT_KEYWORDS if font_keywords is None else font_keywords)
        self._sprite_patterns = list(
            GAME_SPRITE_PATTERNS if sprite_patterns is None else sprite_patterns
        )
        self._sprite_keywords = list(
            GAME_SPRITE_KEYWORDS if sprite_keywords is None else sprite_keywords
        )
        self._sprite_discriminators = frozenset(
            SPRITE_DISCRIMINATOR_KEYWORDS
            if sprite_discriminators is None
            else sprite_discriminators
        )

    def applies_to(self, ctx: FileContext) -> bool:
        return True

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        match = detect_game_asset_match(
            ctx.path,
            music_keywords=self._music_keywords,
            audio_keywords=self._audio_keywords,
            font_keywords=self._font_keywords,
            sprite_patterns=self._sprite_patterns,
            sprite_keywords=self._sprite_keywords,
            sprite_discriminators=self._sprite_discriminators,
        )
        if match is None:
            return []
        confidence = (
            GAME_STRONG_CONFIDENCE
            if match.match_kind in STRONG_MATCH_KINDS
            else GAME_KEYWORD_CONFIDENCE
        )
        matched_key = (
            EVIDENCE_PATTERN
            if match.match_kind == MATCH_KIND_SPRITE_PATTERN
            else EVIDENCE_MATCHED_KEYWORD
        )
        return [
            CategoryScore(
                category=match.category,
                subcategory=match.subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence={
                    EVIDENCE_MATCH_KIND: match.match_kind,
                    matched_key: match.matched,
                },
            )
        ]
