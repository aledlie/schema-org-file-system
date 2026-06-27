"""easyocr backend for screenshot and mobile-capture OCR.

easyocr is more accurate than docTR on screenshots and mobile UI text, so the
screenshot classification path prefers it when installed. Document and PDF OCR
stay on docTR (see ocr_classifier). The heavy easyocr import is deferred until
first use, so the docTR-only path pays no import cost.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Detect availability without importing the heavy module at load time.
EASYOCR_AVAILABLE = importlib.util.find_spec("easyocr") is not None

# Languages passed to easyocr.Reader. English-only keeps the model small/fast.
_EASYOCR_LANGUAGES = ["en"]

_reader = None


def _use_gpu() -> bool:
    """easyocr accelerates on CUDA only; MPS/CPU fall back to CPU."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def _get_reader():
    """Lazily build the singleton easyocr Reader (one model load per process)."""
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(_EASYOCR_LANGUAGES, gpu=_use_gpu(), verbose=False)
    return _reader


def extract_text_easyocr(image_path: Path, max_chars: int = 500) -> str | None:
    """Extract text from a screenshot/mobile image via easyocr.

    Returns None if easyocr is unavailable, the image cannot be read, or no text
    is found.
    """
    if not EASYOCR_AVAILABLE:
        return None
    try:
        reader = _get_reader()
        lines = reader.readtext(str(image_path), detail=0, paragraph=True)
        text = " ".join(" ".join(lines).split())
        if not text.strip():
            return None
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text
    except Exception as e:
        logger.warning("easyocr failed on %s: %s", image_path, e)
        return None
