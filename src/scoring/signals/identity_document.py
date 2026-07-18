"""IdentityDocumentSignal — passport/ID/license detection from OCR text.

Extracted from ``ContentOrganizer._classify_identification_document``
(UNIFIED_SCORING_PLAN §4 row 4). The identity keyword list and the
MRZ / surname / given-name patterns moved here; ``detect_identity_document``
is the pure keyword-and-name-parsing core the legacy method now delegates
to. The legacy method keeps its OCR call, per-file state writes
(``_last_file_ocr_*``), KIE trigger, and length/confidence gating exactly as
before; the Signal reads the same inputs from ``FileContext`` instead
(``ensure_ocr`` plus the ``ID_MIN_TEXT_CHARS`` / ``OCR_CONFIDENCE_GATE``
checks below).

Confidence grades: a passport MRZ match is machine-readable and
near-certain (``ID_MRZ_CONFIDENCE``); keyword detection — whichever name
extraction backs it — is strong but OCR-fuzzy (``ID_KEYWORD_CONFIDENCE``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

import re
from typing import Any, Callable, List, NamedTuple, Optional

from ..types import EVIDENCE_PEOPLE, CategoryScore
from ..weights import OCR_CONFIDENCE_GATE, W_ID

# Minimum OCR text length before identity detection is attempted (mirrors the
# legacy tier-3.5 gate, which now imports this constant).
ID_MIN_TEXT_CHARS = 30

# Emission confidences by detection method.
ID_MRZ_CONFIDENCE = 1.0
ID_KEYWORD_CONFIDENCE = 0.85

# Filing destination for identity documents.
IDENTITY_CATEGORY = ("personal", "identification")

# OCR keywords indicating an identification document (order preserved from the
# legacy list; the first hit is reported as evidence).
ID_KEYWORDS = (
    "passport",
    "driver license",
    "driver's license",
    "identification",
    "united states of america",
    "department of state",
    "nationality",
    "date of birth",
    "place of birth",
    "surname",
    "given names",
    "social security",
    "state id",
    "national id",
    # License *back* term: the back of a US driver license often lacks the
    # words "driver license"/"date of birth" (those are front-side), carrying
    # only class/restriction fields. "corrective lenses" is a near-unique
    # license restriction that catches a photographed back which would
    # otherwise fall through to MIME/`neither`; kept last so any front-side
    # keyword above still wins the reported-keyword slot. ("restrictions" and
    # "endorsements" were dropped after a backtest showed they collide with
    # insurance-document language — see docs/BACKLOG.md.)
    "corrective lenses",
)

# Method 1 — passport MRZ (Machine Readable Zone):
# P<COUNTRY{SURNAME}<<{GIVEN_NAME}<...
MRZ_NAME_PATTERN = re.compile(r"P<[A-Z]{3}([A-Z]+)<<([A-Z]+)<")

# Method 2 — labelled name fields with the value on the next line
# (passport layout: "Surname/Nom\nLEDLIE").
SURNAME_FIELD_PATTERN = re.compile(
    r"(?:surname|nom|apellidos)[/\w\s]*\n\s*([A-Z]{2,})\b", re.IGNORECASE
)
GIVEN_NAME_FIELD_PATTERN = re.compile(
    r"(?:given\s*names?|pr[ée]noms?|nombres)[/\w\s]*\n\s*([A-Z]{2,})\b", re.IGNORECASE
)

# Name-extraction methods, in attempt order. ``METHOD_EXTRACTOR`` also labels
# the fall-through case where the general extractor found no names — the
# match then carries an empty ``people_names`` (keyword evidence still files
# the document, exactly like the legacy tier).
METHOD_MRZ = "mrz"
METHOD_NAME_FIELDS = "name_fields"
METHOD_EXTRACTOR = "extractor"

# Signal-local evidence keys.
EVIDENCE_MATCHED_KEYWORD = "matched_keyword"
EVIDENCE_METHOD = "method"


class IdentityMatch(NamedTuple):
    """Outcome of ``detect_identity_document`` on identity-keyword text."""

    people_names: List[str]
    matched_keyword: str
    method: str


def detect_identity_document(
    ocr_text: str,
    *,
    extract_people_names: Callable[[str], List[str]],
) -> Optional[IdentityMatch]:
    """Keyword + name detection over OCR text; ``None`` when not an ID document.

    Reproduces the keyword check and the three name-extraction methods of the
    legacy ``_classify_identification_document`` in order: passport MRZ,
    labelled surname/given-name fields, then the injected general extractor.
    Gating (text length, OCR confidence) is the caller's responsibility.
    """
    ocr_lower = ocr_text.lower()
    matched_keyword = next((keyword for keyword in ID_KEYWORDS if keyword in ocr_lower), None)
    if matched_keyword is None:
        return None

    people_names: List[str] = []
    method = METHOD_EXTRACTOR

    # Method 1: Parse passport MRZ (Machine Readable Zone).
    mrz_match = MRZ_NAME_PATTERN.search(ocr_text)
    if mrz_match:
        surname = mrz_match.group(1).title()
        given = mrz_match.group(2).title()
        people_names = [f"{given} {surname}"]
        method = METHOD_MRZ

    # Method 2: Name fields with values on the next line or after a colon.
    if not people_names:
        surname_match = SURNAME_FIELD_PATTERN.search(ocr_text)
        given_match = GIVEN_NAME_FIELD_PATTERN.search(ocr_text)
        if surname_match and given_match:
            people_names = [f"{given_match.group(1).title()} {surname_match.group(1).title()}"]
            method = METHOD_NAME_FIELDS

    # Method 3: General name extraction patterns.
    if not people_names:
        people_names = extract_people_names(ocr_text)
        method = METHOD_EXTRACTOR

    return IdentityMatch(
        people_names=people_names,
        matched_keyword=matched_keyword,
        method=method,
    )


class IdentityDocumentSignal:
    """Votes ``personal/identification`` (+ people names) for ID images."""

    name = "identity_document"
    weight = W_ID
    cost_tier = "heavy"

    def __init__(self, classifier: Any) -> None:
        self._classifier = classifier

    def applies_to(self, ctx: FileContext) -> bool:
        return bool(ctx.is_image)

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        ocr = ctx.ensure_ocr()
        if ocr is None:
            return []
        ocr_text = ocr.text or ""
        if len(ocr_text) < ID_MIN_TEXT_CHARS:
            return []
        if ocr.confidence is not None and ocr.confidence < OCR_CONFIDENCE_GATE:
            return []

        match = detect_identity_document(
            ocr_text,
            extract_people_names=self._classifier.extract_people_names,
        )
        if match is None:
            return []

        confidence = ID_MRZ_CONFIDENCE if match.method == METHOD_MRZ else ID_KEYWORD_CONFIDENCE
        category, subcategory = IDENTITY_CATEGORY
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence={
                    EVIDENCE_PEOPLE: match.people_names,
                    EVIDENCE_MATCHED_KEYWORD: match.matched_keyword,
                    EVIDENCE_METHOD: match.method,
                },
            )
        ]
