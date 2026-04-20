"""Unified confidence gate for CLIP classification results."""
from __future__ import annotations


class ConfidenceGateResult:
  """Result of confidence gate evaluation."""
  
  def __init__(self, accepted: bool, reason: str | None = None):
    self.accepted = accepted
    self.reason = reason  # Error message if rejected


def check_confidence(
    category: str,
    confidence: float,
    min_confidence: float = 0.1,
) -> ConfidenceGateResult:
  """
  Evaluate whether a classification meets confidence threshold.

  Args:
    category: Classification category (for context)
    confidence: Confidence score [0.0, 1.0]
    min_confidence: Minimum acceptable confidence threshold

  Returns:
    ConfidenceGateResult with accepted flag and optional reason
  """
  if confidence < min_confidence:
    reason = f"Confidence too low: {confidence:.1%} (threshold: {min_confidence:.1%})"
    return ConfidenceGateResult(accepted=False, reason=reason)
  
  return ConfidenceGateResult(accepted=True)
