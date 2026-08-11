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
is correct and stable; the only workaround applied is cosmetic (the
``_quiet_readtext`` funnel suppresses torch's per-call pin_memory-on-MPS
warning).

For latency-sensitive batch runs, consider:
  - Pre-warming the Reader before the per-file loop (see batch_processor).
  - Using the CLIP embedding cache pattern to skip re-OCR of unchanged images.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from shared.constants import EASYOCR_DEFAULT_LANGUAGE

if TYPE_CHECKING:
    # Runtime import lives inside the functions to avoid a circular import
    # (ocr_classifier imports this module); this is annotations-only.
    from shared.ocr_classifier import OCRResult

logger = logging.getLogger(__name__)

# Detect availability without importing the heavy module at load time.
EASYOCR_AVAILABLE = importlib.util.find_spec("easyocr") is not None

# HEIC/HEIF support — registered here so _readtext_input's PIL decode path
# works even when this module is used standalone (without ocr_classifier).
# Per-module registration is the established pattern in this codebase; a
# module that opens images must call this itself, not rely on import order.
try:
    from pillow_heif import register_heif_opener as _register_heif_easyocr

    _register_heif_easyocr()
except ImportError:
    pass

# Container formats that cv2.imread cannot read — easyocr's CRAFT detector
# calls cv2.imread internally and returns None for these, crashing with
# 'NoneType has no attribute shape'. PIL (already HEIF-capable) can decode
# them; _readtext_input passes pixel arrays for these extensions.
_HEIC_EXTENSIONS = frozenset({".heic", ".heif"})


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

# torch deprecation fired by easyocr's quantized dynamic LSTM at Reader
# construction (pytorch/pytorch#184982): quint8 tensor creation is deprecated,
# but easyocr's quantize=True default depends on it and remains the fastest
# CPU inference path (the content pipeline is OCR-bound — do not trade it for
# a clean log). Suppressed at the single construction site below rather than
# globally, so other torch callers' quantization warnings still surface.
# Matched against the message START (warnings.filterwarnings semantics).
# Revisit when torch actually removes the API: easyocr will then need
# quantize=False (or an upstream fix) and this filter becomes dead.
_TORCH_QUANTIZE_DEPRECATION_MSG = (
    r"torch\.quantize_per_tensor, torch\.quantize_per_channel and other "
    r"quantized tensor creation functions"
)

# torch UserWarning fired on every readtext call on Apple Silicon: easyocr's
# recognizer builds a DataLoader(pin_memory=True) per call, and torch warns
# that MPS cannot pin memory before ignoring the flag. Purely environmental —
# no caller can act on it (easyocr owns the DataLoader) — so it is suppressed
# in the _quiet_readtext funnel below. NOT docTR: probed 2026-07-18, docTR's
# predictor emits no pin_memory warning on this stack.
_TORCH_PIN_MEMORY_MPS_MSG = r"'pin_memory' argument is set as true but not supported on MPS"


