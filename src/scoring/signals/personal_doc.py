"""PersonalDocSignal — person-document detection (§4 row 6, Option C).

Extracted from ``ContentOrganizer.classify_by_person``; the legacy method
delegates to :func:`is_resume_filename` / :func:`detect_person_indicators`
so both paths share one implementation.

Designed divergences from the legacy tier:

- **No legal-document veto here.** The legacy method keeps its court-signal
  early return (it must stay bit-for-bit); the veto is applied by that
  caller, never inside the shared core. In the unified scorer,
  ``LegalContentSignal`` competes instead (§3.3) and is designed to outscore
  this signal on court documents.
- **Graduated confidence replaces the binary name gate.** Legacy returned
  ``None`` when ``_has_human_name_signal`` failed; the signal emits the same
  category at ``PERSON_UNGATED_CONFIDENCE`` so other signals can confirm or
  outscore it, and ``people_names`` evidence is attached regardless of the
  filing winner (Option C: graph edges are independent of placement).
- **Single evaluation of the people/name gates.** The legacy loop kept
  scanning later indicator types after a people/gate failure; because
  extraction and the gate depend only on the text (never on the indicator
  type), the outcome is identical — the core stops at the first
  hit-clearing type and evaluates people extraction + the name gate once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from typing import Any, Callable, Dict, List, NamedTuple, Optional

from src.classifiers.entity_detector import _has_human_name_signal

from ..types import EVIDENCE_PEOPLE, CategoryScore
from ..weights import W_PERSON

# Minimum extracted-text length for person detection (mirrors the legacy
# ``len(text) < 50`` gate in ``classify_by_person``).
PERSON_MIN_TEXT_CHARS = 50

# Person-detection keyword thresholds. The generic person types need two
# indicator hits; `contacts` needs three because its indicators ('contact',
# 'phone:', '@', …) appear in the footer of virtually any official letter —
# two hits is just a letterhead, three implies an actual contact-card layout.
PERSON_MIN_KEYWORD_HITS = 2
CONTACTS_MIN_KEYWORD_HITS = 3

# Graduated confidence (§4 row 6): full confidence when people were extracted
# AND the human-name gate passes; reduced (not vetoed) when the gate fails.
PERSON_GATED_CONFIDENCE = 0.9
PERSON_UNGATED_CONFIDENCE = 0.4

PERSONAL_CATEGORY = "personal"
CONTACTS_SUBCATEGORY = "contacts"
CONTACTS_PERSON_TYPE = "contacts"

# Filename fragments that mark a resume/CV (legacy resume_patterns).
RESUME_FILENAME_PATTERNS = ("resume", "cv", "curriculum", "vitae")

# Signal-local evidence keys (EVIDENCE_PEOPLE is the cross-cutting one).
EVIDENCE_PERSON_TYPE = "person_type"
EVIDENCE_KEYWORD_HITS = "keyword_hits"
EVIDENCE_NAME_GATE = "name_gate"
EVIDENCE_RESUME_FILENAME = "resume_filename"

# Person type indicators, moved verbatim from
# ``ContentOrganizer.classify_by_person``. Dict order is load-bearing: the
# first type whose indicators clear its threshold wins.
PERSON_INDICATORS: Dict[str, List[str]] = {
    "contacts": [
        "contact",
        "phone:",
        "email:",
        "address:",
        "mobile:",
        "tel:",
        "fax:",
        "linkedin",
        "twitter",
        "@",
    ],
    "employees": [
        "employee",
        "staff",
        "team member",
        "department:",
        "title:",
        "hire date",
        "start date",
        "position:",
        "role:",
    ],
    "references": [
        "reference",
        "recommendation",
        "letter of",
        "to whom it may concern",
        "i am pleased to",
        "i highly recommend",
        "worked with",
    ],
    "clients": [
        "client profile",
        "customer profile",
        "client information",
        "account holder",
        "policyholder",
    ],
}

# Option C: `person` is demoted from a category to a graph relationship.
# Person detection still identifies *which kind* of person document this is,
# but maps that detection onto the `personal` category's subcategories
# instead of returning a separate `person` category. See
# docs/changelog/2.1.0/PERSON_TAXONOMY_OPTION_C_PLAN.md for the rationale.
PERSON_SUBCAT_TO_PERSONAL_SUBCAT: Dict[str, str] = {
    "contacts": "contacts",
    "employees": "employment",
    "references": "employment",
    "clients": "other",
    "travel": "other",
    "events": "events",
    "journal": "journal",
    "family": "other",
    "other": "other",
}


class PersonIndicatorMatch(NamedTuple):
    """Outcome of the indicator scan for the first hit-clearing person type."""

    person_type: str
    subcategory: str
    keyword_hits: int
    people: List[str]
    name_gate: bool


def is_resume_filename(filename: str) -> bool:
    """True when the filename matches the legacy resume/CV patterns."""
    filename_lower = filename.lower()
    return any(pattern in filename_lower for pattern in RESUME_FILENAME_PATTERNS)


def detect_person_indicators(
    text: str,
    *,
    extract_people_names: Callable[[str], List[str]],
    has_human_name_signal: Callable[[str], bool],
) -> Optional[PersonIndicatorMatch]:
    """First person type (dict order) whose keyword hits clear its threshold.

    People extraction and the human-name gate are evaluated once for that
    type (the gate only when people were found, matching the legacy
    short-circuit). Callers decide how to treat gate failures: the legacy
    method returns ``None``; ``PersonalDocSignal`` emits graduated
    confidence.
    """
    text_lower = text.lower()
    for person_type, keywords in PERSON_INDICATORS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        min_hits = (
            CONTACTS_MIN_KEYWORD_HITS
            if person_type == CONTACTS_PERSON_TYPE
            else PERSON_MIN_KEYWORD_HITS
        )
        if hits < min_hits:
            continue
        people = list(extract_people_names(text) or [])
        name_gate = bool(people) and bool(has_human_name_signal(text))
        return PersonIndicatorMatch(
            person_type=person_type,
            subcategory=PERSON_SUBCAT_TO_PERSONAL_SUBCAT[person_type],
            keyword_hits=hits,
            people=people,
            name_gate=name_gate,
        )
    return None


class PersonalDocSignal:
    """Person-document indicators → ``personal/{subcat}`` + people evidence.

    Emits ``people_names`` evidence on every emission that found people —
    including ungated ones — so ``GraphStore.add_file_to_person`` edges
    attach regardless of the filing winner (Option C).
    """

    name = "personal_doc"
    weight = W_PERSON
    cost_tier = "mid"

    def __init__(self, classifier: Any) -> None:
        # ContentClassifier (or anything exposing extract_people_names).
        self._classifier = classifier

    def applies_to(self, ctx: FileContext) -> bool:
        return bool(ctx.text_length >= PERSON_MIN_TEXT_CHARS)

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        text = ctx.ensure_text()
        extract_people_names = self._classifier.extract_people_names

        # Resume/CV filename patterns — filename-driven, no name gate (the
        # legacy branch classified these regardless of extracted people).
        if is_resume_filename(ctx.pattern_path.name):
            people = list(extract_people_names(text) or [])
            evidence: Dict[str, Any] = {
                EVIDENCE_RESUME_FILENAME: True,
                EVIDENCE_PERSON_TYPE: CONTACTS_PERSON_TYPE,
            }
            if people:
                evidence[EVIDENCE_PEOPLE] = people
            return [
                CategoryScore(
                    category=PERSONAL_CATEGORY,
                    subcategory=CONTACTS_SUBCATEGORY,
                    confidence=PERSON_GATED_CONFIDENCE,
                    signal_name=self.name,
                    evidence=evidence,
                )
            ]

        match = detect_person_indicators(
            text,
            extract_people_names=extract_people_names,
            has_human_name_signal=_has_human_name_signal,
        )
        if match is None or not match.people:
            return []
        confidence = PERSON_GATED_CONFIDENCE if match.name_gate else PERSON_UNGATED_CONFIDENCE
        return [
            CategoryScore(
                category=PERSONAL_CATEGORY,
                subcategory=match.subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence={
                    EVIDENCE_PEOPLE: match.people,
                    EVIDENCE_PERSON_TYPE: match.person_type,
                    EVIDENCE_KEYWORD_HITS: match.keyword_hits,
                    EVIDENCE_NAME_GATE: match.name_gate,
                },
            )
        ]
