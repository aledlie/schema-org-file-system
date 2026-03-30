"""
Image content analysis using CLIP zero-shot classification and OpenCV face detection.

CLIP inference is delegated to the shared CLIPClassifier singleton
(scripts/shared/clip_utils.py) so that a single model instance serves all callers.
"""

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Tuple

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

        def __exit__(self, *args: Any) -> bool:
            return False


_INTERIOR_CATEGORIES = [
    "a photo of a home interior room",
    "a photo of a living room",
    "a photo of a bedroom",
    "a photo of a kitchen",
    "a photo of a bathroom",
    "a photo of furniture",
]

_ALL_CATEGORIES = _INTERIOR_CATEGORIES + [
    "a photo of a house exterior",
    "a photo of people",
    "a screenshot",
    "a photo of outdoors",
    "a photo of nature",
]

_INTERIOR_SCORE_THRESHOLD = 0.3
_PEOPLE_SCORE_THRESHOLD = 0.2
_PEOPLE_SCORE_LOW_THRESHOLD = 0.15
_SCREENSHOT_SCORE_THRESHOLD = 0.4


class ImageContentAnalyzer:
    """Analyzes image content using computer vision."""

    def __init__(self, cost_calculator: Any = None) -> None:
        self.vision_available = _CV2_AVAILABLE and (CLIP_AVAILABLE or CLIP_CACHE_AVAILABLE)
        self.face_cascade = None
        self.cost_calculator = cost_calculator

        if _CV2_AVAILABLE:
            try:
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
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

        ctx = CostTracker(self.cost_calculator, "face_detection") if self.cost_calculator else nullcontext()
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

        ctx = CostTracker(self.cost_calculator, "clip_vision") if self.cost_calculator else nullcontext()
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
        people_score = scores.get("a photo of people", 0)
        has_faces = self.detect_people(image_path)

        is_interior = interior_score > _INTERIOR_SCORE_THRESHOLD
        has_people = people_score > _PEOPLE_SCORE_THRESHOLD or has_faces

        return (is_interior and not has_people, scores)

    def analyze_for_organization(
        self, image_path: Path
    ) -> Tuple[bool, bool, Dict[str, float]]:
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
        people_score = scores.get("a photo of people", 0)
        screenshot_score = scores.get("a screenshot", 0)

        is_interior = interior_score > _INTERIOR_SCORE_THRESHOLD
        clip_has_people = people_score > _PEOPLE_SCORE_THRESHOLD
        has_people = (people_score > _PEOPLE_SCORE_LOW_THRESHOLD or has_faces) and not (
            screenshot_score > _SCREENSHOT_SCORE_THRESHOLD
        )
        is_home_interior_no_people = is_interior and not (clip_has_people or has_faces)

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

        people_score = scores.get("a photo of people", 0)
        has_faces = self.detect_people(image_path)
        screenshot_score = scores.get("a screenshot", 0)
        is_screenshot = screenshot_score > _SCREENSHOT_SCORE_THRESHOLD

        has_people = (people_score > _PEOPLE_SCORE_LOW_THRESHOLD or has_faces) and not is_screenshot

        return (has_people, scores)
