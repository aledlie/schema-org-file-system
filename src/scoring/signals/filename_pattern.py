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
"""

from __future__ import annotations

from typing import Any, Dict, List

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

# Filename rules are exact-match heuristics; a hit is signal-locally certain
# (the W_FILENAME prior expresses how much the scorer trusts the rule set).
FILENAME_MATCH_CONFIDENCE = 1.0

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

    def applies_to(self, ctx: Any) -> bool:
        return True

    def run(self, ctx: Any) -> List[CategoryScore]:
        # Local state dict replaces the organizer's per-file side channel;
        # provenance lands in evidence instead (§4 row 2).
        state: Dict[str, Any] = {}
        result = classify_by_filename_patterns(
            ctx.pattern_path,
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

        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=FILENAME_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
