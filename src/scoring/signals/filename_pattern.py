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
from typing import Any, Dict, List

from shared.constants import CAMERA_VENDOR_PREFIX_PATTERNS
from shared.filename_classifier import (
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
SOURCE_PROVENANCE_RESULTS = frozenset(
    {("media", "photos_chatgpt"), ("media", "photos_facebook")}
)

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
    # Sprite verdict on a camera-roll / scanner stem: it is a photo or a scan.
    if result == GAME_SPRITES_RESULT and _is_camera_or_scan_stem(stem):
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
        state: Dict[str, Any] = {}
        path = ctx.pattern_path
        result = classify_by_filename_patterns(
            path,
            game_sprite_keywords=self._game_sprite_keywords,
            last_file_state=state,
        )
        if result is None:
            return []
        category, subcategory, company_name, people_names = result

        evidence: Dict[str, Any] = {}
        if company_name:
            evidence[EVIDENCE_COMPANY] = company_name
        if people_names:
            evidence[EVIDENCE_PEOPLE] = list(people_names)
        if category == RESEARCH_CATEGORY:
            evidence[EVIDENCE_SCHEMA_TYPE] = SCHOLARLY_ARTICLE_SCHEMA_TYPE
            evidence[EVIDENCE_RESEARCH] = state.get(RESEARCH_STATE_KEY)

        confidence = graduated_filename_confidence(
            path.stem.lower(), category, subcategory, path.suffix.lower()
        )
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
