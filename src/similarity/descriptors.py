"""SSCD copy-detection descriptors, with an on-disk cache.

Why not the CLIP embeddings already cached in ``.cache/clip_embeddings_v2``:
those are *semantic*. Two different event flyers sit close together in CLIP
space, so a CLIP-keyed duplicate report is dominated by false pairs. SSCD is
trained for "same image, re-encoded / resized / cropped", which is the question
near-duplicate detection actually asks.

The model is a standalone TorchScript checkpoint — ``torch.jit.load`` is the
entire integration, with no ``sscd-copy-detection`` package to install. It is
downloaded once into ``.cache/sscd_models`` on first use.

Every entry point degrades to a no-op (``None`` / empty) when torch,
torchvision or Pillow is unavailable, matching the optional-dependency
behaviour of the CLIP path.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence, Tuple, cast

from .constants import (
    DESCRIPTOR_CACHE_DIR,
    SSCD_BATCH_SIZE,
    SSCD_MODEL_DIR,
    SSCD_MODEL_NAME,
    SSCD_MODEL_URL,
    SSCD_NORMALIZE_MEAN,
    SSCD_NORMALIZE_STD,
    SSCD_RESIZE_SQUARE,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

try:
    import numpy as np  # noqa: F811

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    import xxhash

    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False

try:
    import torch
    from torchvision import transforms

    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# HEIC support. Required, not optional: IMAGE_EXTENSIONS advertises .heic/.heif,
# and without this Image.open silently fails on them — they would be dropped
# from the scan rather than reported as unreadable. Registered per-module, as
# elsewhere in this codebase (scripts/shared/clip_utils.py, image_metadata.py).
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

logger = logging.getLogger(__name__)

DESCRIPTORS_AVAILABLE = _HAS_NUMPY and _HAS_TORCH and _HAS_PIL

_model = None
_transform = None


# --------------------------------------------------------------------------- #
# Cache (mirrors scripts/shared/clip_cache.py's identity + sharding scheme)     #
# --------------------------------------------------------------------------- #


def _file_identity(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.name}_{stat.st_mtime}_{stat.st_size}"
    if _HAS_XXHASH:
        return str(xxhash.xxh64(raw.encode()).hexdigest())
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return DESCRIPTOR_CACHE_DIR / key[:2] / f"{key}.npy"


def _load_cached(path: Path) -> Optional["np.ndarray"]:
    try:
        # np.load is typed as returning Any (it can yield an NpzFile); this
        # cache only ever holds single .npy arrays written by _save_cached.
        return cast("np.ndarray", np.load(path))
    except Exception:
        return None


def _save_cached(path: Path, descriptor: "np.ndarray") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, descriptor)


# --------------------------------------------------------------------------- #
# Model                                                                        #
# --------------------------------------------------------------------------- #


def model_checkpoint_path() -> Path:
    """Local path the TorchScript checkpoint is cached at (may not exist yet)."""
    return SSCD_MODEL_DIR / f"{SSCD_MODEL_NAME}.torchscript.pt"


def ensure_model_downloaded(progress: bool = True) -> Optional[Path]:
    """Download the TorchScript checkpoint on first use; return its path.

    Returns ``None`` if the download fails, so callers degrade rather than
    raise. Writes to a ``.part`` file and renames on success, so an interrupted
    download can never leave a truncated checkpoint that ``torch.jit.load``
    would fail on confusingly later.
    """
    dest = model_checkpoint_path()
    if dest.exists():
        return dest

    try:
        import requests
    except ImportError:
        logger.warning("requests unavailable — cannot download the SSCD checkpoint")
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading SSCD checkpoint %s -> %s", SSCD_MODEL_URL, dest)
    try:
        with requests.get(SSCD_MODEL_URL, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            bar = None
            if progress:
                try:
                    from tqdm import tqdm

                    bar = tqdm(total=total, unit="B", unit_scale=True, desc=SSCD_MODEL_NAME)
                except ImportError:
                    bar = None
            with open(partial, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    handle.write(chunk)
                    if bar is not None:
                        bar.update(len(chunk))
            if bar is not None:
                bar.close()
        partial.rename(dest)
        return dest
    except Exception as exc:
        logger.warning("SSCD checkpoint download failed: %s", exc)
        partial.unlink(missing_ok=True)
        return None


def _get_model():
    """Load (once) the TorchScript model on CPU.

    CPU-only by design: this mirrors the easyocr situation — there is no usable
    MPS path for these ops on Apple Silicon, and the batch job is not latency
    critical.
    """
    global _model, _transform
    if not DESCRIPTORS_AVAILABLE:
        return None, None
    if _model is not None:
        return _model, _transform

    checkpoint = ensure_model_downloaded()
    if checkpoint is None:
        return None, None
    try:
        model = torch.jit.load(str(checkpoint), map_location="cpu")
        model.eval()
    except Exception as exc:
        logger.warning("Failed to load SSCD checkpoint %s: %s", checkpoint, exc)
        return None, None

    _model = model
    _transform = transforms.Compose(
        [
            transforms.Resize(list(SSCD_RESIZE_SQUARE)),
            transforms.ToTensor(),
            transforms.Normalize(mean=list(SSCD_NORMALIZE_MEAN), std=list(SSCD_NORMALIZE_STD)),
        ]
    )
    return _model, _transform


def clear_model() -> None:
    """Drop the loaded model to reclaim memory after a batch run."""
    global _model, _transform
    _model = None
    _transform = None


# --------------------------------------------------------------------------- #
# Encoding                                                                     #
# --------------------------------------------------------------------------- #


def _open_rgb(path: Path) -> Optional["Image.Image"]:
    """Open any supported input as RGB, rasterising PDFs' first page.

    Pillow's decompression-bomb guard raises inside ``load()`` for oversized
    images; the SSCD transform downscales to 320px anyway, so the guard is
    lifted for the open and restored immediately (same trade the CLIP
    thumbnail path makes — global mutation, single-threaded caller).
    """
    from .constants import PDF_EXTENSION, PDF_RASTER_DPI, PDF_RASTER_FIRST_PAGE

    if path.suffix.lower() == PDF_EXTENSION:
        try:
            from pdf2image import convert_from_path
        except ImportError:
            return None
        try:
            pages = convert_from_path(
                str(path),
                dpi=PDF_RASTER_DPI,
                first_page=PDF_RASTER_FIRST_PAGE,
                last_page=PDF_RASTER_FIRST_PAGE,
            )
        except Exception:
            return None
        return pages[0].convert("RGB") if pages else None

    previous_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None
        return Image.open(path).convert("RGB")
    except Exception:
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def encode_images(paths: Sequence[Path]) -> List[Tuple[int, "np.ndarray"]]:
    """Encode images to L2-normalised descriptors, batched.

    Returns ``(index_into_paths, descriptor)`` pairs, skipping anything that
    could not be opened or encoded — callers must not assume a 1:1 mapping.
    """
    # Check for work BEFORE touching the model: _get_model downloads a 94 MB
    # checkpoint on first use, and an empty batch must never trigger that.
    if not paths:
        return []
    model, transform = _get_model()
    if model is None:
        return []

    results: List[Tuple[int, "np.ndarray"]] = []
    for start in range(0, len(paths), SSCD_BATCH_SIZE):
        chunk = paths[start : start + SSCD_BATCH_SIZE]
        tensors = []
        indices = []
        for offset, path in enumerate(chunk):
            image = _open_rgb(path)
            if image is None:
                logger.debug("Unreadable, skipped: %s", path)
                continue
            try:
                tensors.append(transform(image))
            except Exception:
                logger.debug("Transform failed, skipped: %s", path)
                continue
            indices.append(start + offset)
        if not tensors:
            continue
        try:
            with torch.no_grad():
                batch = model(torch.stack(tensors))
        except Exception as exc:
            logger.warning("SSCD forward pass failed for a batch: %s", exc)
            continue
        array = batch.cpu().numpy().astype("float32")
        for row, original_index in enumerate(indices):
            results.append((original_index, array[row]))
    return results


def get_descriptors(paths: Iterable[Path]) -> List[Tuple[Path, "np.ndarray"]]:
    """Return ``(path, descriptor)`` for each input, using and filling the cache.

    Cache hits cost a small ``.npy`` read; misses are encoded in batches. Files
    that cannot be encoded are omitted from the result entirely.
    """
    if not DESCRIPTORS_AVAILABLE:
        return []

    ordered = list(paths)
    cached: dict[int, "np.ndarray"] = {}
    miss_indices: List[int] = []
    miss_paths: List[Path] = []
    cache_paths: dict[int, Path] = {}

    for index, path in enumerate(ordered):
        try:
            cache_path = _cache_path(_file_identity(path))
        except OSError:
            continue
        cache_paths[index] = cache_path
        descriptor = _load_cached(cache_path)
        if descriptor is not None:
            cached[index] = descriptor
        else:
            miss_indices.append(index)
            miss_paths.append(path)

    # Guarded: a fully-cached run must not load the model at all. encode_images
    # returns indices into miss_paths, which miss_indices maps back to the
    # caller's original positions.
    if miss_paths:
        for local_index, descriptor in encode_images(miss_paths):
            original_index = miss_indices[local_index]
            cached[original_index] = descriptor
            _save_cached(cache_paths[original_index], descriptor)

    return [(ordered[i], cached[i]) for i in sorted(cached)]
