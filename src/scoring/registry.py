"""Ordered signal registry (UNIFIED_SCORING_PLAN §3.4).

Registration order is load-bearing: it is the deterministic tie-break
fallback (§3.3 #4) and the precedence order for merged entity evidence.
Keep it aligned with the §4 table (priors descending).

Phase-1 signal extractions register here one line each; adding or removing a
signal must never require orchestrator edits.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .types import Signal


def build_default_signals(
    *,
    classifier: Any = None,
    screenshot_classifier: Any = None,
    image_analyzer: Any = None,
    category_paths: Optional[dict] = None,
    game_sprite_keywords: Optional[List[str]] = None,
) -> List[Signal]:
    """Build the production signal list in §4 order.

    Dependency parameters mirror what ``ContentOrganizer`` owns today:

    - ``classifier``: ContentClassifier (keyword scoring + entity extraction),
      consumed by the organization/person/text/KIE signals.
    - ``screenshot_classifier``: ContentClassifier used for screenshot OCR
      sub-classification (the production script passes the image renamer's).
    - ``image_analyzer``: ImageContentAnalyzer (vision availability + photo
      composition analysis).
    - ``category_paths``: the organizer's (deep-copied) content taxonomy —
      the screenshots sub-dict keys drive renamed-screenshot/OCR routing.
    - ``game_sprite_keywords``: the caller's sprite vocabulary for filename
      rules.

    Phase 0 ships an empty registry (the unified path returns the
    low-confidence fallback); Phase-1 batches append their signals here in
    §4 order: RenamedScreenshot, FilenamePattern, KieStructured,
    IdentityDocument, OrganizationKeyword, PersonalDoc, LegalContent,
    GameAsset, TextContent, ScreenshotOcr, ClipVision, MediaHeuristic,
    PhotoComposition, Filepath, MimeFallback.
    """
    return []
