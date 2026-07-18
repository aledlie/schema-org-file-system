"""PhotoCompositionSignal — people / home-interior CLIP composition flags.

Signal form of ``ContentOrganizer._classify_photo_composition``
(UNIFIED_SCORING_PLAN §4 row 13): one
``ImageContentAnalyzer.analyze_for_organization`` pass yields both flags;
people photos route to the social bucket, empty home interiors to property
management. The legacy method is already a thin adapter over the analyzer
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

from ..types import EVIDENCE_SCHEMA_TYPE, CategoryScore
from ..weights import W_PEOPLE_PHOTO

# Composition confidences: face/people detection is strong but not exact;
# interior detection is a little weaker (staged rooms vs. real listings).
PHOTO_PEOPLE_CONFIDENCE = 0.8
PHOTO_PROPERTY_CONFIDENCE = 0.7

# How many top analyzer scores are kept as debugging evidence.
COMPOSITION_TOP_SCORES = 3

# Destinations for the two composition flags.
PEOPLE_PHOTO_CATEGORY = ("media", "photos_social")
# Home-interior photos file under Media/Interiors and serialize as the
# schema.org Accommodation type ``Room`` (via the schema_type evidence
# override), not the generic image ImageObject. The composition analyzer only
# yields a binary interior flag, so it cannot distinguish the room subtypes —
# it always routes to the generic ``interiors_other`` bucket. The subtype
# folders (Media/Interiors/HotelRoom, Media/Interiors/MeetingRoom) are taxonomy
# scaffolding for a future signal that can tell them apart.
PROPERTY_PHOTO_CATEGORY = ("media", "interiors_other")

# Folder subtype key → schema.org type, mirroring the ``media.interiors``
# branch in src/organizers/category_config.py. The folder namespace is
# "interiors"; the schema namespace is the ``Room`` type family. ``other`` is
# the generic ``Room``.
ROOM_SUBTYPE_SCHEMA = {
    "hotel": "HotelRoom",
    "meeting": "MeetingRoom",
    "other": "Room",
}
ROOM_SCHEMA_TYPE = ROOM_SUBTYPE_SCHEMA["other"]

# Signal-local evidence key.
EVIDENCE_COMPOSITION_SCORES = "composition_scores"


class PhotoCompositionSignal:
    """Votes social/property-management from one composition analysis pass."""

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
        has_people, is_property_mgmt, scores = self._image_analyzer.analyze_for_organization(
            ctx.path
        )

        evidence: Dict[str, Any] = {}
        if scores:
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            evidence[EVIDENCE_COMPOSITION_SCORES] = dict(ranked[:COMPOSITION_TOP_SCORES])

        if has_people:
            category, subcategory = PEOPLE_PHOTO_CATEGORY
            confidence = PHOTO_PEOPLE_CONFIDENCE
        elif is_property_mgmt:
            category, subcategory = PROPERTY_PHOTO_CATEGORY
            confidence = PHOTO_PROPERTY_CONFIDENCE
            evidence[EVIDENCE_SCHEMA_TYPE] = ROOM_SCHEMA_TYPE
        else:
            return []

        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
