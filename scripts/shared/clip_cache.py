"""CLIP image-embedding cache.

Caches normalised [D] image embeddings keyed by file identity (mtime + size + name).
Different label sets reuse the same cached embedding — only a cheap dot-product +
softmax is repeated, not the full image encode.

Cache layout: .cache/clip_embeddings_v2/{aa}/{hash}.npy (fp32 numpy arrays).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    import xxhash

    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False

logger = logging.getLogger(__name__)

CLIP_CACHE_AVAILABLE = _HAS_NUMPY

_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "clip_embeddings_v2"


def _file_identity(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.name}_{stat.st_mtime}_{stat.st_size}"
    if _HAS_XXHASH:
        return xxhash.xxh64(raw.encode()).hexdigest()
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / key[:2] / f"{key}.npy"


def _load_embedding(path: Path):
    try:
        return np.load(path)
    except Exception:
        return None


def _save_embedding(path: Path, emb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, emb)


def get_or_compute_embedding(image_path: Path):
    """Return the cached [D] fp32 image embedding, encoding + caching on miss.

    Single-homed embedding accessor shared by the interior-probe prototype and
    the runtime ``InteriorSignal``. Returns ``None`` when numpy/CLIP is
    unavailable or the image cannot be encoded, so callers degrade to a no-op.
    """
    if not CLIP_CACHE_AVAILABLE:
        return None
    try:
        # _file_identity stats the file — a missing/unreadable path (e.g. a
        # synthetic test context) must no-op, not raise.
        cpath = _cache_path(_file_identity(image_path))
    except Exception:
        return None
    emb = _load_embedding(cpath)
    if emb is not None:
        return emb
    try:
        from shared.clip_utils import get_clip_classifier

        emb = get_clip_classifier().encode_image_to_numpy(image_path)
    except Exception:
        return None
    _save_embedding(cpath, emb)
    return emb


def store_embedding(image_path: Path, image_emb) -> None:
    """Persist a precomputed [D] embedding to the disk cache if not already present.

    Lets a call site that has already encoded an image (e.g. the rename pre-step)
    seed the cache so later label-set scorings reuse the embedding instead of
    re-encoding. The array must be the same fp32 representation produced by
    CLIPClassifier.encode_image_to_numpy so cached and freshly-encoded results
    are byte-identical.
    """
    if not CLIP_CACHE_AVAILABLE:
        return
    cpath = _cache_path(_file_identity(image_path))
    if cpath.exists():
        return
    _save_embedding(cpath, np.asarray(image_emb))


def get_cached_embedding(
    image_path: Path,
    labels: list[str],
    prompt_prefix: str = "a photo of ",
) -> list[tuple[str, float]]:
    """Return classify() results, scoring a cached image embedding against labels."""
    from shared.clip_utils import get_clip_classifier

    classifier = get_clip_classifier()

    key = _file_identity(image_path)
    cpath = _cache_path(key)
    emb = _load_embedding(cpath)
    if emb is None:
        emb = classifier.encode_image_to_numpy(image_path)
        _save_embedding(cpath, emb)
    return classifier.score_embedding(emb, labels, prompt_prefix)


def get_cached_embeddings_batch(
    image_paths: list[Path],
    labels: list[str],
    prompt_prefix: str = "a photo of ",
) -> list[list[tuple[str, float]]]:
    """Batch variant. Encodes cache misses in a single batched forward pass,
    then scores every image against labels in-memory.
    """
    from shared.clip_utils import get_clip_classifier

    classifier = get_clip_classifier()

    keys = [_file_identity(p) for p in image_paths]
    paths = [_cache_path(k) for k in keys]

    embeddings: dict[int, "np.ndarray"] = {}
    miss_indices: list[int] = []
    miss_paths: list[Path] = []

    for i, cpath in enumerate(paths):
        emb = _load_embedding(cpath)
        if emb is not None:
            embeddings[i] = emb
        else:
            miss_indices.append(i)
            miss_paths.append(image_paths[i])

    if miss_paths:
        encoded = classifier.encode_images_to_numpy(miss_paths)
        for local_idx, emb in encoded:
            orig_idx = miss_indices[local_idx]
            embeddings[orig_idx] = emb
            _save_embedding(paths[orig_idx], emb)

    fallback = [(lbl, 0.0) for lbl in labels]
    output: list[list[tuple[str, float]]] = []
    for i in range(len(image_paths)):
        emb = embeddings.get(i)
        if emb is None:
            output.append(list(fallback))
        else:
            output.append(classifier.score_embedding(emb, labels, prompt_prefix))
    return output
