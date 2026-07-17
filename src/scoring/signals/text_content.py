"""TextContentSignal — keyword-taxonomy scoring over extracted text.

Extracted from ``ContentClassifier.classify_content`` /
``score_categories_detailed`` (UNIFIED_SCORING_PLAN §4 row 9). The signal
calls ``classify_content`` once for the winning category plus its entity
evidence — the company precedence rules (relationship company vs direct
extraction, legal-suffix preference) live there and are reused, never
reimplemented — and ``score_categories_detailed`` for the full keyword
distribution so runner-up categories also receive damped votes.

Divergences from the legacy chain (by design):

- The legacy chain consults ``classify_content`` only at the terminal tier;
  here every scored category competes. Runner-up categories are emitted at
  ``length_factor × normalized_score × TEXT_RUNNERUP_DAMPING`` so a
  runner-up whose keyword total ties the winner still scores strictly below
  it within this signal.
- ``uncategorized`` carries no filing evidence: when ``classify_content``
  returns it the signal emits ``[]`` outright — entities extracted along the
  way are NOT attached to an uncategorized vote (the legacy terminal tier
  still propagates them on its 7-tuple).
- The non-English OCR skip (§3.3) is an ``applies_to`` gate here
  (``ctx.ocr_language in ALLOWED_OCR_LANGUAGES``) instead of the inline
  ``detected_language`` short-circuit inside ``classify_content``.
"""

from __future__ import annotations

from typing import Any, List

from ..types import EVIDENCE_COMPANY, EVIDENCE_PEOPLE, CategoryScore
from ..weights import TEXT_LENGTH_FULL_CHARS, TEXT_MIN_CHARS, W_TEXT

# Damping applied to non-winner categories so a tied runner-up cannot equal
# the winner's confidence within this signal.
TEXT_RUNNERUP_DAMPING = 0.8

# OCR languages the English keyword taxonomy is reliable for; None means the
# text did not come from OCR (or no language was detected).
ALLOWED_OCR_LANGUAGES = (None, "en")

# classify_content's no-match category — carries no filing evidence.
UNCATEGORIZED_CATEGORY = "uncategorized"

# Signal-local evidence keys.
EVIDENCE_LENGTH_FACTOR = "length_factor"
EVIDENCE_SCORES = "scores"
EVIDENCE_NORMALIZED_SCORE = "normalized_score"


class TextContentSignal:
    """Votes for every keyword-scored category, scaled by extraction length."""

    name = "text_content"
    weight = W_TEXT
    cost_tier = "heavy"

    def __init__(self, classifier: Any) -> None:
        self._classifier = classifier

    def applies_to(self, ctx: Any) -> bool:
        return ctx.ocr_language in ALLOWED_OCR_LANGUAGES and ctx.text_length >= TEXT_MIN_CHARS

    def run(self, ctx: Any) -> List[CategoryScore]:
        text = ctx.ensure_text()
        filename = ctx.path.name

        category, subcategory, company_name, people_names = self._classifier.classify_content(
            text, filename
        )
        if category == UNCATEGORIZED_CATEGORY:
            return []

        distribution = self._classifier.score_categories_detailed(text, filename)
        length_factor = min(1.0, ctx.text_length / TEXT_LENGTH_FULL_CHARS)
        normalized_scores = {
            scored_category: normalized for scored_category, (_, normalized) in distribution.items()
        }

        winner_normalized = normalized_scores.get(category, 1.0)
        emissions = [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=length_factor * winner_normalized,
                signal_name=self.name,
                evidence={
                    EVIDENCE_COMPANY: company_name,
                    EVIDENCE_PEOPLE: people_names,
                    EVIDENCE_LENGTH_FACTOR: length_factor,
                    EVIDENCE_SCORES: normalized_scores,
                },
            )
        ]
        for other_category, (best_subcategory, normalized) in distribution.items():
            if other_category in (category, UNCATEGORIZED_CATEGORY):
                continue
            emissions.append(
                CategoryScore(
                    category=other_category,
                    subcategory=best_subcategory,
                    confidence=length_factor * normalized * TEXT_RUNNERUP_DAMPING,
                    signal_name=self.name,
                    evidence={
                        EVIDENCE_LENGTH_FACTOR: length_factor,
                        EVIDENCE_NORMALIZED_SCORE: normalized,
                    },
                )
            )
        return emissions
