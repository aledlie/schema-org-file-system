"""easyocr backend for screenshot and mobile-capture OCR.

easyocr is more accurate than docTR on screenshots and mobile UI text, so the
screenshot classification path prefers it when installed. Document and PDF OCR
stay on docTR (see ocr_classifier). The heavy easyocr import is deferred until
first use, so the docTR-only path pays no import cost.

GPU/accelerator notes
---------------------
easyocr supports CUDA acceleration but has no usable MPS backend as of v1.7.
On Apple Silicon the Reader always runs on CPU regardless of whether MPS is
available. This is expected — easyocr's internal pin_memory calls are
incompatible with MPS and the library falls back automatically. The CPU path
is correct and stable; no workaround is applied.

For latency-sensitive batch runs, consider:
  - Pre-warming the Reader before the per-file loop (see batch_processor).
  - Using the CLIP embedding cache pattern to skip re-OCR of unchanged images.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from pathlib import Path

from shared.constants import EASYOCR_DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)

# Detect availability without importing the heavy module at load time.
EASYOCR_AVAILABLE = importlib.util.find_spec("easyocr") is not None


def _resolve_languages() -> list[str]:
    """Read OCR_EASYOCR_LANGS env var (comma-separated ISO codes) or return default.

    Resolved at Reader-construction time (not import time) so the env var can be
    set after this module is imported (e.g. in tests/notebooks). Adding languages
    increases model load time and memory — each downloads ~50–100 MB of weights.

    Examples:
      OCR_EASYOCR_LANGS=en,fr,es   → ["en", "fr", "es"]
      (unset)                       → ["en"]
    """
    raw = os.environ.get("OCR_EASYOCR_LANGS", "").strip()
    if raw:
        langs = [lang.strip() for lang in raw.split(",") if lang.strip()]
        if langs:
            logger.debug("easyocr: using languages from OCR_EASYOCR_LANGS: %s", langs)
            return langs
    return [EASYOCR_DEFAULT_LANGUAGE]


_reader = None
_lock = threading.Lock()


def _use_gpu() -> bool:
    """Return True only when CUDA is available.

    easyocr has no usable MPS backend (Apple Silicon). On MPS hosts the Reader
    must load with gpu=False — the library's pin_memory calls are not MPS-
    compatible and it falls back to CPU automatically, but passing gpu=True
    triggers confusing log noise. CUDA-only guard is intentional.
    """
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def _get_reader():
    """Lazily build the singleton easyocr Reader (one model load per process).

    Thread-safe via double-checked locking: concurrent callers block until the
    first load completes rather than each building a Reader. Mirrors
    CLIPClassifier.get_instance().
    """
    global _reader
    if _reader is None:
        with _lock:
            # Re-test inside the lock.
            if _reader is None:
                import easyocr

                gpu = _use_gpu()
                if not gpu:
                    try:
                        import torch

                        if torch.backends.mps.is_available():
                            logger.debug(
                                "easyocr: MPS detected but not supported — loading CPU Reader"
                            )
                    except Exception:
                        pass
                _reader = easyocr.Reader(
                    _resolve_languages(), gpu=gpu, verbose=False
                )
    return _reader


def clear_reader() -> None:
    """Release the cached easyocr Reader and free its memory.

    Mirrors CLIPClassifier.clear_cache(). Useful in tests and long-running
    processes that want to reclaim the Reader's model weights between batches.
    """
    global _reader
    with _lock:
        _reader = None
    logger.info("easyocr Reader cache cleared")


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


def extract_text_easyocr_with_confidence(
    image_path: Path,
    max_chars: int = 0,
) -> "OCRResult | None":
    """Extract text with per-box confidence from a screenshot via easyocr.

    Uses detail=1 to get (bbox, text, confidence) tuples. Aggregates confidence
    as the mean of per-word scores. Language and orientation are not reported by
    easyocr and are returned as None to match the OCRResult shape from docTR.

    Returns None if easyocr is unavailable, the image cannot be read, or no text
    is found. Use max_chars=0 for no truncation.
    """
    if not EASYOCR_AVAILABLE:
        return None
    try:
        from shared.ocr_classifier import OCRResult

        reader = _get_reader()
        detections = reader.readtext(str(image_path), detail=1, paragraph=False)
        if not detections:
            return None

        words: list[str] = []
        confidences: list[float] = []
        for _bbox, word_text, conf in detections:
            cleaned = word_text.strip()
            if cleaned:
                words.append(cleaned)
                confidences.append(float(conf))

        if not words:
            return None

        text = " ".join(" ".join(words).split())
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."

        avg_confidence = sum(confidences) / len(confidences)
        return OCRResult(
            text=text,
            confidence=avg_confidence,
            language=None,
            word_count=len(words),
            orientation=None,
        )
    except Exception as e:
        logger.warning("easyocr (detail=1) failed on %s: %s", image_path, e)
        return None