def _quiet_readtext(reader, image, **kwargs):
    """``reader.readtext`` with the per-call MPS pin_memory warning suppressed.

    Scoped to the single call so genuinely new easyocr/torch warnings still
    surface; every production readtext goes through this funnel.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_TORCH_PIN_MEMORY_MPS_MSG,
            category=UserWarning,
        )
        return reader.readtext(image, **kwargs)


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
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=_TORCH_QUANTIZE_DEPRECATION_MSG,
                        category=UserWarning,
                    )
                    _reader = easyocr.Reader(_resolve_languages(), gpu=gpu, verbose=False)
    return _reader


def prewarm_reader() -> None:
    """Eagerly build the singleton easyocr Reader to amortize first-call latency.

    The Reader's multi-second model load otherwise happens lazily on the first
    screenshot mid-batch. Call this before a per-file loop (see BatchProcessor)
    so the cost is paid up front. No-op if easyocr is unavailable or the Reader
    is already loaded; thread-safe via _get_reader's double-checked locking.
    """
    if not EASYOCR_AVAILABLE:
        return
    _get_reader()


def clear_reader() -> None:
    """Release the cached easyocr Reader and free its memory.

    Mirrors CLIPClassifier.clear_cache(). Useful in tests and long-running
    processes that want to reclaim the Reader's model weights between batches.
    """
    global _reader
    with _lock:
        _reader = None
    logger.info("easyocr Reader cache cleared")


def _readtext_input(image_path: Path):
    """Return the value to pass to Reader.readtext for this image.

    easyocr's reformat_input loads animated images (multi-frame GIF/WebP) as a
    4-D (frames, H, W, 3) stack, which its detection pipeline then converts to
    float — multi-GB for long animations, enough to OOM-kill the process. For
    animated images, decode only the first frame and pass it as an RGB array
    (readtext accepts ndarray input); otherwise pass the path through unchanged.

    HEIC/HEIF files are also decoded to an array: cv2.imread (called internally
    by easyocr's CRAFT detector) returns None for these containers, causing
    'NoneType has no attribute shape'. PIL already decoded the file during this
    check, so the array is free to produce here.
    """
    try:
        from PIL import Image
        import numpy as np

        with Image.open(image_path) as img:
            if getattr(img, "n_frames", 1) > 1:
                img.seek(0)
                return np.asarray(img.convert("RGB"))
            # HEIC/HEIF: cv2.imread can't open these containers.  PIL already
            # has the decoded image from the animated-frame check above — pass
            # pixels so easyocr never sees the path.
            if image_path.suffix.lower() in _HEIC_EXTENSIONS:
                return np.asarray(img.convert("RGB"))
    except Exception as e:
        logger.debug("animated-image check failed on %s: %s", image_path, e)
    return str(image_path)


def extract_text_easyocr(image_path: Path, max_chars: int = 500) -> str | None:
    """Extract text from a screenshot/mobile image via easyocr.

    Returns None if easyocr is unavailable, the image cannot be read, or no text
    is found.
    """
    if not EASYOCR_AVAILABLE:
        return None
    try:
        reader = _get_reader()
        lines = _quiet_readtext(reader, _readtext_input(image_path), detail=0, paragraph=True)
        text = " ".join(" ".join(lines).split())
        if not text.strip():
            return None
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text
    except Exception as e:
        logger.warning("easyocr failed on %s: %s", image_path, e)
        return None


def extract_lines_easyocr(image_path: Path, max_lines: int = 20) -> list[str] | None:
    """Extract text as reading-order lines (paragraph-grouped) via easyocr.

    Unlike extract_text_easyocr, line structure is preserved — used for
    title-snippet naming. Returns None if easyocr is unavailable, the image
    cannot be read, or no text is found.
    """
    if not EASYOCR_AVAILABLE:
        return None
    try:
        reader = _get_reader()
        raw = _quiet_readtext(reader, _readtext_input(image_path), detail=0, paragraph=True)
        lines = [" ".join(segment.split()) for segment in raw]
        lines = [line for line in lines if line]
        return lines[:max_lines] or None
    except Exception as e:
        logger.warning("easyocr failed on %s: %s", image_path, e)
        return None


def extract_text_easyocr_with_status(
    image_path: Path,
    max_chars: int = 0,
) -> "tuple[OCRResult | None, bool]":
    """easyocr detail=1 extraction, reporting whether it errored.

    Returns ``(result, errored)``: ``result`` is an ``OCRResult`` or ``None``
    (unavailable / no text found), and ``errored`` is True *only* when easyocr
    raised — distinct from cleanly finding no text (``(None, False)``). Callers
    use ``errored`` to fall back to docTR only on a genuine easyocr failure, not
    on a text-free image (where a full docTR pass would just re-confirm the same
    negative at far higher cost). Use max_chars=0 for no truncation.
    """
    if not EASYOCR_AVAILABLE:
        return None, False
    try:
        from shared.ocr_classifier import OCRResult

        reader = _get_reader()
        detections = _quiet_readtext(reader, _readtext_input(image_path), detail=1, paragraph=False)
        if not detections:
            return None, False

        words: list[str] = []
        confidences: list[float] = []
        for _bbox, word_text, conf in detections:
            cleaned = word_text.strip()
            if cleaned:
                words.append(cleaned)
                confidences.append(float(conf))

        if not words:
            return None, False

        text = " ".join(" ".join(words).split())
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "..."

        avg_confidence = sum(confidences) / len(confidences)
        return (
            OCRResult(
                text=text,
                confidence=avg_confidence,
                language=None,
                word_count=len(words),
                orientation=None,
            ),
            False,
        )
    except Exception as e:
        logger.warning("easyocr (detail=1) failed on %s: %s", image_path, e)
        return None, True


def extract_text_easyocr_with_confidence(
    image_path: Path,
    max_chars: int = 0,
) -> "OCRResult | None":
    """Extract text with per-box confidence from a screenshot via easyocr.

    Thin wrapper over :func:`extract_text_easyocr_with_status` that drops the
    error flag. Returns None if easyocr is unavailable, the image cannot be
    read, or no text is found. Use max_chars=0 for no truncation.
    """
    return extract_text_easyocr_with_status(image_path, max_chars=max_chars)[0]
