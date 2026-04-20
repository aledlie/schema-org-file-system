"""Unified CLIP image classification with optional refinement."""
from __future__ import annotations

from pathlib import Path

from shared.clip_utils import get_clip_classifier, CLIP_AVAILABLE
from shared.ocr_classifier import apply_ocr_fallback as apply_ocr_fallback_logic


def classify_image(
    image_path: Path,
    labels: list[str],
    refinement_terms: dict[str, list[str]] | None = None,
    refinement_min_confidence: float = 0.15,
    refinement_accept_confidence: float = 0.30,
    collect_all_scores: bool = False,
) -> tuple[str, float, dict[str, float]] | None:
  """Classify image with optional refinement and score collection.

  Args:
    image_path: Path to image file
    labels: List of category labels to classify against
    refinement_terms: Optional dict mapping labels to refinement term lists
    refinement_min_confidence: Min confidence to attempt refinement
    refinement_accept_confidence: Min confidence to accept refinement result
    collect_all_scores: If True, return all label scores; else empty dict

  Returns:
    Tuple of (best_category, confidence, all_scores) or None if unavailable.
  """
  if not CLIP_AVAILABLE:
    return None

  classifier = get_clip_classifier()
  if classifier is None:
    return None

  try:
    # Get best match
    best_category, confidence = classifier.top_match(image_path, labels)

    # Optional refinement
    if refinement_terms and best_category in refinement_terms:
      if confidence > refinement_min_confidence:
        refinements = refinement_terms[best_category]
        refined_term, refined_confidence = classifier.top_match(
            image_path, refinements
        )
        if refined_confidence > refinement_accept_confidence:
          best_category = refined_term
          confidence = refined_confidence

    # Collect all scores if requested
    all_scores: dict[str, float] = {}
    if collect_all_scores:
      raw_results = classifier.classify_raw(image_path, labels)
      all_scores = {prompt: conf for prompt, conf in raw_results}

    return (best_category, confidence, all_scores)

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
    collect_all_scores: bool = False,
    verbose: bool = False,
) -> tuple[str, float, dict[str, float]] | None:
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
    collect_all_scores: If True, return all label scores; else empty dict
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
      collect_all_scores=collect_all_scores,
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

  return (final_category, final_confidence, final_scores)
