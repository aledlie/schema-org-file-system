"""MimeFallbackSignal — MIME/extension fallback routing (§4 row 15).

Wraps ``src.organizers.mime_classifier.classify_by_mime`` plus the
``_MIME_TO_CONTENT`` translation, both moved here from
``src.organizers.content_organizer`` (which imports them back under their
legacy underscore names for its tier-6 fallback and existing test imports).
Importing ``src.organizers.category_config`` / ``mime_classifier`` here is
safe: neither imports the scoring package, so there is no cycle.

Calibrated §4 property (BACKLOG Phase-3 item #1, resolved): ``W_MIME`` = 0.4
now clears ``MIN_DECISION_CONFIDENCE`` = 0.35, so a mime-only match
(``0.4 × MIME_MATCH_CONFIDENCE (1.0) = 0.4``) commits — restoring the legacy
tier-6 MIME rescue the unified path had lost for binary media (gif/webp/
video/audio/fonts) with no extractable text. It stays the weakest voice: the
``MIN_DECISION_MARGIN`` (0.10) gate means a mime guess that disagrees with a
content winner scoring ≥ 0.35 can't commit (the lead is < 0.10, so both route
to fallback), and content that clears the floor always out-commits it. See
``src/scoring/weights.py`` and ``tests/unit/scoring/test_mime_commit_gap.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from typing import Dict, List, Optional, Tuple

from src.organizers.category_config import FONTS_PATHS
from src.organizers.mime_classifier import classify_by_mime

from ..types import CategoryScore
from ..weights import W_MIME

# The format lookup itself is certain — the W_MIME prior (0.4) is what keeps
# this the weakest voice in the aggregate.
MIME_MATCH_CONFIDENCE = 1.0

# Signal-local evidence keys (the raw classify_by_mime result).
EVIDENCE_MIME_CATEGORY = "mime_category"
EVIDENCE_MIME_SUBCATEGORY = "mime_subcategory"

# Translation from ``classify_by_mime``'s ``CATEGORY_PATHS`` namespace
# (``images``/``code``/``data``/…, absent from ``CONTENT_CATEGORY_PATHS``) into
# the content taxonomy. Each mime category maps to a {subcategory: content
# (cat, subcat)} branch; the ``None`` key is the default for any other
# subcategory of that category — so new ``classify_by_mime`` subcats route
# sensibly instead of falling through to uncategorized. Media targets use the
# underscored ``media_type_subcat`` form that ``get_destination_path`` resolves.
# Categories absent here (documents, archives, generic ``other``) have no
# content home: they are text-classifiable types that stay uncategorized rather
# than being force-filed. ``fonts`` passes subcategories through unchanged,
# keying off ``FONTS_PATHS`` as the single source for its subcategory set.
MIME_TO_CONTENT: Dict[str, Dict[Optional[str], Tuple[str, str]]] = {
    "images": {
        "screenshots": ("media", "photos_screenshots"),
        "graphics": ("media", "graphics_other"),
        None: ("media", "photos_other"),  # photos / other
    },
    "media": {
        "music": ("media", "audio_music"),
        "videos": ("media", "videos_other"),
        None: ("media", "audio_other"),  # audio
    },
    "software": {None: ("technical", "software_packages")},
    "code": {"web": ("technical", "web"), None: ("technical", "other")},
    "data": {"config": ("technical", "config"), None: ("technical", "data")},
    "research": {None: ("research", "other")},
    "fonts": {k: ("fonts", k) for k in FONTS_PATHS},  # identity passthrough
}


def mime_result_to_content_category(category: str, subcategory: str) -> Optional[Tuple[str, str]]:
    """Translate a ``classify_by_mime`` result into the content taxonomy.

    Returns the content (category, subcategory) that ``get_destination_path``
    resolves, or ``None`` for formats with no content home (documents, archives,
    generic ``other``) — see ``MIME_TO_CONTENT`` for the mapping rationale.
    """
    branch = MIME_TO_CONTENT.get(category)
    if branch is None:
        return None
    return branch.get(subcategory, branch.get(None))


class MimeFallbackSignal:
    """Always-on MIME/extension vote, deliberately too weak to override."""

    name = "mime_fallback"
    weight = W_MIME
    cost_tier = "cheap"

    def applies_to(self, ctx: FileContext) -> bool:
        return True

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        mime_category, mime_subcategory, _schema_type = classify_by_mime(ctx.path, None)
        translated = mime_result_to_content_category(mime_category, mime_subcategory)
        if translated is None:
            # Documents/archives/other stay unforced — text signals decide.
            return []
        category, subcategory = translated
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=MIME_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence={
                    EVIDENCE_MIME_CATEGORY: mime_category,
                    EVIDENCE_MIME_SUBCATEGORY: mime_subcategory,
                },
            )
        ]
