"""RenamedScreenshotSignal — renamer-classified screenshot routing (§4 row 1).

Extracted from the inline "PRIORITY 0a" block of
``ContentOrganizer._detect_file_category_legacy``: when the image renamer has
already classified a screenshot (e.g. ``"Screenshot ..."`` →
``"20260320_terminal_session.png"``), the renamed stem is matched against the
organizer's screenshot sub-folder keys directly. The legacy block delegates to
:func:`match_renamed_screenshot` so the matching rule is single-homed.

Behavior divergences from the legacy chain: none in the matching rule itself.
The legacy block short-circuits the whole chain on a match; the signal instead
emits one very-high-precision vote (``W_RENAMED`` = 1.2 prior ×
``RENAMED_MATCH_CONFIDENCE`` = 1.0) that competes with the other signals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from typing import Iterable, List, Mapping, Optional

from ..types import CategoryScore
from ..weights import W_RENAMED

# A renamed screenshot is the renamer's own content classification — treat the
# key match as certain (precision comes from the display/physical name split).
RENAMED_MATCH_CONFIDENCE = 1.0

# Physical-path stem marker identifying an original screenshot capture.
SCREENSHOT_STEM_MARKER = "screenshot"

# The generic screenshots bucket never matches (any stem could contain it via
# words like "another"; it also carries no routing information).
OTHER_SCREENSHOT_KEY = "other"

MEDIA_CATEGORY = "media"
SCREENSHOT_SUBCATEGORY_PREFIX = "photos_screenshots_"

# Signal-local evidence keys.
EVIDENCE_MATCHED_KEY = "matched_key"
EVIDENCE_RENAMED_STEM = "renamed_stem"


def match_renamed_screenshot(renamed_stem: str, screenshot_keys: Iterable[str]) -> Optional[str]:
    """Match a renamed screenshot stem against screenshot sub-folder keys.

    Checks longer keys first so ``"terminal_session"`` matches before
    ``"terminal"``; the ``"other"`` bucket is skipped. Returns the matched key
    or ``None``.
    """
    for key in sorted(screenshot_keys, key=len, reverse=True):
        if key != OTHER_SCREENSHOT_KEY and key in renamed_stem:
            return key
    return None


class RenamedScreenshotSignal:
    """Route renamer-classified screenshots to their content sub-folder."""

    name = "renamed_screenshot"
    weight = W_RENAMED
    cost_tier = "cheap"

    def __init__(self, screenshots_dict: Mapping[str, object]) -> None:
        # The organizer's category_paths["media"]["photos"]["screenshots"];
        # only the keys drive matching (insertion order preserved so the
        # stable longest-first sort matches the legacy dict iteration).
        self._screenshot_keys: List[str] = list(screenshots_dict)

    def applies_to(self, ctx: FileContext) -> bool:
        return (
            ctx.display_path is not None
            and ctx.display_path != ctx.path
            and SCREENSHOT_STEM_MARKER in ctx.path.stem.lower()
        )

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        if ctx.display_path is None:  # guaranteed by applies_to; guard for type-safety
            return []
        renamed_stem = ctx.display_path.stem.lower()
        key = match_renamed_screenshot(renamed_stem, self._screenshot_keys)
        if key is None:
            return []
        return [
            CategoryScore(
                category=MEDIA_CATEGORY,
                subcategory=f"{SCREENSHOT_SUBCATEGORY_PREFIX}{key}",
                confidence=RENAMED_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence={
                    EVIDENCE_MATCHED_KEY: key,
                    EVIDENCE_RENAMED_STEM: renamed_stem,
                },
            )
        ]
