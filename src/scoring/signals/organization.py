"""OrganizationKeywordSignal — organization-document detection (§4 row 5).

Extracted from ``ContentOrganizer.classify_by_organization``; the legacy
method now delegates to :func:`detect_organization` so the tier chain and the
unified signal share one implementation (bit-for-bit legacy behavior).

Intentional broadening vs legacy (§4 format-drift fix): the legacy tier only
ran for ``DigitalDocument``/PDF files (``detect_file_category`` gates
PRIORITY 1 on schema type), so organization letterheads on image scans were
invisible to it. This signal runs for ALL schema types, including images —
``FileContext.ensure_text()`` routes image text through OCR, so a PDF and a
PNG of the same letter accumulate the same organization evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from typing import Any, Callable, Dict, List, Optional, Tuple

from ..types import EVIDENCE_COMPANY, CategoryScore
from ..weights import W_ORG

# Minimum extracted-text length for organization detection (mirrors the
# legacy ``len(text) < 50`` gate in ``classify_by_organization``).
ORG_MIN_TEXT_CHARS = 50

# An organization type's indicators must hit at least this many times
# (legacy "require at least 2 keyword matches" rule).
ORG_MIN_KEYWORD_HITS = 2

# Hit-scaled confidence: base at exactly ORG_MIN_KEYWORD_HITS hits, plus one
# increment per additional hit, capped at ORG_CONFIDENCE_MAX.
ORG_CONFIDENCE_BASE = 0.7
ORG_CONFIDENCE_PER_HIT = 0.1
ORG_CONFIDENCE_MAX = 1.0

ORGANIZATION_CATEGORY = "organization"

# Signal-local evidence keys (EVIDENCE_COMPANY is the cross-cutting one).
EVIDENCE_ORG_TYPE = "org_type"
EVIDENCE_KEYWORD_HITS = "keyword_hits"

# Organization type indicators, moved verbatim from
# ``ContentOrganizer.classify_by_organization``. Dict order is load-bearing:
# the first type whose indicators clear ORG_MIN_KEYWORD_HITS (with an
# extractable company name) wins, exactly like the legacy loop.
ORG_INDICATORS: Dict[str, List[str]] = {
    "government": [
        "department of",
        "internal revenue",
        "irs",
        "social security",
        "state of",
        "county of",
        "city of",
        "municipality",
        "federal",
        "government",
        "agency",
        "bureau",
        "commission",
        "dmv",
        "passport",
        "immigration",
        "customs",
        "treasury",
    ],
    "healthcare": [
        "hospital",
        "clinic",
        "medical center",
        "health system",
        "healthcare",
        "physicians",
        "doctor",
        "patient",
        "diagnosis",
        "prescription",
        "pharmacy",
        "insurance claim",
        "medicare",
        "medicaid",
        "hipaa",
        "medical record",
        "lab results",
        # Genomics / clinical-lab vocabulary (e.g. GeneDx variant classification
        # process docs contain none of the clinical-care terms above).
        "genomic",
        "variant classification",
        "pathogenic",
        "sequencing",
    ],
    "financial": [
        "bank",
        "credit union",
        "investment",
        "brokerage",
        "mortgage",
        "loan",
        "account statement",
        "transaction",
        "wire transfer",
        "routing number",
        "account number",
        "fdic",
        "securities",
        # Insurance vocabulary (e.g. a homeowners policy summary contains none
        # of the banking terms above, except incidentally via a mortgagee
        # clause — 2 hits, leaving the org signal too weak to win).
        "insurance",
        "policy number",
        "premium",
        "deductible",
        "insured",
    ],
    "educational": [
        "university",
        "college",
        "school",
        "academy",
        "institute",
        "transcript",
        "diploma",
        "degree",
        "enrollment",
        "registrar",
        "financial aid",
        "tuition",
        "semester",
        "course",
        "student id",
    ],
    "nonprofit": [
        "foundation",
        "charity",
        "nonprofit",
        "non-profit",
        "501(c)",
        "donation",
        "volunteer",
        "mission",
        "charitable",
    ],
    "employers": [
        "offer letter",
        "employment agreement",
        "w-2",
        "w2",
        "pay stub",
        "payroll",
        "human resources",
        "hr department",
        "employee id",
        "benefits enrollment",
        "performance review",
        "termination",
    ],
    "vendors": [
        "invoice",
        "purchase order",
        "po number",
        "vendor id",
        "supplier",
        "bill to",
        "ship to",
        "payment terms",
        "net 30",
    ],
    "clients": [
        "client",
        "customer",
        "service agreement",
        "statement of work",
        "sow",
        "proposal",
        "quote",
        "estimate",
        "engagement letter",
    ],
}


def detect_organization(
    text: str, *, extract_company_names: Callable[[str], List[str]]
) -> Optional[Tuple[str, str, int]]:
    """First org type (dict order) with enough keyword hits and a company name.

    Returns ``(org_type, org_name, hit_count)`` or ``None``. Mirrors the
    legacy loop exactly, including trying later indicator types when a
    hit-clearing type yields no extractable company name.
    """
    text_lower = text.lower()
    for org_type, keywords in ORG_INDICATORS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits >= ORG_MIN_KEYWORD_HITS:
            companies = extract_company_names(text)
            org_name = companies[0] if companies else None
            if org_name:
                return (org_type, org_name, hits)
    return None


def organization_confidence(hit_count: int) -> float:
    """Hit-scaled confidence: base at the minimum hits, +PER_HIT per extra."""
    extra_hits = max(hit_count - ORG_MIN_KEYWORD_HITS, 0)
    return min(ORG_CONFIDENCE_BASE + ORG_CONFIDENCE_PER_HIT * extra_hits, ORG_CONFIDENCE_MAX)


class OrganizationKeywordSignal:
    """Org indicators + extractable company name → ``organization/{type}``.

    Brand-as-person collisions are resolved by competition with
    ``PersonalDocSignal`` (§4 row 5), not by tier order.
    """

    name = "organization_keyword"
    weight = W_ORG
    cost_tier = "mid"

    def __init__(self, classifier: Any) -> None:
        # ContentClassifier (or anything exposing extract_company_names).
        self._classifier = classifier

    def applies_to(self, ctx: FileContext) -> bool:
        return bool(ctx.text_length >= ORG_MIN_TEXT_CHARS)

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        detected = detect_organization(
            ctx.ensure_text(),
            extract_company_names=self._classifier.extract_company_names,
        )
        if detected is None:
            return []
        org_type, org_name, hits = detected
        return [
            CategoryScore(
                category=ORGANIZATION_CATEGORY,
                subcategory=org_type,
                confidence=organization_confidence(hits),
                signal_name=self.name,
                evidence={
                    EVIDENCE_COMPANY: org_name,
                    EVIDENCE_ORG_TYPE: org_type,
                    EVIDENCE_KEYWORD_HITS: hits,
                },
            )
        ]
