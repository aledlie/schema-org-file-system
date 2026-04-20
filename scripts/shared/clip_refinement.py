"""CLIP classification refinement using more specific terms."""
from __future__ import annotations

from pathlib import Path


def refine_classification(
    classifier,
    image_path: Path,
    best_category: str,
    confidence: float,
    refinement_terms: dict[str, list[str]] | None = None,
    refinement_min_confidence: float = 0.15,
    refinement_accept_confidence: float = 0.30,
) -> tuple[str, float]:
  """Refine CLIP classification using more specific terms.

  Args:
    classifier: CLIPClassifier instance
    image_path: Path to image file
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
  refined_term, refined_confidence = classifier.top_match(image_path, refinements)

  if refined_confidence > refinement_accept_confidence:
    return refined_term, refined_confidence

  return best_category, confidence
