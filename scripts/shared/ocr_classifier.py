"""OCR text extraction (docTR) and image classification.

Combines the low-level docTR text-extraction primitives with the screenshot
and Schema.org classification fallbacks that consume them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shared.constants import HEIC_HEIF_EXTENSIONS
from shared.ocr_easyocr import (
    EASYOCR_AVAILABLE,
    extract_lines_easyocr,
    extract_text_easyocr,
    extract_text_easyocr_with_status,
)

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

# Module-private alias — canonical definition in shared.constants.
# docTR's DocumentFile.from_images raises ValueError for these containers.
_HEIC_EXTENSIONS = HEIC_HEIF_EXTENSIONS

# Image preprocessing (dark-background inversion + CLAHE) needs PIL + numpy;
# CLAHE additionally needs OpenCV. Each is optional and degrades gracefully.
_PREPROCESS_AVAILABLE = False
try:
    import numpy as np
    from PIL import Image, ImageOps

    _PREPROCESS_AVAILABLE = True
except ImportError:
    pass

_CV2_AVAILABLE = False
try:
    import cv2

    _CV2_AVAILABLE = True
except ImportError:
    pass

# Mean luminance (0–255) below which an image is treated as dark-background and
# inverted before OCR (light-on-dark text → dark-on-light, which docTR reads far
# better). Calibrated for terminal/IDE/dashboard screenshots.
_DARK_BACKGROUND_LUMINANCE_THRESHOLD = 100.0
# Luminance is sampled from a downscaled thumbnail for speed.
_LUMINANCE_THUMBNAIL_SIZE = 64
# When the first OCR pass renders fewer than this many characters, retry once
# with CLAHE contrast enhancement (helps low-contrast dark UI screenshots).
_CLAHE_RETRY_MIN_CHARS = 30
_CLAHE_CLIP_LIMIT = 2.0
_CLAHE_TILE_GRID_SIZE = 8


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


# ---------------------------------------------------------------------------
# Image preprocessing for OCR (dark-background inversion + CLAHE)
# ---------------------------------------------------------------------------


def _load_rgb(image_path: Path):
    """Load an image as an EXIF-oriented RGB PIL image, or None on failure."""
    try:
        img = Image.open(image_path)
        oriented = ImageOps.exif_transpose(img)
        return oriented.convert("RGB")
    except Exception:
        return None


def _mean_luminance(img) -> float:
    """Mean perceptual luminance (0–255) sampled from a downscaled thumbnail."""
    gray = img.convert("L")
    gray.thumbnail((_LUMINANCE_THUMBNAIL_SIZE, _LUMINANCE_THUMBNAIL_SIZE))
    return float(np.asarray(gray).mean())


def is_dark_background(image_path: Path) -> bool:
    """True when the image's mean luminance is below the dark-background threshold."""
    if not _PREPROCESS_AVAILABLE:
        return False
    img = _load_rgb(image_path)
    if img is None:
        return False
    return _mean_luminance(img) < _DARK_BACKGROUND_LUMINANCE_THRESHOLD


