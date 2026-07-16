"""KieStructuredSignal — structured invoice/receipt fields via KIE.

Wraps ``ContentClassifier.classify_with_kie`` (UNIFIED_SCORING_PLAN §4 row 3;
§11 OQ #7 resolution: KIE stays a standalone signal served by
``FileContext.ensure_kie``). The legacy tier-3.5 → tier-6 hidden dependency —
KIE only runs when OCR confidence clears ``OCR_CONFIDENCE_GATE`` — is
enforced inside ``ensure_kie``, not here. ``classify_with_kie`` itself stays
on the classifier (the field-confidence ≥ 0.5 gate lives there); no
organizer edits were needed for this signal.
"""

from __future__ import annotations

from typing import Any, List

from ..types import EVIDENCE_COMPANY, EVIDENCE_PEOPLE, CategoryScore
from ..weights import W_KIE

# Structured vendor+amount/date extraction is the strongest content evidence
# short of an exact MRZ match.
KIE_MATCH_CONFIDENCE = 0.95

# Signal-local evidence key: which KIE field classes were extracted.
EVIDENCE_KIE_FIELD_CLASSES = "kie_field_classes"


class KieStructuredSignal:
    """Votes the KIE classification (vendor evidence attached) for images."""

    name = "kie_structured"
    weight = W_KIE
    cost_tier = "heavy"

    def __init__(self, classifier: Any) -> None:
        self._classifier = classifier

    def applies_to(self, ctx: Any) -> bool:
        return ctx.is_image

    def run(self, ctx: Any) -> List[CategoryScore]:
        kie_result = ctx.ensure_kie()
        if kie_result is None:
            return []

        classification = self._classifier.classify_with_kie(
            kie_result, ctx.ensure_text(), ctx.path.name
        )
        if classification is None:
            return []

        category, subcategory, company_name, people_names = classification
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=KIE_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence={
                    EVIDENCE_COMPANY: company_name,
                    EVIDENCE_PEOPLE: people_names,
                    EVIDENCE_KIE_FIELD_CLASSES: sorted(kie_result.fields.keys()),
                },
            )
        ]
