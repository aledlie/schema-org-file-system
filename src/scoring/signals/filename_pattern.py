"""FilenamePatternSignal — shared filename-rule classification (§4 row 2).

Wraps ``shared.filename_classifier.classify_by_filename_patterns`` — the
single-homed ~40-group rule module — as ONE signal (plan v2 decision, Open
Question #5 tracks later per-domain decomposition). The rule module itself is
neither copied nor modified; ``ContentOrganizer.classify_by_filename_patterns``
already delegates to it, so no organizer edit accompanies this signal.

Behavior divergences from the legacy chain (by design):

- Research-publisher provenance moves from the ``last_file_state`` side
  channel into ``evidence["research"]`` (§4 row 2); the legacy chain's
  ``schema_type = SCHOLARLY_ARTICLE_SCHEMA_TYPE`` mutation becomes an
  ``evidence["schema_type"]`` override that the scorer applies only when this
  signal contributes to the winning candidate.
- ``skip``/``duplicate`` results pass through as a normal
  :class:`~src.scoring.types.CategoryScore` instead of short-circuiting the
  chain; the decision assembler sees them compete like any candidate.
- Weak generic rules emit graduated confidence: a ``media/photos_other``
  result is the rule module's "Named image" catch-all — the exact case the
  legacy chain routes through ``enhance_weak_image_classification`` (Point A)
  rather than trusting. At full confidence it would early-exit the cheap wave
  (W_FILENAME × 1.0 > EARLY_EXIT_CONFIDENCE) and OCR/CLIP evidence would
  never run; at ``FILENAME_WEAK_CONFIDENCE`` content signals outscore it,
  which is the §4 format-drift fix in action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

import re
from typing import Dict, List

from shared.constants import CAMERA_VENDOR_PREFIX_PATTERNS
from shared.filename_classifier import (
    GAME_ASSET_STEM_KEYWORDS,
    RESEARCH_CATEGORY,
    SCHOLARLY_ARTICLE_SCHEMA_TYPE,
    classify_by_filename_patterns,
)

from ..types import (
    EVIDENCE_COMPANY,
    EVIDENCE_PEOPLE,
    EVIDENCE_SCHEMA_TYPE,
    CategoryScore,
)
from ..weights import W_FILENAME
from .media_heuristic import AUDIO_EXTENSIONS as REFINABLE_AUDIO_EXTENSIONS

# Filename rules are exact-match heuristics; a hit is signal-locally certain
# (the W_FILENAME prior expresses how much the scorer trusts the rule set).
FILENAME_MATCH_CONFIDENCE = 1.0

# Weak catch-all results (see module docstring): the legacy chain treats these
# as enhancement triggers, not answers, so the signal mirrors that with a
# confidence low enough for heavy content signals to outscore.
FILENAME_WEAK_CONFIDENCE = 0.4
FILENAME_WEAK_RESULTS = frozenset({("media", "photos_other")})

# Event/venue-map stems route to events, but the Events/{EventName}/ folder
# name comes from EventContentSignal (mid wave). At full confidence this
# cheap-wave verdict would early-exit (W_FILENAME × 1.0 > EARLY_EXIT_CONFIDENCE)
# before the event name is ever extracted; graduated, it corroborates the
# content signal (0.44 + 0.95 aggregate) and still commits alone (0.44 ≥
# MIN_DECISION_CONFIDENCE) when the map yields no extractable title.
EVENTS_MAP_RESULT = ("events", "other")

# Archives: the extension says "it's an archive", never what it holds — the
# member listing does (ArchiveManifestSignal, mid wave). Same downgrade
# rationale as EVENTS_MAP_RESULT: full confidence would early-exit before the
# manifest is read; graduated, a media/medical manifest outscores this verdict
# and a silent manifest leaves it to commit Technical/Other alone.
ARCHIVE_RESULT = ("technical", "archives")

# Legacy filename naming traps (BACKLOG Phase-3 item #5): the shared rule
# module answers these at full strength, but the stem is not what the verdict
# claims, so the signal graduates their confidence down to let the
# content/media signals outscore.
GAME_SPRITES_RESULT = ("game_assets", "sprites")
MEDIA_AUDIO_OTHER_RESULT = ("media", "audio_other")

# Source/host provenance, not content: a ``ChatGPTImage*`` or Facebook-export
# stem records where the file came from (which tool generated it, which site
# hosted it), never what it depicts. At full strength the source filename
# preempts content classification — an interior render named ``ChatGPTImage*``
# commits to photos_chatgpt before CLIP / interior signals are weighed. Graduate
# these down so content signals decide the bucket; the source category still
# wins as a fallback when no content signal fires. (Content-agnostic-filename
# fix; pairs with a content interior signal — see docs/reviews/
# INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md.)
SOURCE_PROVENANCE_RESULTS = frozenset({("media", "photos_chatgpt"), ("media", "photos_facebook")})

# Person-name filename rules (e.g. "sumedh_alyshia.jpg") route images to
# personal/contacts at full strength — but contact records are vCards/resumes,
# not photos of people. The rule is correct for document-typed files
# (``Alyshia_Ledlie_Resume.pdf`` → personal/contacts is right); for images the
# stem says who is depicted, not what format the file is. Graduate so that
# PhotoCompositionSignal/MediaHeuristicSignal/CLIP can decide the real bucket.
# Only applies when the file schema_type is ImageObject; all other types keep
# full confidence. Handled in ``run()`` (needs the FileContext, not just the
# stem) rather than in ``graduated_filename_confidence``.
CONTACTS_RESULT = ("personal", "contacts")

# Stock-asset stems explicitly assert the graphic format ("stock-vector-*",
# "pngtree-*"). The shared rule module lands these on photos_other (already
# weak via FILENAME_WEAK_RESULTS), but the stem says the file is a vector
# illustration or graphic template — media/graphics_other is the right bucket.
# Promote the subcategory while keeping weak confidence so CLIP /
# GraphicDetectionSignal can confirm or override.
_STOCK_ASSET_STEM_PREFIXES = ("stock-vector-", "pngtree-", "stock_vector_", "pngtree_")


def _is_stock_asset_stem(stem: str) -> bool:
    """True when ``stem`` (already case-folded) is a stock-asset naming pattern
    that implies a vector illustration or graphic template."""
    return any(stem.startswith(prefix) for prefix in _STOCK_ASSET_STEM_PREFIXES)


# Camera-roll / scanner stems are photos and scans, never game sprites. The
# shared module already guards its numbered-sprite paths against the camera
# vendor prefixes, but not against scanner output (``scan_0023``), and offers
# no defense if a future rule fires ``sprites`` on a camera stem. Reuse the
# single-homed vendor prefixes and add the scanner prefix; a ``sprites`` verdict
# on any of these downgrades so MediaHeuristicSignal / TextContentSignal win.
SCAN_STEM_PREFIX_PATTERN = r"^scan_?\d+"
_CAMERA_OR_SCAN_STEM_PATTERNS = tuple(
    re.compile(pattern) for pattern in (*CAMERA_VENDOR_PREFIX_PATTERNS, SCAN_STEM_PREFIX_PATTERN)
)


def _is_camera_or_scan_stem(stem: str) -> bool:
    """True when ``stem`` (already case-folded) is a camera-roll or scanner
    name — the prefixes are lowercase anchored-start regexes."""
    return any(pattern.match(stem) for pattern in _CAMERA_OR_SCAN_STEM_PATTERNS)


# Weak-shape sprite naming traps: the shared module's catch-all sprite rules
# fire on ANY bare lowercase word ("Game asset (single word)": joke, silly,
# apartment), word+trailing-number ("Sprite sequence"/"Numbered variant":
# love10, ganesh5), two-letter stem ("Two-letter asset": aw), or hyphenated
# name ("Hyphenated asset": blue-ai-digital-cube). The stem attests nothing
# game-related — these shapes cover most human photo names — so the verdict
# graduates to FILENAME_WEAK_CONFIDENCE and content evidence decides:
# MediaHeuristicSignal/CLIP (and PhotoCompositionSignal live) outscore it on
# real photos, while a genuine bare-named sprite in a game folder still wins
# via FilepathSignal/GameAssetSignal corroboration. Measured on 13 misfiled
# social photos (scoring-calibration-20260726 §3.2 oracle repair).
_WEAK_SPRITE_STEM_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^[a-z]+$",  # single word (incl. two-letter)
        r"^[a-z]+\d+(_\d+)?$",  # word + trailing number(s)
        r"^[a-z]+(-[a-z]+)+(-copy)?$",  # hyphenated name
    )
)

# Strong numbered stems excluded from the weak shapes: unicode/emoji sprite
# sheets are hex codepoints (1f60a, face12 — the shared "Emoji/unicode asset"
# rule), and the curated game vocabulary ("Game asset (dungeon2)" rule) is a
# real content attestation.
_HEX_STEM_PATTERN = re.compile(r"^[0-9a-f]{4,8}$")
_TRAILING_NUMBER_PATTERN = re.compile(r"^([a-z]+)\d+(_\d+)?$")


def _is_weak_sprite_stem(stem: str) -> bool:
    """True when a ``game_assets/sprites`` verdict rests on a naming-trap
    shape rather than a game-attesting stem (already case-folded)."""
    if _HEX_STEM_PATTERN.match(stem):
        return False
    numbered = _TRAILING_NUMBER_PATTERN.match(stem)
    if numbered and numbered.group(1) in GAME_ASSET_STEM_KEYWORDS:
        return False
    return any(pattern.match(stem) for pattern in _WEAK_SPRITE_STEM_PATTERNS)


def graduated_filename_confidence(stem: str, category: str, subcategory: str, ext: str) -> float:
    """Confidence for a shared filename-rule verdict, downgraded to
    ``FILENAME_WEAK_CONFIDENCE`` when the rule is a weak catch-all the content
    signals should outscore, otherwise ``FILENAME_MATCH_CONFIDENCE``.

    Pure and signal-local: it re-derives the downgrade condition from the
    (case-folded) ``stem``, the returned ``(category, subcategory)`` and the
    extension, because the signal cannot see which shared rule fired.
    """
    result = (category, subcategory)
    if result in FILENAME_WEAK_RESULTS:
        return FILENAME_WEAK_CONFIDENCE
    # Source/host provenance (ChatGPT / Facebook): filename says where the file
    # came from, not what it depicts — content signals should decide the bucket.
    if result in SOURCE_PROVENANCE_RESULTS:
        return FILENAME_WEAK_CONFIDENCE
    # Event/venue maps: let the mid wave run so EventContentSignal can supply
    # the Events/{EventName}/ folder name (see EVENTS_MAP_RESULT above).
    if result == EVENTS_MAP_RESULT:
        return FILENAME_WEAK_CONFIDENCE
    # Archives: let the mid wave read the member listing (ARCHIVE_RESULT above).
    if result == ARCHIVE_RESULT:
        return FILENAME_WEAK_CONFIDENCE
    # Sprite verdict on a camera-roll / scanner stem: it is a photo or a scan.
    if result == GAME_SPRITES_RESULT and _is_camera_or_scan_stem(stem):
        return FILENAME_WEAK_CONFIDENCE
    # Sprite verdict from a weak-shape naming trap (bare word, word+number,
    # hyphenated): the stem attests nothing — let content evidence decide.
    if result == GAME_SPRITES_RESULT and _is_weak_sprite_stem(stem):
        return FILENAME_WEAK_CONFIDENCE
    # The generic "Audio file" catch-all (no music/podcast awareness) on an
    # extension MediaHeuristicSignal can refine to audio_podcasts/audio_music.
    if result == MEDIA_AUDIO_OTHER_RESULT and ext in REFINABLE_AUDIO_EXTENSIONS:
        return FILENAME_WEAK_CONFIDENCE
    return FILENAME_MATCH_CONFIDENCE


# Signal-local evidence key carrying the research-publisher provenance tuple
# (publisher_key, identifier, publisher_name, url).
EVIDENCE_RESEARCH = "research"

# Key under which the shared rule module side-channels research provenance
# into the ``last_file_state`` dict it is handed.
RESEARCH_STATE_KEY = "research"


class FilenamePatternSignal:
    """One signal over the whole shared filename-pattern rule module."""

    name = "filename_pattern"
    weight = W_FILENAME
    cost_tier = "cheap"

    def __init__(self, game_sprite_keywords: List[str]) -> None:
        # The caller's sprite vocabulary (gates the snake_case "Game asset
        # (named)" rule inside the shared module).
        self._game_sprite_keywords: List[str] = list(game_sprite_keywords)

    def applies_to(self, ctx: FileContext) -> bool:
        return True

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        # Local state dict replaces the organizer's per-file side channel;
        # provenance lands in evidence instead (§4 row 2).
        state: Dict[str, object] = {}
        path = ctx.pattern_path
        result = classify_by_filename_patterns(
            path,
            game_sprite_keywords=self._game_sprite_keywords,
            last_file_state=state,
        )
        if result is None:
            return []
        category, subcategory, company_name, people_names = result

        evidence: Dict[str, object] = {}
        if company_name:
            evidence[EVIDENCE_COMPANY] = company_name
        if people_names:
            evidence[EVIDENCE_PEOPLE] = list(people_names)
        if category == RESEARCH_CATEGORY:
            evidence[EVIDENCE_SCHEMA_TYPE] = SCHOLARLY_ARTICLE_SCHEMA_TYPE
            evidence[EVIDENCE_RESEARCH] = state.get(RESEARCH_STATE_KEY)

        stem_lower = path.stem.lower()
        confidence = graduated_filename_confidence(
            stem_lower, category, subcategory, path.suffix.lower()
        )

        # Person-name stems on images: the shared rule files images named after
        # known people as personal/contacts at full strength, but contact records
        # are vCards/resumes — not photographs. Graduate to weak confidence for
        # ImageObject files so content signals (PhotoCompositionSignal,
        # MediaHeuristicSignal, CLIP) can outscore and decide the real bucket.
        # Document-typed resumes ("Alyshia_Ledlie_Resume.pdf") keep full confidence.
        if (category, subcategory) == CONTACTS_RESULT and ctx.is_image:
            confidence = FILENAME_WEAK_CONFIDENCE

        # Stock-asset stems ("stock-vector-*", "pngtree-*"): the stem explicitly
        # asserts vector illustration / graphic template format. The shared rule
        # fires "Hyphenated asset" → game_assets/sprites (already downgraded to
        # weak confidence by the sprite trap graduation). Promote to
        # media/graphics_other to match the explicit format claim; confidence
        # stays at FILENAME_WEAK_CONFIDENCE so CLIP/GraphicDetectionSignal can
        # confirm or override.
        if (category, subcategory) == GAME_SPRITES_RESULT and _is_stock_asset_stem(stem_lower):
            category, subcategory = "media", "graphics_other"

        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