def _apply_clahe(rgb):
    """Apply CLAHE contrast enhancement on the L channel of an RGB uint8 array."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=_CLAHE_CLIP_LIMIT,
        tileGridSize=(_CLAHE_TILE_GRID_SIZE, _CLAHE_TILE_GRID_SIZE),
    )
    l_chan = clahe.apply(l_chan)
    merged = cv2.merge((l_chan, a_chan, b_chan))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)


def preprocess_for_ocr(image_path: Path, *, enhance: bool = False):
    """Return a preprocessed RGB numpy page for OCR, or None when no preprocessing
    applies (or libraries are unavailable), in which case the caller should feed
    docTR the original file path unchanged.

    - Dark-background images (mean luminance below the threshold) are inverted so
      light-on-dark text becomes dark-on-light.
    - ``enhance=True`` additionally applies CLAHE contrast enhancement (used as a
      retry when the first OCR pass yields little text).
    """
    if not _PREPROCESS_AVAILABLE:
        return None
    img = _load_rgb(image_path)
    if img is None:
        return None
    is_dark = _mean_luminance(img) < _DARK_BACKGROUND_LUMINANCE_THRESHOLD
    apply_clahe = enhance and _CV2_AVAILABLE
    if not is_dark and not apply_clahe:
        return None  # nothing to do; caller uses the original path
    if is_dark:
        img = ImageOps.invert(img)
    rgb = np.asarray(img)
    if apply_clahe:
        rgb = _apply_clahe(rgb)
    return rgb


def _run_image_ocr(image_path: Path):
    """Run docTR on an image with dark-background inversion and a CLAHE retry.

    The retry fires only when the first pass barely reads anything AND the image
    was dark (inverted) or partially read — so textless bright photos are not
    charged a second model pass. Returns the docTR result object, or None.

    HEIC/HEIF images that are not dark (i.e. preprocess_for_ocr returns None)
    are decoded via PIL before reaching DocumentFile.from_images, which cannot
    parse those containers and would raise ValueError.
    """
    if not OCR_AVAILABLE:
        return None
    try:
        predictor = _get_predictor()
        page = preprocess_for_ocr(image_path, enhance=False)
        if page is None and _PREPROCESS_AVAILABLE and image_path.suffix.lower() in _HEIC_EXTENSIONS:
            # docTR's DocumentFile.from_images raises ValueError for HEIC/HEIF.
            # PIL (already HEIF-capable via pillow_heif) can decode the file;
            # pass a pixel array so docTR never touches the container path.
            heic_img = _load_rgb(image_path)
            if heic_img is not None:
                page = np.asarray(heic_img)
        doc = [page] if page is not None else DocumentFile.from_images([str(image_path)])
        result = predictor(doc)
        chars = len(result.render().strip())
        if chars < _CLAHE_RETRY_MIN_CHARS and (page is not None or chars > 0):
            enhanced = preprocess_for_ocr(image_path, enhance=True)
            if enhanced is not None:
                alt = predictor([enhanced])
                if len(alt.render().strip()) > chars:
                    result = alt
        return result
    except Exception as e:
        print(f"  OCR error: {type(e).__name__}: {e}")
        return None


def extract_ocr_text(
    image_path: Path,
    max_chars: int = 500,
    config: str = "",  # kept for API compatibility
    timeout: int = 10,  # kept for API compatibility
) -> str | None:
    """Extract text from image using docTR OCR.

    Returns None if OCR unavailable or no text found.
    """
    result = _run_image_ocr(image_path)
    if result is None:
        return None
    text = " ".join(result.render().split())
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text if text.strip() else None


def extract_screenshot_text(image_path: Path, max_chars: int = 500) -> str | None:
    """Extract OCR text from a screenshot or mobile capture.

    Prefers easyocr (more accurate on screenshots and mobile UI text) when it is
    installed, falling back to the docTR pipeline. Document and PDF OCR continue
    to use docTR directly via extract_ocr_text / extract_ocr_text_pdf.

    Returns None if no backend produces text.
    """
    if EASYOCR_AVAILABLE:
        text = extract_text_easyocr(image_path, max_chars=max_chars)
        if text:
            return text
    return extract_ocr_text(image_path, max_chars=max_chars)


def extract_screenshot_lines(image_path: Path, max_lines: int = 20) -> list[str] | None:
    """Extract OCR text as reading-order lines, preserving line structure.

    Backend preference mirrors extract_screenshot_text (easyocr first, docTR
    fallback); used for title-snippet naming. extract_screenshot_text's
    flattened output is intentionally untouched — digit detection and keyword
    classification depend on it.

    Returns None if no backend produces text.
    """
    if EASYOCR_AVAILABLE:
        lines = extract_lines_easyocr(image_path, max_lines=max_lines)
        if lines:
            return lines
    result = _run_image_ocr(image_path)
    if result is None:
        return None
    lines = [" ".join(line.split()) for line in result.render().split("\n")]
    lines = [line for line in lines if line]
    return lines[:max_lines] or None


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
    prefer_easyocr: bool = True,
    force_doctr_fallback: bool = False,
) -> OCRResult | None:
    """Extract text with confidence scores, language, and orientation.

    When ``prefer_easyocr`` is True (the default) and easyocr is installed, the
    easyocr detail=1 path is tried first because it is more accurate on
    screenshots and mobile UI captures. Falls back to docTR if easyocr returns
    nothing. Set ``prefer_easyocr=False`` to force the docTR path (e.g. for
    scanned documents where docTR is the stronger backend).

    ``force_doctr_fallback`` disables the clean-negative gate below: docTR runs
    even when easyocr cleanly found no text, recovering very-low-contrast text
    that easyocr's detector misses (eval: 1/7 such images) at ~25x the cost.

    Returns None if OCR unavailable or no text found.
    Use max_chars=0 for no truncation.
    """
    if prefer_easyocr and EASYOCR_AVAILABLE:
        easyocr_result, easyocr_errored = extract_text_easyocr_with_status(
            image_path, max_chars=max_chars
        )
        if easyocr_result is not None:
            return easyocr_result
        # easyocr ran cleanly and found no text: the image is (almost certainly)
        # text-free, and a full docTR pass would repeat the same negative at
        # ~25x the cost. Skip it. Fall back to docTR only when easyocr actually
        # errored (its detector never produced a verdict) or the caller forced
        # the fallback (faint-text recall over cost).
        if not easyocr_errored and not force_doctr_fallback:
            return None

    result = _run_image_ocr(image_path)
    if result is None:
        return None
    text = " ".join(result.render().split())
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
    # IDE / code editor screenshots — keyed "code" to match the
    # Media/Photos/Screenshots/CodeEditors folder mapping. Tokens are language
    # syntax (kept distinct from terminal shell commands above).
    "code": [
        "import ",
        "function ",
        "class ",
        "def ",
        "const ",
        "return ",
        "public ",
        "private ",
        "void ",
        "#include",
        "console.log",
        "print(",
        "var ",
        "let ",
        "async ",
        "await ",
        "=>",
    ],
    # Web browser screenshots — keyed "browser" to match the
    # Media/Photos/Screenshots/Browser folder mapping.
    "browser": [
        "http://",
        "https://",
        "www.",
        ".com",
        ".org",
        ".net",
        "search",
        "bookmarks",
        "address bar",
        "new tab",
        "incognito",
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
    *,
    text: str | None = None,
) -> tuple[str, float, dict[str, float], str] | None:
    """Classify image by OCR text extraction with fallback hierarchy.

    Tries screenshot-specific keywords first, then falls back to Schema.org
    taxonomy if available.

    Args:
      image_path: Path to the image file
      content_classifier: Optional ContentClassifier for schema.org taxonomy
      max_chars: Max characters to extract via OCR
      text: Pre-extracted OCR text. When provided (including an empty string,
        meaning "OCR ran and found nothing"), classification runs on it directly
        and no extraction happens — lets callers that already OCR'd the image
        (e.g. the unified ScreenshotOcrSignal via ctx.ensure_ocr) skip a second
        pass. When None, text is extracted here as before.

    Returns:
      Tuple of (category, confidence, all_scores, extracted_text) or None
      if OCR unavailable or no matches found.
      all_scores maps every matched category to its confidence.
    """
    if text is None:
        if not is_ocr_available() and not EASYOCR_AVAILABLE:
            return None
        text = extract_screenshot_text(image_path, max_chars=max_chars)
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
        best_ss = max(screenshot_scores, key=lambda k: screenshot_scores[k])
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
