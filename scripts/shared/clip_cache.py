"""CLIP inference cache backed by pickle files.

Caches classify() results by SHA-256 of image content so duplicate files
skip model inference entirely. Cache is stored in .cache/clip_embeddings/.
Supports a probe-without-execute pattern for batch inference.
"""
from __future__ import annotations
import hashlib
import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

CLIP_CACHE_AVAILABLE = True

_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "clip_embeddings"


def _sha256(path: Path) -> str:
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
      h.update(chunk)
  return h.hexdigest()


def _cache_key(content_hash: str, labels: list[str], prompt_prefix: str) -> str:
  labels_str = "|".join(sorted(labels)) + "|" + prompt_prefix
  return content_hash + "_" + hashlib.sha256(labels_str.encode()).hexdigest()[:12]


def _cache_path(key: str) -> Path:
  return _CACHE_DIR / key[:2] / f"{key}.pkl"


def _load(path: Path) -> list | None:
  try:
    with open(path, "rb") as f:
      return pickle.load(f)
  except Exception:
    return None


def _save(path: Path, result: list) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with open(path, "wb") as f:
    pickle.dump(result, f)


def get_cached_embedding(
  image_path: Path,
  labels: list[str],
  prompt_prefix: str = "a photo of ",
) -> list[tuple[str, float]]:
  """Return classify() results, served from disk cache when possible.

  Cache key: SHA-256 of image file content + labels + prompt_prefix.
  """
  from shared.clip_utils import get_clip_classifier
  key = _cache_key(_sha256(image_path), labels, prompt_prefix)
  cached = _load(_cache_path(key))
  if cached is not None:
    return cached
  result = get_clip_classifier().classify(image_path, labels, prompt_prefix)
  _save(_cache_path(key), result)
  return result


def get_cached_embeddings_batch(
  image_paths: list[Path],
  labels: list[str],
  prompt_prefix: str = "a photo of ",
) -> list[list[tuple[str, float]]]:
  """Return classify() results for a batch of images, using cache for hits.

  Cache misses are collected and dispatched together via classify_batch()
  to amortize model-load cost across the batch.
  """
  from shared.clip_utils import get_clip_classifier
  hashes = [_sha256(p) for p in image_paths]
  keys = [_cache_key(h, labels, prompt_prefix) for h in hashes]

  output: dict[int, list] = {}
  miss_indices: list[int] = []
  miss_paths: list[Path] = []

  for i, key in enumerate(keys):
    cached = _load(_cache_path(key))
    if cached is not None:
      output[i] = cached
    else:
      miss_indices.append(i)
      miss_paths.append(image_paths[i])

  if miss_paths:
    classifier = get_clip_classifier()
    batch_results = classifier.classify_batch(miss_paths, labels, prompt_prefix)
    for i, result in zip(miss_indices, batch_results):
      _save(_cache_path(keys[i]), result)
      output[i] = result

  return [output[i] for i in range(len(image_paths))]
