"""PhotoCompositionSignal — people CLIP composition flag.

Signal form of ``ContentOrganizer._classify_photo_composition``
(UNIFIED_SCORING_PLAN §4 row 13): one
``ImageContentAnalyzer.analyze_for_organization`` pass; people photos route
to the social bucket. The analyzer's second flag (``is_property_mgmt``, the
home-interior heuristic) is ignored since 2026-07-18 — interior detection is
the trained ``SceneSignal``'s job (``scene.py``), whose calibrated probe
replaced this signal's fixed-confidence interior vote (MEDIA_EXTERIORS_PLAN
decision #5). The legacy method is already a thin adapter over the analyzer
(availability gate + tuple assembly + prints), so it is left unmodified
rather than forced into a delegation — this module holds the equivalent
logic in Signal shape.

Known weakness carried over from the legacy tier: stock-photo people in
marketing material still read as social photos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from typing import Any, Dict, List

from ..types import CategoryScore
from ..weights import W_PEOPLE_PHOTO

# Face/people detection is strong but not exact.
PHOTO_PEOPLE_CONFIDENCE = 0.8

# How many top analyzer scores are kept as debugging evidence.
COMPOSITION_TOP_SCORES = 3

# Destination for the people flag.
PEOPLE_PHOTO_CATEGORY = ("media", "photos_social")

# Signal-local evidence key.
EVIDENCE_COMPOSITION_SCORES = "composition_scores"


class PhotoCompositionSignal:
    """Votes ``media/photos_social`` from one composition analysis pass."""

    name = "photo_composition"
    weight = W_PEOPLE_PHOTO
    cost_tier = "heavy"

    def __init__(self, image_analyzer: Any) -> None:
        self._image_analyzer = image_analyzer

    def applies_to(self, ctx: FileContext) -> bool:
        return (
            ctx.is_image
            and self._image_analyzer is not None
            and self._image_analyzer.vision_available
        )

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        has_people, _is_property_mgmt, scores = self._image_analyzer.analyze_for_organization(
            ctx.path
        )
        if not has_people:
            return []

        evidence: Dict[str, Any] = {}
        if scores:
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            evidence[EVIDENCE_COMPOSITION_SCORES] = dict(ranked[:COMPOSITION_TOP_SCORES])

        category, subcategory = PEOPLE_PHOTO_CATEGORY
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=PHOTO_PEOPLE_CONFIDENCE,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
