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
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Detect availability without importing the heavy module at load time.
EASYOCR_AVAILABLE = importlib.util.find_spec("easyocr") is not None

# Languages passed to easyocr.Reader. English-only keeps the model small/fast.
# Override via OCR_EASYOCR_LANGS env var (comma-separated ISO codes, e.g. "en,es").
# Adding languages increases model load time and memory usage.
_EASYOCR_LANGUAGES = ["en"]

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
                _reader = easyocr.Reader(_EASYOCR_LANGUAGES, gpu=gpu, verbose=False)
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
