"""
Image content analysis using CLIP zero-shot classification and OpenCV face detection.

CLIP inference is delegated to the shared CLIPClassifier singleton
(scripts/shared/clip_utils.py) so that a single model instance serves all callers.
"""

from contextlib import nullcontext
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, Literal, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    # The bare cost_roi_calculator import below is Any to mypy; the
    # src.-prefixed form is the one that resolves.
    from src.cost_roi_calculator import CostROICalculator

# Vision libraries are optional
try:
    import cv2

    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

# CLIP (open-clip via shared.clip_utils)
try:
    from shared.clip_utils import get_clip_classifier, CLIP_AVAILABLE
except ImportError:
    CLIP_AVAILABLE = False

# CLIP cache support
try:
    from shared.clip_cache import get_cached_embedding, CLIP_CACHE_AVAILABLE
except ImportError:
    CLIP_CACHE_AVAILABLE = False

# Cost tracking is optional
try:
    from cost_roi_calculator import CostTracker
except ImportError:

    class CostTracker:  # type: ignore[no-redef]
        """Stub when cost tracking is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "CostTracker":
            return self

        def __exit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
        ) -> Literal[False]:
            return False


_INTERIOR_CATEGORIES = [
    "a photo of a home interior room",
    "a photo of a living room",
    "a photo of a bedroom",
    "a photo of a kitchen",
    "a photo of a bathroom",
    "a photo of furniture",
]

_SCREENSHOT_LABEL = "a screenshot of a computer screen"
_PEOPLE_LABEL = "a photo of people"

# Non-photographic labels. Without them every logo, icon and flat graphic is
# out-of-vocabulary: the softmax must still sum to 1 over labels that all
# misfit, so the argmax lands arbitrarily — and it landed on _PEOPLE_LABEL for
# 13 of 28 images in the 2026-08-11 measurement (9 logos, 3 icons, 1 text
# screenshot). Giving those images a label to win keeps them off the people
# gate; measured, all 9 logos moved here and every genuine people photo stayed.
_GRAPHIC_LABELS = [
    "a logo or brand mark",
    "a graphic design or illustration",
]

_ALL_CATEGORIES = (
    _INTERIOR_CATEGORIES
    + [
        "a photo of a house exterior",
        _PEOPLE_LABEL,
        _SCREENSHOT_LABEL,
        "a photo of outdoors",
        "a photo of nature",
    ]
    + _GRAPHIC_LABELS
)

# Interior gate. DEAD, and deliberately left that way: CLIP scores here are an
# unscaled-cosine softmax pinned near the uniform floor (max 0.1003 measured
# over 39 images), so 0.3 can never be reached and `is_home_interior_no_people`
# is always False. Interior detection moved to the trained SceneSignal on
# 2026-07-18, so converting this to a rank test would resurrect a heuristic the
# project replaced on purpose and re-route photos to property_management/other.
# See docs/BACKLOG.md — CLIP scores are a softmax over raw cosines.
_INTERIOR_SCORE_THRESHOLD = 0.3


def _ranks_top(scores: Dict[str, float], label: str) -> bool:
    """True when ``label`` scores at or above every other label.

    Rank is the only usable reading of these scores. ``_similarities`` softmaxes
    unscaled cosines, so the distribution sits at the uniform floor (0.0903–0.1003
    measured over 39 images against a 1/N floor of 0.0909) and every absolute
    threshold written against it is unreachable. Softmax is order-preserving, so
    a rank test is invariant to the missing ``logit_scale`` — restoring the
    scaling later changes these magnitudes but not this comparison, which is
    exactly why rank is used here rather than a ratio.

    Ties count as ranking top (``>=``) so the answer never depends on dict
    insertion order, which ``max()`` would otherwise decide arbitrarily. Callers
    testing two labels can therefore both be true, and it is the caller's job to
    resolve that — see the screenshot suppression in ``analyze_for_organization``.

    A distribution whose labels all score identically carries no ranking at all,
    so nothing ranks top and this returns False rather than True for every label.
    Real softmax output never lands exactly uniform, so this only guards
    degenerate and empty inputs — but without it an all-zero dict would fire
    every gate at once, including suppressions.
    """
    if not scores:
        return False
    top = max(scores.values())
    if top == min(scores.values()):
        return False
    return scores.get(label, 0.0) >= top


class ImageContentAnalyzer:
    """Analyzes image content using computer vision."""

    def __init__(self, cost_calculator: Optional["CostROICalculator"] = None) -> None:
        self.vision_available = _CV2_AVAILABLE and (CLIP_AVAILABLE or CLIP_CACHE_AVAILABLE)
        self.face_cascade = None
        self.cost_calculator = cost_calculator

        if _CV2_AVAILABLE:
            try:
                haar_dir = cv2.data.haarcascades  # type: ignore[attr-defined]
                cascade_path = haar_dir + "haarcascade_frontalface_default.xml"
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
            except Exception as e:
                print(f"Warning: Could not load face cascade: {e}")

        if self.vision_available and not CLIP_CACHE_AVAILABLE:
            try:
                # Eagerly warm the singleton so load errors surface at init time.
                get_clip_classifier()
            except Exception as e:
                print(f"Warning: Could not load CLIP model: {e}")
                self.vision_available = False

    def detect_people(self, image_path: Path) -> bool:
        """
        Detect if there are people in the image using face detection.

        Returns:
            True if people detected, False otherwise
        """
        if not _CV2_AVAILABLE or self.face_cascade is None:
            return False

        ctx = (
            CostTracker(self.cost_calculator, "face_detection")
            if self.cost_calculator
            else nullcontext()
        )
        with ctx:
            try:
                img = cv2.imread(str(image_path))
                if img is None:
                    return False

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30),
                )
                return len(faces) > 0

            except Exception as e:
                print(f"  Face detection error: {e}")
                return False

    def classify_image_content(self, image_path: Path) -> Dict[str, float]:
        """
        Classify image content using CLIP zero-shot classification.

        Returns:
            Dictionary of category -> confidence score
        """
        if not self.vision_available:
            return {}

        ctx = (
            CostTracker(self.cost_calculator, "clip_vision")
            if self.cost_calculator
            else nullcontext()
        )
        with ctx:
            try:
                if CLIP_CACHE_AVAILABLE:
                    results = get_cached_embedding(image_path, _ALL_CATEGORIES, prompt_prefix="")
                    return {label: conf for label, conf in results}

                results = get_clip_classifier().classify_raw(image_path, _ALL_CATEGORIES)
                return {label: conf for label, conf in results}

            except Exception as e:
                print(f"  Image classification error: {e}")
            return {}

    def is_home_interior_no_people(self, image_path: Path) -> Tuple[bool, Dict[str, float]]:
        """
        Check if image is a home interior without people.

        Returns:
            Tuple of (is_interior_no_people, classification_scores)
        """
        if not self.vision_available:
            return (False, {})

        scores = self.classify_image_content(image_path)

        if not scores:
            return (False, {})

        interior_score = max(scores.get(cat, 0) for cat in _INTERIOR_CATEGORIES)
        has_faces = self.detect_people(image_path)

        is_interior = interior_score > _INTERIOR_SCORE_THRESHOLD
        has_people = _ranks_top(scores, _PEOPLE_LABEL) or has_faces

        return (is_interior and not has_people, scores)

    def analyze_for_organization(self, image_path: Path) -> Tuple[bool, bool, Dict[str, float]]:
        """
        Run CLIP inference once and return both organization-relevant flags.

        Returns:
            Tuple of (has_people, is_home_interior_no_people, scores)
        """
        if not self.vision_available:
            return (False, False, {})

        scores = self.classify_image_content(image_path)
        if not scores:
            return (False, False, {})

        has_faces = self.detect_people(image_path)

        interior_score = max(scores.get(cat, 0) for cat in _INTERIOR_CATEGORIES)

        is_interior = interior_score > _INTERIOR_SCORE_THRESHOLD
        # Rank, not magnitude — see _ranks_top. Structure is the original
        # (people OR faces) AND NOT screenshot; only the comparison changed.
        # The screenshot clause is what keeps a face detected inside a
        # screenshot (a video call, a photo of a photo) out of the social
        # bucket, and it wins a people/screenshot tie because it is applied
        # last — suppression is the conservative resolution.
        has_people = (_ranks_top(scores, _PEOPLE_LABEL) or has_faces) and not _ranks_top(
            scores, _SCREENSHOT_LABEL
        )
        is_home_interior_no_people = is_interior and not has_people

        return (has_people, is_home_interior_no_people, scores)

    def has_people_in_photo(self, image_path: Path) -> Tuple[bool, Dict[str, float]]:
        """
        Check if image contains people (for social photos).

        Returns:
            Tuple of (has_people, classification_scores)
        """
        if not self.vision_available:
            return (False, {})

        scores = self.classify_image_content(image_path)

        if not scores:
            return (False, {})

        has_faces = self.detect_people(image_path)
        is_screenshot = _ranks_top(scores, _SCREENSHOT_LABEL)

        has_people = (_ranks_top(scores, _PEOPLE_LABEL) or has_faces) and not is_screenshot

        return (has_people, scores)
