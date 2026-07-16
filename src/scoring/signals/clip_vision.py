"""ClipVisionSignal — 20-prompt CLIP label votes for images.

Extracted from ``ContentOrganizer._run_clip_signal`` + ``_map_clip_label``
(UNIFIED_SCORING_PLAN §4 row 11). ``GEOGRAPHIC_LABELS`` moved here from the
organizer (which keeps ``_GEOGRAPHIC_LABELS`` as a class-attribute alias);
``map_clip_label`` is the pure mapping the legacy ``_map_clip_label`` now
delegates to, including the GPS → ``GPS_TRAVEL_CATEGORY`` upgrade for
geographic labels.

Divergence (by design, §4 row 11): the legacy ``_run_clip_signal`` hard-gates
on ``CLIP_ENHANCE_THRESHOLD`` — a top score below it yields no candidate at
all. Here that threshold becomes a *soft floor*: the top
``CLIP_TOP_EMISSIONS`` labels are emitted at their raw CLIP score and weak
votes simply lose on weight during aggregation. The legacy method keeps its
hard threshold untouched.

Evidence per emission carries the raw ``clip_label``/``clip_score`` pair; the
decision adapter later maps the top one onto the legacy
``_last_file_state["clip_description"]`` schema.org description state.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from ..types import CategoryScore
from ..weights import W_CLIP

try:
    from shared.constants import CLIP_LABEL_TO_ORGANIZER
except ImportError:  # scripts/shared not on sys.path — no labels map, signal emits nothing
    CLIP_LABEL_TO_ORGANIZER: Dict[str, Tuple[str, str]] = {}

# CLIP labels describing geography; with GPS metadata present they upgrade to
# the travel bucket. Moved from ContentOrganizer._GEOGRAPHIC_LABELS (which now
# aliases this constant).
GEOGRAPHIC_LABELS: FrozenSet[str] = frozenset(
    {
        "a landscape or nature scene",
        "a cityscape or urban scene",
        "a building or architecture",
    }
)

# How many top-scoring CLIP labels get a vote.
CLIP_TOP_EMISSIONS = 3

# Destination for geographic labels when the image carries GPS coordinates.
GPS_TRAVEL_CATEGORY = ("media", "photos_travel")

# Image-metadata key carrying (lat, lon) — the get_metadata_summary() shape.
GPS_COORDINATES_KEY = "gps_coordinates"

# Signal-local evidence keys.
EVIDENCE_CLIP_LABEL = "clip_label"
EVIDENCE_CLIP_SCORE = "clip_score"


def map_clip_label(
    label: str,
    image_metadata: Optional[Mapping[str, Any]],
    label_to_organizer: Mapping[str, Tuple[str, str]],
    geographic_labels: FrozenSet[str],
) -> Optional[Tuple[str, str]]:
    """Map a CLIP label to ``(category, subcategory)``, or ``None`` if unmapped.

    Reproduces ``ContentOrganizer._map_clip_label`` exactly: unknown labels
    return ``None``; geographic labels upgrade to ``GPS_TRAVEL_CATEGORY``
    when the image metadata carries GPS coordinates.
    """
    mapping = label_to_organizer.get(label)
    if not mapping:
        return None
    category, subcategory = mapping
    if image_metadata and image_metadata.get(GPS_COORDINATES_KEY) and label in geographic_labels:
        category, subcategory = GPS_TRAVEL_CATEGORY
    return (category, subcategory)


class ClipVisionSignal:
    """Votes for the organizer mappings of the top CLIP labels."""

    name = "clip_vision"
    weight = W_CLIP
    cost_tier = "heavy"

    def applies_to(self, ctx: Any) -> bool:
        return ctx.is_image

    def run(self, ctx: Any) -> List[CategoryScore]:
        scores = ctx.ensure_clip()
        if not scores:
            return []
        image_metadata = ctx.ensure_image_metadata()

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        emissions: List[CategoryScore] = []
        for label, score in ranked[:CLIP_TOP_EMISSIONS]:
            mapped = map_clip_label(
                label, image_metadata, CLIP_LABEL_TO_ORGANIZER, GEOGRAPHIC_LABELS
            )
            if mapped is None:
                continue
            category, subcategory = mapped
            emissions.append(
                CategoryScore(
                    category=category,
                    subcategory=subcategory,
                    confidence=score,
                    signal_name=self.name,
                    evidence={EVIDENCE_CLIP_LABEL: label, EVIDENCE_CLIP_SCORE: score},
                )
            )
        return emissions
