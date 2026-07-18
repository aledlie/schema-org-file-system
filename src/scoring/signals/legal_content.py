"""LegalContentSignal — legal-document detection by competition (§4 row 7).

NEW signal (no 1:1 legacy tier): it replaces the person-tier hard veto at
``ContentOrganizer.classify_by_person`` with competition (§3.3). The
``LEGAL_DOCUMENT_SIGNALS`` / ``LEGAL_SIGNAL_MIN_HITS`` constants moved here
from ``content_organizer.py`` (which keeps ``_LEGAL_DOCUMENT_SIGNALS`` /
``_LEGAL_SIGNAL_MIN_HITS`` aliases so the legacy veto and its importers keep
working unchanged).

On court documents this signal is DESIGNED to outscore ``PersonalDocSignal``
in aggregate: ``W_LEGAL (0.85) × confidence`` plus text-signal reinforcement
beats ``W_PERSON (0.9) × confidence`` — court notices rarely pass the human
name gate, so the person emission is usually the ungated 0.4. Golden tests
in a later wave pin that competition (§8.3 "legal-outscores-personal").

SSRN/research false positives ("agreement" in paper abstracts) are
suppressed by the filename research rules and by co-occurrence with org and
person evidence, not by this signal.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple

from ..types import EVIDENCE_PEOPLE, CategoryScore
from ..weights import W_LEGAL

# Legal-document signal vocabulary. Court documents carry clerk contact
# blocks that satisfy the generic person/contacts indicators and were
# misfiled under Personal/Contacts (e.g. "NOTICE OF CT SETTING"). When at
# least LEGAL_SIGNAL_MIN_HITS of these appear, the legacy person tier defers
# (hard veto) so content analysis decides; in the unified scorer this signal
# emits a competing legal score instead. Person attribution still lands via
# ``people_names`` evidence regardless of the winner.
LEGAL_DOCUMENT_SIGNALS = frozenset(
    {
        "court",
        "cause no",
        "docket",
        "plaintiff",
        "defendant",
        "hearing",
        "petitioner",
        "respondent",
        "judicial",
    }
)
LEGAL_SIGNAL_MIN_HITS = 2

# Minimum extracted-text length for legal detection (parallel to the other
# mid-tier text signals' 50-char gate).
LEGAL_MIN_TEXT_CHARS = 50

# Hit-scaled confidence: base at exactly LEGAL_SIGNAL_MIN_HITS hits, plus one
# increment per additional distinct signal, capped at LEGAL_CONFIDENCE_MAX.
LEGAL_CONFIDENCE_BASE = 0.7
LEGAL_CONFIDENCE_PER_HIT = 0.1
LEGAL_CONFIDENCE_MAX = 1.0

# Secondary emission when personal-legal cues (dui/citation/traffic ticket/
# dmv/…) are present: personal/legal competes alongside legal/{subcat} and
# aggregation sorts the rest.
LEGAL_PERSONAL_CONFIDENCE = 0.5

LEGAL_CATEGORY = "legal"
LEGAL_DEFAULT_SUBCATEGORY = "other"
PERSONAL_CATEGORY = "personal"
PERSONAL_LEGAL_SUBCATEGORY = "legal"

# ContentClassifier.patterns lookup keys.
PATTERNS_LEGAL_KEY = "legal"
PATTERNS_PERSONAL_KEY = "personal"
PATTERNS_SUBCATEGORIES_KEY = "subcategories"

# Signal-local evidence keys (EVIDENCE_PEOPLE is the cross-cutting one).
EVIDENCE_LEGAL_HITS = "legal_hits"
EVIDENCE_MATCHED_SIGNALS = "matched_signals"
EVIDENCE_PERSONAL_LEGAL_CUES = "personal_legal_cues"


def count_legal_signals(text_lower: str) -> Tuple[int, List[str]]:
    """Distinct LEGAL_DOCUMENT_SIGNALS present in the text (count, sorted)."""
    matched = sorted(kw for kw in LEGAL_DOCUMENT_SIGNALS if kw in text_lower)
    return len(matched), matched


def legal_confidence(hit_count: int) -> float:
    """Hit-scaled confidence: base at the minimum hits, +PER_HIT per extra."""
    extra_hits = max(hit_count - LEGAL_SIGNAL_MIN_HITS, 0)
    return min(LEGAL_CONFIDENCE_BASE + LEGAL_CONFIDENCE_PER_HIT * extra_hits, LEGAL_CONFIDENCE_MAX)


def score_legal_subcategory(text_lower: str, subcategories: dict) -> str:
    """Best legal subcategory by keyword occurrence counts.

    Mirrors ``ContentClassifier.classify_content`` subcategory scoring
    (sum of ``text.count(keyword)`` per subcategory, first maximum wins);
    defaults to ``LEGAL_DEFAULT_SUBCATEGORY`` when nothing matches.
    """
    best_subcategory = LEGAL_DEFAULT_SUBCATEGORY
    best_count = 0
    for subcategory, keywords in subcategories.items():
        count = sum(text_lower.count(kw.lower()) for kw in keywords)
        if count > best_count:
            best_count = count
            best_subcategory = subcategory
    return best_subcategory


def match_personal_legal_cues(text_lower: str, cues: Iterable[str]) -> List[str]:
    """Personal-legal cue keywords present in the text (cue-list order)."""
    return [cue for cue in cues if cue.lower() in text_lower]


class LegalContentSignal:
    """Legal document signals → ``legal/{subcat}`` (+ ``personal/legal``)."""

    name = "legal_content"
    weight = W_LEGAL
    cost_tier = "mid"

    def __init__(self, classifier: Any) -> None:
        # ContentClassifier: patterns dict for subcategory vocabularies and
        # extract_people_names for Option C graph-edge evidence.
        self._classifier = classifier

    def applies_to(self, ctx: Any) -> bool:
        return bool(ctx.text_length >= LEGAL_MIN_TEXT_CHARS)

    def run(self, ctx: Any) -> List[CategoryScore]:
        text = ctx.ensure_text()
        text_lower = text.lower()

        hits, matched_signals = count_legal_signals(text_lower)
        if hits < LEGAL_SIGNAL_MIN_HITS:
            return []

        people = list(self._classifier.extract_people_names(text) or [])
        base_evidence = {
            EVIDENCE_PEOPLE: people,
            EVIDENCE_LEGAL_HITS: hits,
            EVIDENCE_MATCHED_SIGNALS: matched_signals,
        }

        legal_subcategories = self._classifier.patterns[PATTERNS_LEGAL_KEY][
            PATTERNS_SUBCATEGORIES_KEY
        ]
        subcategory = score_legal_subcategory(text_lower, legal_subcategories)
        scores = [
            CategoryScore(
                category=LEGAL_CATEGORY,
                subcategory=subcategory,
                confidence=legal_confidence(hits),
                signal_name=self.name,
                evidence=dict(base_evidence),
            )
        ]

        personal_cues = self._classifier.patterns[PATTERNS_PERSONAL_KEY][
            PATTERNS_SUBCATEGORIES_KEY
        ].get(PERSONAL_LEGAL_SUBCATEGORY, [])
        matched_cues = match_personal_legal_cues(text_lower, personal_cues)
        if matched_cues:
            personal_evidence = dict(base_evidence)
            personal_evidence[EVIDENCE_PERSONAL_LEGAL_CUES] = matched_cues
            scores.append(
                CategoryScore(
                    category=PERSONAL_CATEGORY,
                    subcategory=PERSONAL_LEGAL_SUBCATEGORY,
                    confidence=LEGAL_PERSONAL_CONFIDENCE,
                    signal_name=self.name,
                    evidence=personal_evidence,
                )
            )
        return scores
