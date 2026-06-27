"""Unified CLIP image classification with refinement and naming."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from shared.clip_utils import get_clip_classifier, CLIP_AVAILABLE
from shared.ocr_classifier import apply_ocr_fallback as apply_ocr_fallback_logic

try:
  from shared.clip_cache import store_embedding, CLIP_CACHE_AVAILABLE
except ImportError:
  CLIP_CACHE_AVAILABLE = False
from shared.constants import (
    CLIP_REFINEMENT_MIN_CONFIDENCE,
    CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
)


class CLIPResult(NamedTuple):
  """Unified CLIP classification result."""
  category: str
  confidence: float
  all_scores: dict[str, float]


def refine_classification(
    classifier,
    image_emb,
    best_category: str,
    confidence: float,
    refinement_terms: dict[str, list[str]] | None = None,
    refinement_min_confidence: float = CLIP_REFINEMENT_MIN_CONFIDENCE,
    refinement_accept_confidence: float = CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
) -> tuple[str, float]:
  """Refine CLIP classification using more specific terms.

  Args:
    classifier: CLIPClassifier instance
    image_emb: Precomputed [D] image embedding (scored, never re-encoded)
    best_category: Initial CLIP classification result
    confidence: Initial CLIP confidence
    refinement_terms: Dict mapping categories to refinement term lists
    refinement_min_confidence: Min confidence to attempt refinement
    refinement_accept_confidence: Min confidence to accept refinement result

  Returns:
    Tuple of (refined_category, refined_confidence)
  """
  if not refinement_terms or best_category not in refinement_terms:
    return best_category, confidence

  if confidence <= refinement_min_confidence:
    return best_category, confidence

  refinements = refinement_terms[best_category]
  refined = classifier.score_embedding(image_emb, refinements, "a photo of ")
  refined_term, refined_confidence = refined[0] if refined else ("unknown", 0.0)

  if refined_confidence > refinement_accept_confidence:
    return refined_term, refined_confidence

  return best_category, confidence


def generate_filename(
    image_path: Path,
    content: str,
    metadata_parser=None,
) -> str:
  """Generate descriptive filename from content classification.

  Creates names like: YYYYMMDD_descriptive_content.ext or descriptive_content.ext

  Args:
    image_path: Path to image file
    content: CLIP classification result (category/description)
    metadata_parser: Optional ImageMetadataParser for datetime extraction

  Returns:
    New filename with extension
  """
  clean_content = re.sub(r'[^a-z0-9_]', '', content.lower().replace(" ", "_"))

  # Try to extract datetime from metadata or file mtime
  dt = None
  if metadata_parser:
    dt = metadata_parser.extract_datetime(image_path)

  if dt is None:
    try:
      dt = datetime.fromtimestamp(image_path.stat().st_mtime)
    except Exception:
      dt = None

  date_str = dt.strftime("%Y%m%d") if dt else None
  ext = image_path.suffix.lower()

  if date_str:
    return f"{date_str}_{clean_content}{ext}"
  return f"{clean_content}{ext}"


def classify_image(
    image_path: Path,
    labels: list[str],
    refinement_terms: dict[str, list[str]] | None = None,
    refinement_min_confidence: float = CLIP_REFINEMENT_MIN_CONFIDENCE,
    refinement_accept_confidence: float = CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
) -> CLIPResult | None:
  """Classify image with optional refinement.

  Args:
    image_path: Path to image file
    labels: List of category labels to classify against
    refinement_terms: Optional dict mapping labels to refinement term lists
    refinement_min_confidence: Min confidence to attempt refinement
    refinement_accept_confidence: Min confidence to accept refinement result

  Returns:
    Tuple of (best_category, confidence, all_scores) or None if unavailable.
  """
  if not CLIP_AVAILABLE:
    return None

  classifier = get_clip_classifier()
  if classifier is None:
    return None

  try:
    # Encode the image once; score every prompt set against the same embedding
    # (byte-identical to the per-call top_match/classify_raw paths, which share
    # the same similarity routine).
    image_emb = classifier.encode_image(image_path)
    if CLIP_CACHE_AVAILABLE:
      # Seed the disk cache so downstream classification tiers reuse this
      # embedding instead of re-encoding the same pixels.
      store_embedding(image_path, classifier.embedding_to_numpy(image_emb))

    # Get best match (matches top_match: "a photo of " prefix)
    prefixed = classifier.score_embedding(image_emb, labels, "a photo of ")
    best_category, confidence = prefixed[0] if prefixed else ("unknown", 0.0)

    # Refine with more specific terms if available
    best_category, confidence = refine_classification(
        classifier,
        image_emb,
        best_category,
        confidence,
        refinement_terms=refinement_terms,
        refinement_min_confidence=refinement_min_confidence,
        refinement_accept_confidence=refinement_accept_confidence,
    )

    # Collect all scores (matches classify_raw: no prefix)
    raw_results = classifier.score_embedding(image_emb, labels, "")
    all_scores = {prompt: conf for prompt, conf in raw_results}

    return CLIPResult(best_category, confidence, all_scores)

  except Exception as e:
    print(f"  CLIP classification error for {image_path.name}: {e}")
    return None


def classify_with_ocr_fallback(
    image_path: Path,
    labels: list[str],
    ocr_threshold: float = 0.10,
    content_classifier=None,
    refinement_terms: dict[str, list[str]] | None = None,
    refinement_min_confidence: float = 0.15,
    refinement_accept_confidence: float = 0.30,
    verbose: bool = False,
) -> CLIPResult | None:
  """Unified CLIP classification with optional OCR fallback.

  Orchestrates CLIP classification + OCR fallback decision in single call.
  Returns consistent 3-tuple format for both tools.

  Args:
    image_path: Path to image file
    labels: List of category labels
    ocr_threshold: Min CLIP confidence to skip OCR fallback
    content_classifier: Optional ContentClassifier for schema.org fallback
    refinement_terms: Optional dict mapping labels to refinement term lists
    refinement_min_confidence: Min confidence to attempt refinement
    refinement_accept_confidence: Min confidence to accept refinement result
    verbose: Print fallback decisions

  Returns:
    Tuple of (best_category, confidence, all_scores) or None if unavailable.
  """
  # Step 1: CLIP classification with optional refinement
  clip_result = classify_image(
      image_path,
      labels,
      refinement_terms=refinement_terms,
      refinement_min_confidence=refinement_min_confidence,
      refinement_accept_confidence=refinement_accept_confidence,
  )
  if not clip_result:
    return None

  clip_category, clip_confidence, clip_scores = clip_result

  # Step 2: Apply OCR fallback if needed
  final_category, final_confidence, final_scores, _ = apply_ocr_fallback_logic(
      clip_category, clip_confidence, clip_scores,
      image_path,
      clip_threshold=ocr_threshold,
      content_classifier=content_classifier,
      verbose=verbose,
  )

  return CLIPResult(final_category, final_confidence, final_scores)
