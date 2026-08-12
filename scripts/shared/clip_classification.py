"""Unified CLIP image classification with refinement and naming."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from shared.clip_utils import CLIP_AVAILABLE, get_clip_classifier
from shared.ocr_classifier import apply_ocr_fallback as apply_ocr_fallback_logic

try:
    from shared.clip_cache import CLIP_CACHE_AVAILABLE, store_embedding
except ImportError:
    CLIP_CACHE_AVAILABLE = False
from shared.constants import (
    CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
    CLIP_REFINEMENT_MIN_CONFIDENCE,
)

# Which vocabulary produced the winning label (CLIPResult.label_source).
LABEL_SOURCE_CLIP = "clip"  # the prompt-prefixed base ranking — has a margin
LABEL_SOURCE_REFINEMENT = "refinement"  # cleared CLIP_REFINEMENT_ACCEPT_CONFIDENCE
LABEL_SOURCE_OCR = "ocr"  # OCR override — only had to beat a sub-threshold CLIP score


class CLIPResult(NamedTuple):
    """Unified CLIP classification result.

    Two scoring distributions are stored to make their distinct roles explicit:

    - ``decision_scores`` — the prompt-prefixed pass (``"a photo of "``) that
      actually chose ``category``.  Consumers that want to understand or audit
      the decision should read this field.
    - ``raw_scores`` — the unprefixed pass (``prompt_prefix=""``).  The two
      distributions differ in practice; having both named makes it impossible to
      silently read the wrong one.
    - ``all_scores`` — **deprecated alias for ``raw_scores``**.  Carries the
      unprefixed distribution (same value ``all_scores`` always held).  Prefer
      ``raw_scores`` for clarity.  No in-repo readers should remain; this exists
      only for external callers.
    """

    category: str
    confidence: float
    # Scores from the "a photo of " prefixed pass that chose ``category``.
    decision_scores: dict[str, float]
    # Scores from the unprefixed pass — a different, flatter distribution.
    raw_scores: dict[str, float]
    # Top-1/top-2 ratio of the prompt-prefixed distribution that *chose*
    # ``category`` — the only usable measure of how decided this label is, since
    # the unscaled softmax leaves absolute confidences pinned near the uniform
    # floor. ``None`` means ``category`` did not come from that ranking (OCR
    # fallback or an accepted refinement won instead), so callers must not apply
    # a margin gate to it.
    margin: float | None = None
    # Which vocabulary actually produced ``category``. A ``None`` margin is
    # ambiguous on its own — an accepted refinement cleared its own absolute
    # threshold, while an OCR override only had to beat a CLIP score that was
    # already below the fallback trigger. Callers that gate on separation need
    # to tell those apart rather than treating "no margin" as "no objection".
    label_source: str = LABEL_SOURCE_CLIP

    @property
    def all_scores(self) -> dict[str, float]:
        """Deprecated alias for ``raw_scores`` (the unprefixed distribution).

        Prefer ``raw_scores`` for clarity, or ``decision_scores`` if you need
        the distribution that actually picked the winner.  Zero in-repo readers
        remain; this property exists only for external consumers.
        """
        return self.raw_scores


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
    clean_content = re.sub(r"[^a-z0-9_]", "", content.lower().replace(" ", "_"))

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

        # Get best match using the "a photo of " prefix — this IS the decision pass.
        prefixed = classifier.score_embedding(image_emb, labels, "a photo of ")
        best_category, confidence = prefixed[0] if prefixed else ("unknown", 0.0)

        # How decided that top match was, before refinement can replace it.
        # score_embedding returns descending order, so [1] is the runner-up.
        margin: float | None = None
        if len(prefixed) > 1 and prefixed[1][1] > 0:
            margin = prefixed[0][1] / prefixed[1][1]

        # Refine with more specific terms if available
        refined_category, confidence = refine_classification(
            classifier,
            image_emb,
            best_category,
            confidence,
            refinement_terms=refinement_terms,
            refinement_min_confidence=refinement_min_confidence,
            refinement_accept_confidence=refinement_accept_confidence,
        )
        label_source = LABEL_SOURCE_CLIP
        if refined_category != best_category:
            # The refinement vocabulary chose the label, so the margin computed
            # over `labels` no longer describes this decision.
            margin = None
            label_source = LABEL_SOURCE_REFINEMENT
        best_category = refined_category

        # decision_scores: the prefixed distribution that chose the winner.
        decision_scores = {prompt: conf for prompt, conf in prefixed}

        # raw_scores: unprefixed pass — a distinct, flatter distribution kept
        # so callers that need to compare the two can do so explicitly.
        raw_results = classifier.score_embedding(image_emb, labels, "")
        raw_scores = {prompt: conf for prompt, conf in raw_results}

        return CLIPResult(
            best_category, confidence, decision_scores, raw_scores, margin, label_source
        )

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

    # Attribute access, not tuple unpacking: CLIPResult carries a margin field
    # that unpacking here would silently reject on arity.
    clip_category = clip_result.category

    # Step 2: Apply OCR fallback if needed.
    # Pass decision_scores so the threshold comparison uses the same distribution
    # that chose clip_category, and any OCR merge starts from that baseline.
    final_category, final_confidence, final_decision_scores, _ = apply_ocr_fallback_logic(
        clip_category,
        clip_result.confidence,
        clip_result.decision_scores,
        image_path,
        clip_threshold=ocr_threshold,
        content_classifier=content_classifier,
        verbose=verbose,
    )

    # raw_scores always carries the unmodified unprefixed CLIP distribution;
    # it is not affected by whether OCR overrode the decision.
    final_raw_scores = clip_result.raw_scores

    # The CLIP margin only describes the label CLIP itself picked; when OCR
    # supplies a better one, there is no CLIP separation to gate on.
    ocr_won = final_category != clip_category
    margin = None if ocr_won else clip_result.margin
    label_source = LABEL_SOURCE_OCR if ocr_won else clip_result.label_source

    return CLIPResult(
        final_category,
        final_confidence,
        final_decision_scores,
        final_raw_scores,
        margin,
        label_source,
    )
