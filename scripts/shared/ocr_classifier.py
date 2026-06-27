"""OCR text extraction (docTR) and image classification.

Combines the low-level docTR text-extraction primitives with the screenshot
and Schema.org classification fallbacks that consume them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

OCR_AVAILABLE = False
_predictor = None

try:
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor

    OCR_AVAILABLE = True
except ImportError:
    pass

# HEIC support
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Predictor configuration
# ---------------------------------------------------------------------------

_DET_ARCH = "fast_base"  # default since docTR v0.9, faster than db_resnet50
_RECO_ARCH = "crnn_vgg16_bn"  # reliable baseline recognition


def _detect_device() -> str:
    """Detect best available torch device: CUDA > MPS > CPU."""
    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"

    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass

    return "cpu"


def _get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = ocr_predictor(
            det_arch=_DET_ARCH,
            reco_arch=_RECO_ARCH,
            pretrained=True,
            assume_straight_pages=False,  # support rotated/skewed scans
            straighten_pages=True,  # auto-correct page rotation
            detect_orientation=True,  # classify page orientation (0/90/180/270)
            detect_language=True,  # per-page language detection
            resolve_blocks=True,  # group lines into blocks for reading order
            resolve_lines=True,  # group words into lines
        )
        # docTR 1.x moves predictor to device via .to() after construction
        device = _detect_device()
        if device != "cpu":
            try:
                _predictor = _predictor.to(device)
            except Exception:
                pass
    return _predictor


# ---------------------------------------------------------------------------
# Rich result type
# ---------------------------------------------------------------------------


@dataclass
class OCRResult:
    """Rich OCR result with text, confidence, and metadata."""

    text: str
    confidence: float  # average word confidence (0.0–1.0)
    language: Optional[str]  # ISO 639-1 code or None
    word_count: int
    orientation: Optional[int]  # page rotation in degrees (0/90/180/270)


def _compute_confidence(result) -> float:
    """Compute average word confidence across all pages."""
    confidences = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    confidences.append(word.confidence)
    return sum(confidences) / len(confidences) if confidences else 0.0


def _extract_language(result) -> Optional[str]:
    """Extract primary language from first page."""
    if result.pages and result.pages[0].language:
        lang = result.pages[0].language
        if isinstance(lang, dict):
            return lang.get("value")
        return str(lang)
    return None


def _extract_orientation(result) -> Optional[int]:
    """Extract page orientation from first page."""
    if result.pages and result.pages[0].orientation:
        orient = result.pages[0].orientation
        if isinstance(orient, dict):
            return orient.get("value")
        return int(orient)
    return None


def _count_words(result) -> int:
    """Count total words across all pages."""
    count = 0
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                count += len(line.words)
    return count


# ---------------------------------------------------------------------------
# Text extraction API
# ---------------------------------------------------------------------------


def is_ocr_available() -> bool:
    return OCR_AVAILABLE


def extract_ocr_text(
    image_path: Path,
    max_chars: int = 500,
    config: str = "",  # kept for API compatibility
    timeout: int = 10,  # kept for API compatibility
) -> str | None:
    """Extract text from image using docTR OCR.

    Returns None if OCR unavailable or no text found.
    """
    if not OCR_AVAILABLE:
        return None
    try:
        doc = DocumentFile.from_images([str(image_path)])
        result = _get_predictor()(doc)
        text = result.render()
        text = " ".join(text.split())
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text if text.strip() else None
    except Exception as e:
        print(f"  OCR error: {type(e).__name__}: {e}")
        return None


def extract_ocr_text_pdf(
    pdf_path: Path,
    max_pages: int = 5,
    max_chars: int = 2000,
) -> str | None:
    """Extract text from scanned PDF using docTR OCR.

    Returns None if OCR unavailable or no text found.
    """
    if not OCR_AVAILABLE:
        return None
    try:
        doc = DocumentFile.from_pdf(str(pdf_path))
        if len(doc) > max_pages:
            doc = doc[:max_pages]
        result = _get_predictor()(doc)
        text = result.render()
        text = " ".join(text.split())
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text if text.strip() else None
    except Exception:
        return None


def extract_ocr_with_confidence(
    image_path: Path,
    max_chars: int = 0,
) -> OCRResult | None:
    """Extract text with confidence scores, language, and orientation.

    Returns None if OCR unavailable or no text found.
    Use max_chars=0 for no truncation.
    """
    if not OCR_AVAILABLE:
        return None
    try:
        doc = DocumentFile.from_images([str(image_path)])
        result = _get_predictor()(doc)
        text = result.render()
        text = " ".join(text.split())
        if not text.strip():
            return None
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return OCRResult(
            text=text,
            confidence=_compute_confidence(result),
            language=_extract_language(result),
            word_count=_count_words(result),
            orientation=_extract_orientation(result),
        )
    except Exception:
        return None


def extract_ocr_pdf_with_confidence(
    pdf_path: Path,
    max_pages: int = 5,
    max_chars: int = 2000,
) -> OCRResult | None:
    """Extract text from scanned PDF with confidence and metadata.

    Returns None if OCR unavailable or no text found.
    """
    if not OCR_AVAILABLE:
        return None
    try:
        doc = DocumentFile.from_pdf(str(pdf_path))
        if len(doc) > max_pages:
            doc = doc[:max_pages]
        result = _get_predictor()(doc)
        text = result.render()
        text = " ".join(text.split())
        if not text.strip():
            return None
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return OCRResult(
            text=text,
            confidence=_compute_confidence(result),
            language=_extract_language(result),
            word_count=_count_words(result),
            orientation=_extract_orientation(result),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Classification fallbacks
# ---------------------------------------------------------------------------

# Minimum keyword hits for screenshot-specific matching
SCREENSHOT_MIN_HITS = 2

SCREENSHOT_KEYWORDS: dict[str, list[str]] = {
    "dashboard": [
        "daily requests",
        "monthly cost",
        "active alerts",
        "latency",
        "trace pipeline",
        "provider costs",
        "dashboard",
        "metrics",
        "monitoring",
        "uptime",
        "throughput",
    ],
    "terminal_session": [
        "completed:",
        "next steps:",
        "blocked by",
        "npm run",
        "git ",
        "curl ",
        "http 2",
        "signup successful",
        "deploy",
        "$ ",
        "insert --",
        "bash(",
        "command:",
        "exit code",
    ],
    "error_log": [
        "error:",
        "traceback",
        "exception",
        "stack trace",
        "fatal",
        "panic:",
        "segfault",
        "core dumped",
    ],
    "api_response": [
        '"jwt":',
        '"token":',
        '"userid":',
        "http 200",
        "http 201",
        "http 400",
        "http 500",
        "response:",
        "status:",
        "content-type:",
        "application/json",
    ],
}


def apply_ocr_fallback(
    clip_category: str,
    clip_confidence: float,
    clip_scores: dict[str, float],
    image_path: Path,
    clip_threshold: float = 0.10,
    content_classifier=None,
    verbose: bool = False,
) -> tuple[str, float, dict[str, float], str | None]:
    """Apply unified OCR fallback logic with threshold+decision layer.

    Decides whether to use CLIP result as-is, try OCR, or merge results.

    Args:
      clip_category: Best CLIP match category
      clip_confidence: CLIP confidence score
      clip_scores: All CLIP scores dict
      image_path: Path to image file
      clip_threshold: Min confidence to skip OCR (default 0.10)
      content_classifier: Optional ContentClassifier for schema.org fallback
      verbose: Print fallback decisions

    Returns:
      Tuple of (final_category, final_confidence, final_scores, ocr_text).
      ocr_text is None if OCR wasn't used or failed.
    """
    # If CLIP confidence is acceptable, return as-is
    if clip_confidence >= clip_threshold:
        return (clip_category, clip_confidence, clip_scores, None)

    # CLIP confidence too low; try OCR fallback
    ocr_result = classify_by_ocr(image_path, content_classifier)

    if not ocr_result:
        # OCR failed; return original CLIP result
        return (clip_category, clip_confidence, clip_scores, None)

    ocr_category, ocr_confidence, ocr_scores, ocr_text = ocr_result

    # Use OCR if it's better than CLIP
    if ocr_confidence > clip_confidence:
        if verbose:
            print(f"  ↪ OCR fallback: {ocr_category} ({ocr_confidence:.0%})")
        # Merge scores: OCR overrides but keep CLIP scores too
        merged_scores = {**clip_scores, **ocr_scores}
        return (ocr_category, ocr_confidence, merged_scores, ocr_text)

    # CLIP was better; return original
    return (clip_category, clip_confidence, clip_scores, ocr_text)


def classify_by_ocr(
    image_path: Path,
    content_classifier=None,
    max_chars: int = 1000,
) -> tuple[str, float, dict[str, float], str] | None:
    """Classify image by OCR text extraction with fallback hierarchy.

    Tries screenshot-specific keywords first, then falls back to Schema.org
    taxonomy if available.

    Args:
      image_path: Path to the image file
      content_classifier: Optional ContentClassifier for schema.org taxonomy
      max_chars: Max characters to extract via OCR

    Returns:
      Tuple of (category, confidence, all_scores, extracted_text) or None
      if OCR unavailable or no matches found.
      all_scores maps every matched category to its confidence.
    """
    if not is_ocr_available():
        return None

    text = extract_ocr_text(image_path, max_chars=max_chars)
    if not text:
        return None

    text_lower = text.lower()

    # Screenshot-specific scores
    screenshot_scores: dict[str, float] = {}
    screenshot_hits: dict[str, int] = {}
    for category, keywords in SCREENSHOT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            screenshot_hits[category] = hits
            screenshot_scores[category] = hits / len(keywords)

    # Schema.org taxonomy scores (if classifier provided)
    schema_scores: dict[str, float] = {}
    if content_classifier:
        schema_scores = content_classifier.score_all_categories(text, image_path.name)

    # Merge: screenshot-specific keys take precedence
    all_scores = {**schema_scores, **screenshot_scores}

    if not all_scores:
        return None

    # Pass 1: screenshot-specific winner
    if screenshot_scores:
        best_ss = max(screenshot_scores, key=screenshot_scores.get)
        if screenshot_hits[best_ss] >= SCREENSHOT_MIN_HITS:
            return (best_ss, screenshot_scores[best_ss], all_scores, text)

    # Pass 2: Schema.org taxonomy winner
    if schema_scores and content_classifier:
        category, subcategory, _company, _people = content_classifier.classify_content(
            text, image_path.name
        )
        if category != "uncategorized":
            label = f"{category}_{subcategory}" if subcategory != "other" else category
            return (label, schema_scores.get(category, 0.0), all_scores, text)

    return None
