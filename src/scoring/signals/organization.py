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

import re
from typing import Callable, Dict, FrozenSet, List, NamedTuple, Optional, Protocol, Tuple

from ..types import EVIDENCE_COMPANY, CategoryScore
from ..weights import W_ORG


class _CompanyExtractor(Protocol):
    """The ContentClassifier slice this signal uses."""

    def extract_company_names(self, text: str) -> List[str]: ...


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
        # Insurance POLICY vocabulary (insurance/policy number/premium/
        # deductible/insured) is deliberately ABSENT: policy documents route
        # financial/insurance via the text-content taxonomy, not
        # organization/financial — org keywords here would score 1.0 on any
        # policy page and (at W_ORG 1.0 > W_TEXT 0.8) steal every policy from
        # that bucket. Insurer ACCOUNT STATEMENTS still route here via the
        # banking terms above. Pinned by the named-insurer golden pair in
        # tests/integration/test_unified_scoring_golden.py.
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


# Government indicators split by what they actually attest. The identity set
# names a government body ("department of", "internal revenue"); the rest are
# topical words that appear in any document *about* dealing with government.
# Two topical words were enough to type an Austin domestic-violence nonprofit
# as government — "agency" and "immigration", both incidental in a survivor
# intake form that asks about immigration status. Requiring one identity-bearing
# indicator keeps the IRS notices and DMV letters this type exists for.
GOVERNMENT_IDENTITY_INDICATORS: FrozenSet[str] = frozenset(
    {
        "department of",
        "internal revenue",
        "irs",
        "social security",
        "state of",
        "county of",
        "city of",
        "dmv",
        "treasury",
    }
)

# Org types where clearing ORG_MIN_KEYWORD_HITS is necessary but not sufficient:
# at least one of these identity-bearing indicators must also hit.
ORG_TYPE_REQUIRED_INDICATORS: Dict[str, FrozenSet[str]] = {
    "government": GOVERNMENT_IDENTITY_INDICATORS,
}


class OrgIdentity(NamedTuple):
    """The canonical name and type behind a domain."""

    name: str
    org_type: str


# Domains whose organization cannot be read off the document text. A body's
# letterhead often carries only a department or program name — the SAFE
# Alliance's legal intake form says "SAFE Legal Department" and
# "legal@safeaustin.org", and never its own name — so keyword typing lands on
# the wrong type and company extraction lands on the wrong name. A domain is
# unambiguous provenance, so it resolves both. Hand-curated and deliberately
# small: this is not a substitute for entity extraction, only an override for
# organizations whose documents do not name themselves.
ORG_DOMAIN_IDENTITIES: Dict[str, OrgIdentity] = {
    "safeaustin.org": OrgIdentity(name="The SAFE Alliance", org_type="nonprofit"),
}

# Email addresses and bare hostnames; the capture is the registrable domain as
# written, matched against ORG_DOMAIN_IDENTITIES case-folded.
_DOMAIN_PATTERN = re.compile(
    r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)|(?:https?://|www\.)([\w-]+(?:\.[\w-]+)+)"
)


def detect_organization_domain(text: str) -> Optional[OrgIdentity]:
    """Resolve a curated organization identity from a domain in *text*."""
    for match in _DOMAIN_PATTERN.finditer(text):
        domain = (match.group(1) or match.group(2) or "").lower()
        identity = ORG_DOMAIN_IDENTITIES.get(domain)
        if identity is not None:
            return identity
    return None


def detect_organization(
    text: str, *, extract_company_names: Callable[[str], List[str]]
) -> Optional[Tuple[str, str, int]]:
    """First org type (dict order) with enough keyword hits and a company name.

    Returns ``(org_type, org_name, hit_count)`` or ``None``. Mirrors the
    legacy loop exactly, including trying later indicator types when a
    hit-clearing type yields no extractable company name — except that a
    curated domain (:data:`ORG_DOMAIN_IDENTITIES`) overrides both the type and
    the name, and that types in :data:`ORG_TYPE_REQUIRED_INDICATORS` must also
    hit an identity-bearing indicator.

    ``hit_count`` on a domain-identity result is always
    :data:`ORG_MIN_KEYWORD_HITS`, never a running keyword count. The keywords
    that clear the gate belong to whichever type the sweep reaches first, which
    is frequently *not* the type the domain resolves to — the SAFE Alliance
    form clears ``government`` on "agency"/"immigration" while resolving to
    ``nonprofit``, so reporting that count would scale a nonprofit's confidence
    by how much government vocabulary the page happened to contain. A curated
    domain is evidence in its own right and does not need the keyword sweep at
    all, so it is checked first and every domain result scores at base
    confidence.
    """
    identity = detect_organization_domain(text)
    if identity is not None:
        return (identity.org_type, identity.name, ORG_MIN_KEYWORD_HITS)

    text_lower = text.lower()
    for org_type, keywords in ORG_INDICATORS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits < ORG_MIN_KEYWORD_HITS:
            continue
        required = ORG_TYPE_REQUIRED_INDICATORS.get(org_type)
        if required is not None and not any(kw in text_lower for kw in required):
            continue
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

    def __init__(self, classifier: _CompanyExtractor) -> None:
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
