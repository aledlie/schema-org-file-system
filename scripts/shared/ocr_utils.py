"""Shared OCR text extraction using docTR."""
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

_DET_ARCH = 'fast_base'          # default since docTR v0.9, faster than db_resnet50
_RECO_ARCH = 'crnn_vgg16_bn'     # reliable baseline recognition


def _get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = ocr_predictor(
            det_arch=_DET_ARCH,
            reco_arch=_RECO_ARCH,
            pretrained=True,
            assume_straight_pages=False,   # support rotated/skewed scans
            straighten_pages=True,         # auto-correct page rotation
            detect_orientation=True,       # classify page orientation (0/90/180/270)
            detect_language=True,          # per-page language detection
            resolve_blocks=True,           # group lines into blocks for reading order
            resolve_lines=True,            # group words into lines
        )
    return _predictor


# ---------------------------------------------------------------------------
# Rich result type
# ---------------------------------------------------------------------------

@dataclass
class OCRResult:
    """Rich OCR result with text, confidence, and metadata."""
    text: str
    confidence: float              # average word confidence (0.0–1.0)
    language: Optional[str]        # ISO 639-1 code or None
    word_count: int
    orientation: Optional[int]     # page rotation in degrees (0/90/180/270)


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
# Public API
# ---------------------------------------------------------------------------

def is_ocr_available() -> bool:
    return OCR_AVAILABLE


def extract_ocr_text(
    image_path: Path,
    max_chars: int = 500,
    config: str = "",         # kept for API compatibility
    timeout: int = 10,        # kept for API compatibility
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
        text = ' '.join(text.split())
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text if text.strip() else None
    except Exception:
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
        text = ' '.join(text.split())
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
        text = ' '.join(text.split())
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
        text = ' '.join(text.split())
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
