"""ScreenshotOcrSignal — screenshot OCR keyword routing (§4 row 10).

Extracted from ``ContentOrganizer._classify_screenshot_ocr`` step 1 (the OCR
keyword routing). Step 2 — CLIP enhancement for images OCR could not
classify — belongs to the CLIP-flavored signals in the unified world; the
legacy method keeps it (plus its prints and fall-through) bit-for-bit and
delegates only the step-1 branch decisions to :func:`route_screenshot_ocr`.

OCR backend note: the shared ``classify_by_ocr`` runs its own
screenshot-tuned extraction (``extract_screenshot_text``: easyocr-preferring
with docTR fallback and dark-background preprocessing) rather than
``ctx.ensure_ocr()`` — intentional parity with the legacy tier, which never
used the document OCR path for screenshots.

Fallback guarantee: legacy always returned *something* for screenshot-named
files; the signal mirrors that by ALWAYS emitting a weak
``media/photos_screenshots_other`` fallback so screenshot-named files land
somewhere, while staying weak enough for CLIP/text signals to outscore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

import re
from typing import Any, Callable, Iterable, List, Optional, Tuple

from ..types import CategoryScore
from ..weights import W_UI

# Minimum keyword-hit ratio to accept a screenshot OCR sub-classification.
# classify_by_ocr() scores as hits/len(keywords), so this is calibrated to that
# scale — NOT to CLIP probability space.  With SCREENSHOT_MIN_HITS=2 and the
# largest category having 14 keywords, 2 hits = 14.3%.  A threshold of 0.10
# accepts any category that cleared SCREENSHOT_MIN_HITS (the real quality bar);
# the 0.30 gate previously used was copied from _OCR_CONFIDENCE_THRESHOLD and
# silently rejected valid 3-18% scores as "low confidence".
SCREENSHOT_OCR_KEYWORD_THRESHOLD = 0.10

# Keyword-routed OCR sub-classification is high precision (legacy accepted it
# outright); the fallback is deliberately weak (see module docstring).
UI_KEYWORD_CONFIDENCE = 0.9
UI_FALLBACK_CONFIDENCE = 0.3

MEDIA_CATEGORY = "media"
SCREENSHOT_SUBCATEGORY_PREFIX = "photos_screenshots_"
SCREENSHOT_FALLBACK_SUBCATEGORY = "photos_screenshots_other"

# "<category>_<subcategory>" separator in schema-taxonomy OCR labels.
CATEGORY_SEPARATOR = "_"

# Signal-local evidence keys.
EVIDENCE_KEYWORD_RATIO = "keyword_ratio"
EVIDENCE_OCR_CATEGORY = "ocr_category"
EVIDENCE_FALLBACK = "fallback"

# Screenshot-name predicate vocabulary (legacy tier 4.5 gate): raw
# screenshot stems start with "screenshot"/contain "screen shot"; stems that
# merely contain "screenshot" count unless the renamer already classified
# them with a structured "<kind>_" prefix.
SCREENSHOT_STEM_PREFIX = "screenshot"
SCREEN_SHOT_TOKEN = "screen shot"
_RENAMED_SCREENSHOT_PREFIX_RE = re.compile(
    r"^(browser|terminal|code|docs|settings|product|chat|dashboard)_"
)

# Default OCR classifier — injected per instance for tests. Import degrades
# gracefully (like the legacy organizer's guarded import): without the OCR
# stack the signal emits only the weak fallback.
_default_ocr_classify: Optional[Callable[..., Any]]
try:
    from shared.ocr_classifier import classify_by_ocr as _default_ocr_classify
except ImportError:  # pragma: no cover - depends on optional OCR stack
    _default_ocr_classify = None


def is_screenshot_named(stem: str) -> bool:
    """True when a lowercased stem names a raw (un-renamed) screenshot."""
    return (
        stem.startswith(SCREENSHOT_STEM_PREFIX)
        or SCREEN_SHOT_TOKEN in stem
        or (SCREENSHOT_STEM_PREFIX in stem and not _RENAMED_SCREENSHOT_PREFIX_RE.match(stem))
    )


def route_screenshot_ocr(
    ocr_category: str,
    ocr_confidence: float,
    screenshot_keys: Iterable[str],
) -> Optional[Tuple[str, str]]:
    """Step-1 OCR routing decision: ``(category, subcategory)`` or ``None``.

    - keyword ratio below ``SCREENSHOT_OCR_KEYWORD_THRESHOLD`` → ``None``
      (legacy falls back to CLIP);
    - category in ``screenshot_keys`` → screenshot subfolder under media;
    - "_"-bearing schema-taxonomy category → cross-category reclassification
      ``(prefix, full_label)``;
    - anything else → ``None`` (legacy falls through to step 2).
    """
    if ocr_confidence < SCREENSHOT_OCR_KEYWORD_THRESHOLD:
        return None
    if ocr_category in screenshot_keys:
        return (MEDIA_CATEGORY, f"{SCREENSHOT_SUBCATEGORY_PREFIX}{ocr_category}")
    if CATEGORY_SEPARATOR in ocr_category:
        return (ocr_category.split(CATEGORY_SEPARATOR)[0], ocr_category)
    return None


class ScreenshotOcrSignal:
    """Screenshot-named images → OCR keyword routing + weak fallback."""

    name = "screenshot_ocr"
    weight = W_UI
    cost_tier = "mid"

    def __init__(
        self,
        screenshot_classifier: Any = None,
        screenshots_dict: Any = None,
        ocr_classify: Optional[Callable[..., Any]] = None,
    ) -> None:
        # ContentClassifier for schema-taxonomy OCR fallback (may be None).
        self._screenshot_classifier = screenshot_classifier
        # Screenshot subfolder mapping — only its keys drive routing.
        self._screenshot_keys = screenshots_dict if screenshots_dict is not None else {}
        self._ocr_classify = ocr_classify if ocr_classify is not None else _default_ocr_classify

    def applies_to(self, ctx: FileContext) -> bool:
        return ctx.is_image and is_screenshot_named(ctx.path.stem.lower())

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        scores: List[CategoryScore] = []
        result = None
        if self._ocr_classify is not None:
            # Reuse the shared OCR extraction (ctx.ensure_ocr) rather than
            # running a second easyocr pass: an image the identity/KIE signals
            # already OCR'd is not re-read here. A None OCR result means "OCR ran
            # and found nothing" and is passed as "" so classify_by_ocr does not
            # re-extract; only a wholly OCR-less context (no provider) leaves it
            # to classify_by_ocr's own extraction path.
            ocr = ctx.ensure_ocr()
            ocr_text = ocr.text if ocr is not None else ""
            result = self._ocr_classify(
                ctx.path, content_classifier=self._screenshot_classifier, text=ocr_text
            )
        if result:
            ocr_category, ocr_confidence, _all_scores, _text = result
            routed = route_screenshot_ocr(ocr_category, ocr_confidence, self._screenshot_keys)
            if routed is not None:
                category, subcategory = routed
                scores.append(
                    CategoryScore(
                        category=category,
                        subcategory=subcategory,
                        confidence=UI_KEYWORD_CONFIDENCE,
                        signal_name=self.name,
                        evidence={
                            EVIDENCE_KEYWORD_RATIO: ocr_confidence,
                            EVIDENCE_OCR_CATEGORY: ocr_category,
                        },
                    )
                )
        # Always emitted: screenshot-named files must land somewhere (legacy
        # guarantee), but weakly enough for CLIP/text signals to outscore.
        scores.append(
            CategoryScore(
                category=MEDIA_CATEGORY,
                subcategory=SCREENSHOT_FALLBACK_SUBCATEGORY,
                confidence=UI_FALLBACK_CONFIDENCE,
                signal_name=self.name,
                evidence={EVIDENCE_FALLBACK: True},
            )
        )
        return scores
