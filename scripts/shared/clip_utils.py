"""CLIP model loading and classification utilities."""
from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from shared.constants import CLIP_BATCH_SIZE

logger = logging.getLogger(__name__)

CLIP_AVAILABLE = False
try:
  import torch
  import torch.nn.functional as F
  from sentence_transformers import SentenceTransformer
  from PIL import Image
  CLIP_AVAILABLE = True
except ImportError:
  pass

# HEIC support
try:
  from pillow_heif import register_heif_opener
  register_heif_opener()
except ImportError:
  pass

# Module-level singleton cache: device string → CLIPClassifier instance.
_instances: Dict[str, "CLIPClassifier"] = {}
_lock = threading.Lock()


def get_clip_classifier(device: Optional[str] = None) -> "CLIPClassifier":
  """Return a cached CLIPClassifier, loading the model once per device."""
  return CLIPClassifier.get_instance(device)


class CLIPClassifier:
  """Shared CLIP model loader and classifier backed by sentence-transformers.

  Uses SentenceTransformer('clip-ViT-B-32') — same weights as
  openai/clip-vit-base-patch32, with built-in batching via DataLoader.

  Use CLIPClassifier.get_instance() (or get_clip_classifier()) instead of
  CLIPClassifier() directly to share the loaded model across callers.
  """

  MODEL_NAME = "clip-ViT-B-32"

  def __init__(self, device: str | None = None):
    if not CLIP_AVAILABLE:
      raise RuntimeError(
        "CLIP not available. Install sentence-transformers and torch."
      )
    self.device = device or self._detect_device()
    logger.info("Loading CLIP model %s", self.MODEL_NAME)
    self.model = SentenceTransformer(self.MODEL_NAME, device=self.device)
    self.model.eval()
    logger.info("CLIP model loaded (device: %s)", self.device)

  @classmethod
  def get_instance(cls, device: Optional[str] = None) -> "CLIPClassifier":
    """Return a cached instance, creating it on first call per device.

    Thread-safe: concurrent callers block until the first load completes
    rather than each paying the full load cost.
    """
    resolved_device = device or cls._detect_device()
    if resolved_device not in _instances:
      with _lock:
        # Double-checked locking: re-test inside the lock.
        if resolved_device not in _instances:
          logger.info("Creating CLIPClassifier singleton (device: %s)", resolved_device)
          _instances[resolved_device] = cls(device=resolved_device)
    return _instances[resolved_device]

  @classmethod
  def clear_cache(cls) -> None:
    """Release all cached model instances and free GPU/MPS memory."""
    with _lock:
      for instance in _instances.values():
        if CLIP_AVAILABLE and hasattr(instance, "model"):
          try:
            del instance.model
            if torch.cuda.is_available():
              torch.cuda.empty_cache()
          except Exception:
            pass
      _instances.clear()
    logger.info("CLIPClassifier cache cleared")

  @staticmethod
  def _detect_device() -> str:
    if not CLIP_AVAILABLE:
      return "cpu"
    if torch.backends.mps.is_available():
      return "mps"
    if torch.cuda.is_available():
      return "cuda"
    return "cpu"

  @staticmethod
  def is_available() -> bool:
    return CLIP_AVAILABLE

  def _encode_image(self, image_path: Path) -> "torch.Tensor":
    with Image.open(image_path) as img:
      image = img.convert("RGB")
    return self.model.encode(image, convert_to_tensor=True)

  def _similarities(
    self,
    img_emb: "torch.Tensor",
    text_prompts: list[str],
  ) -> "torch.Tensor":
    """Return softmax probabilities over text_prompts for a single image embedding."""
    txt_emb = self.model.encode(text_prompts, convert_to_tensor=True)
    # img_emb: [D], txt_emb: [N, D]
    sims = F.cosine_similarity(img_emb.unsqueeze(0), txt_emb)  # [N]
    return sims.softmax(dim=0)

  def classify(
    self,
    image_path: Path,
    labels: list[str],
    prompt_prefix: str = "a photo of ",
  ) -> list[tuple[str, float]]:
    """Classify image against labels.

    Returns list of (label, confidence) sorted by confidence descending.
    """
    text_prompts = [f"{prompt_prefix}{lbl}" for lbl in labels]
    img_emb = self._encode_image(image_path)
    probs = self._similarities(img_emb, text_prompts)
    results = [(labels[i], probs[i].item()) for i in range(len(labels))]
    results.sort(key=lambda x: x[1], reverse=True)
    return results

  def classify_raw(
    self,
    image_path: Path,
    text_prompts: list[str],
  ) -> list[tuple[str, float]]:
    """Classify image using raw text prompts (no prefix added).

    Returns list of (prompt, confidence) sorted by confidence descending.
    """
    img_emb = self._encode_image(image_path)
    probs = self._similarities(img_emb, text_prompts)
    results = [(text_prompts[i], probs[i].item()) for i in range(len(text_prompts))]
    results.sort(key=lambda x: x[1], reverse=True)
    return results

  def top_match(
    self,
    image_path: Path,
    labels: list[str],
    prompt_prefix: str = "a photo of ",
  ) -> tuple[str, float]:
    """Return single best match (label, confidence)."""
    results = self.classify(image_path, labels, prompt_prefix)
    return results[0] if results else ("unknown", 0.0)

  # --- Batch inference — sentence-transformers handles DataLoader internally ---

  _FALLBACK_CONFIDENCE = 0.0
  _DEFAULT_BATCH_SIZE = CLIP_BATCH_SIZE

  def classify_batch(
    self,
    image_paths: List[Path],
    labels: list[str],
    prompt_prefix: str = "a photo of ",
    batch_size: int = _DEFAULT_BATCH_SIZE,
  ) -> List[List[tuple[str, float]]]:
    """Classify a list of images against the same labels in batched forward passes.

    sentence-transformers uses DataLoader with num_workers internally.
    Returns one result list per input image, sorted by confidence descending.
    Images that fail to load return [(label, 0.0), ...].
    """
    text_prompts = [f"{prompt_prefix}{lbl}" for lbl in labels]
    return self._run_batch(image_paths, labels, text_prompts, batch_size)

  def classify_raw_batch(
    self,
    image_paths: List[Path],
    text_prompts: list[str],
    batch_size: int = _DEFAULT_BATCH_SIZE,
  ) -> List[List[tuple[str, float]]]:
    """Classify a list of images using raw text prompts (no prefix added)."""
    return self._run_batch(image_paths, text_prompts, text_prompts, batch_size)

  def top_match_batch(
    self,
    image_paths: List[Path],
    labels: list[str],
    prompt_prefix: str = "a photo of ",
    batch_size: int = _DEFAULT_BATCH_SIZE,
  ) -> List[tuple[str, float]]:
    """Return the best (label, confidence) for each image in a batched call."""
    all_results = self.classify_batch(image_paths, labels, prompt_prefix, batch_size)
    return [res[0] if res else ("unknown", self._FALLBACK_CONFIDENCE) for res in all_results]

  def _run_batch(
    self,
    image_paths: List[Path],
    result_keys: list[str],
    text_prompts: list[str],
    batch_size: int,
  ) -> List[List[tuple[str, float]]]:
    """Shared implementation for classify_batch and classify_raw_batch.

    Text is encoded once; images are loaded and encoded in mini-batches.
    sentence-transformers handles DataLoader parallelism internally.
    """
    fallback = [(key, self._FALLBACK_CONFIDENCE) for key in result_keys]
    output: List[List[tuple[str, float]]] = []

    # Encode text once — same for every image in this call.
    txt_emb = self.model.encode(text_prompts, convert_to_tensor=True)  # [N, D]
    txt_norm = F.normalize(txt_emb, dim=-1)

    for chunk_start in range(0, len(image_paths), batch_size):
      chunk = image_paths[chunk_start : chunk_start + batch_size]
      images: list = []
      valid_idx: list[int] = []

      for i, path in enumerate(chunk):
        try:
          with Image.open(path) as img:
            images.append(img.convert("RGB"))
          valid_idx.append(i)
        except Exception:
          logger.warning("CLIP batch: failed to open %s", path)

      chunk_results: List[List[tuple[str, float]]] = [list(fallback) for _ in chunk]

      if images:
        img_emb = self.model.encode(images, batch_size=batch_size, convert_to_tensor=True)
        img_norm = F.normalize(img_emb, dim=-1)
        sims = img_norm @ txt_norm.T      # [num_valid, N]
        probs = sims.softmax(dim=-1)

        for out_pos, chunk_pos in enumerate(valid_idx):
          row = [(result_keys[j], probs[out_pos][j].item()) for j in range(len(result_keys))]
          row.sort(key=lambda x: x[1], reverse=True)
          chunk_results[chunk_pos] = row

      output.extend(chunk_results)

    return output
