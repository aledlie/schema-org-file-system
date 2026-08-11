"""Layered, local-only person-name confidence gate.

Replaces the leaky substring denylist with a composite score from several weak
signals, routed three ways (auto_accept / review / reject). Designed per
``docs/plans/PERSON_NAME_VALIDATION_PLAN.md``.

Layers (each optional; an unavailable layer scores ``None`` and is dropped from
the composite so the gate degrades gracefully):

    L0 denylist     fast-path reject (absorbs graph_store._PERSON_NAME_DENYLIST)
    L1 nameparser   shape: non-empty first AND last
    L2 probablepeople  CRF tag type must be 'Person'
    L3 gazetteer    Census given-name + surname membership

The composite is a weighted mean over available layers; ``>= AUTO_ACCEPT`` →
auto_accept, ``<= REJECT`` → reject, else review. Two hard rules bias ambiguity
toward review (never auto_accept): a failed shape (L1) caps routing at review,
and a zero gazetteer (L3) alone never forces reject when L1+L2 both pass
(non-Anglo-name bias guard).

No network calls. All external libraries are imported lazily inside try/except
so ``src/classifiers`` works without the ``names`` extra installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Tuple

RouteDecision = Literal["auto_accept", "review", "reject"]

# Routing thresholds on the composite score (module constants, tunable).
AUTO_ACCEPT_THRESHOLD = 0.75
REJECT_THRESHOLD = 0.30

# Per-layer weights (renormalized over the layers that are actually available).
_WEIGHT_SHAPE = 0.2
_WEIGHT_PROBABLEPEOPLE = 0.4
_WEIGHT_GAZETTEER = 0.4

# L0 denylist: case-insensitive substrings that mark an obvious non-person
# (organization / event / meeting names misdetected as people). Authoritative
# copy; graph_store's read-time filter and private copy were removed in Phase 3.
PERSON_NAME_DENYLIST: Tuple[str, ...] = (
    "studio",
    "meeting",
    "member id",
    "inc",
    "llc",
    "corp",
    "company",
    "services",
    "department",
    "district",
    "county",
    "agency",
    "bureau",
    "commission",
    "authority",
    "association",
    "foundation",
    "institute",
    "university",
    "hospital",
    "clinic",
    "center",
    "centre",
    "council",
    "committee",
    "society",
    "trust",
    "group",
    "partners",
    "camp",
    # Insurance/policy document-heading vocabulary — ALL-CAPS headings like
    # "INSURANCE POLICY" match the broad roster pattern and surface as
    # title-case bigrams ("Insurance Policy").
    "insurance",
    "policy",
    "premium",
    "deductible",
    "coverage",
)

# Word-boundary matched so a denylist term is only a hit as a whole word —
# "inc" must NOT reject "Vincent"/"Lincoln", "corp" must not reject a name
# containing that substring. Multi-word terms ("member id") are matched intact.
_DENYLIST_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in PERSON_NAME_DENYLIST) + r")\b"
)

_GAZETTEER_DIR = Path(__file__).resolve().parent / "data" / "census_names"

# Ambiguous given names: common English words (seasons, months, virtues, natural
# phenomena) that appear in Census given-name lists but are equally or more common
# as non-person words (location names, event names, organizations).  When the
# first token of a candidate name is one of these, we cannot distinguish "Summer
# Hill" (the neighborhood / event) from "Summer Hill" (a person) using the
# gazetteer alone, so auto_accept is capped at review — a human can confirm.
#
# Trade-off: real people named May, June, Summer, etc. route to pending_review
# instead of auto_accept. Per the design principle ("a false Person/{Name}/
# folder is worse than a missed person") this is the correct side to err on.
# Derivation: every word in this set (a) appears in Census given_names.txt and
# (b) is also a common English noun/adjective/month that regularly appears in
# non-personal document headings, event names, and location references.
_AMBIGUOUS_GIVEN_NAMES: frozenset = frozenset(
    {
        # Seasons
        "summer",
        "spring",
        "autumn",
        "winter",
        # Months commonly used as given names (March/July/October/November/December
        # are rarely used as first names and not in the gazetteer).
        "april",
        "may",
        "june",
        "august",
        # Time of day / nature phenomena
        "dawn",
        "eve",
        # Virtue / abstract noun names
        "faith",
        "hope",
        "grace",
        "joy",
        "amber",
        "sage",
        # Role / job words sometimes used as given names
        "hunter",
        # Nature / toponym words
        "brook",
    }
)


@dataclass(frozen=True)
class PersonNameValidation:
    """Outcome of :func:`validate_person_name`."""

    name: str
    decision: RouteDecision
    score: float
    layer_scores: Dict[str, Optional[float]]
    reasons: List[str]


def _normalize(name: str) -> str:
    """Match extract_people_names' ALL-CAPS→Title-case normalization."""
    clean = " ".join((name or "").split())
    if clean.isupper():
        clean = clean.title()
    return clean


def is_denylisted(name: str) -> bool:
    """L0-only check: ``name`` contains a whole-word denylist term.

    Cheap enough for extraction-time filtering (no optional scoring layers),
    so document-heading bigrams like "Insurance Policy" never enter the
    people-name stream at all.
    """
    return _DENYLIST_RE.search(_normalize(name).lower()) is not None


# --------------------------------------------------------------------------- #
# Layer availability (imports guarded; data files optional)                    #
# --------------------------------------------------------------------------- #


def _nameparser_available() -> bool:
    try:
        import nameparser  # noqa: F401

        return True
    except ImportError:
        return False


def _probablepeople_available() -> bool:
    try:
        import probablepeople  # noqa: F401

        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _load_gazetteer() -> Optional[Tuple[Set[str], Set[str]]]:
    """Load (given_names, surnames) sets, or None if data files are absent."""
    given_path = _GAZETTEER_DIR / "given_names.txt"
    surname_path = _GAZETTEER_DIR / "surnames.txt"
    if not given_path.exists() or not surname_path.exists():
        return None
    given = {line.strip() for line in given_path.read_text().splitlines() if line.strip()}
    surnames = {line.strip() for line in surname_path.read_text().splitlines() if line.strip()}
    if not given or not surnames:
        return None
    return given, surnames


def available_layers() -> Dict[str, bool]:
    """Report which optional layers are usable (for ``organize-files health``)."""
    return {
        "denylist": True,
        "shape": _nameparser_available(),
        "probablepeople": _probablepeople_available(),
        "gazetteer": _load_gazetteer() is not None,
    }


# --------------------------------------------------------------------------- #
# Per-layer scorers                                                            #
# --------------------------------------------------------------------------- #


def _score_shape(name: str) -> Optional[float]:
    if not _nameparser_available():
        return None
    from nameparser import HumanName

    hn = HumanName(name)
    return 1.0 if (hn.first and hn.last) else 0.0


def _score_probablepeople(name: str) -> Optional[float]:
    if not _probablepeople_available():
        return None
    import probablepeople as pp

    try:
        _tagged, name_type = pp.tag(name)
    except pp.RepeatedLabelError:
        return 0.5
    if name_type == "Person":
        return 1.0
    if name_type in ("Corporation", "Household"):
        return 0.0
    return 0.5


def _score_gazetteer(name: str) -> Optional[float]:
    gaz = _load_gazetteer()
    if gaz is None:
        return None
    given, surnames = gaz
    tokens = [t.strip(".,").lower() for t in name.split() if t.strip(".,")]
    if len(tokens) < 2:
        # Single token can't be first+last; treat as a miss, not unavailable.
        return 0.0
    first_hit = tokens[0] in given
    last_hit = tokens[-1] in surnames
    if first_hit and last_hit:
        return 1.0
    if first_hit or last_hit:
        return 0.5
    return 0.0


# --------------------------------------------------------------------------- #
# Composite + routing                                                          #
# --------------------------------------------------------------------------- #


def validate_person_name(name: str) -> PersonNameValidation:
    """Score ``name`` across all available layers and route it three ways."""
    clean = _normalize(name)
    reasons: List[str] = []
    layer_scores: Dict[str, Optional[float]] = {
        "denylist": None,
        "shape": None,
        "probablepeople": None,
        "gazetteer": None,
    }

    # L0 denylist — immediate reject, short-circuit (whole-word match).
    match = _DENYLIST_RE.search(clean.lower())
    if match is not None:
        layer_scores["denylist"] = 0.0
        reasons.append(f"denylist: contains {match.group(0)!r}")
        return PersonNameValidation(clean, "reject", 0.0, layer_scores, reasons)
    layer_scores["denylist"] = 1.0

    shape = _score_shape(clean)
    pp_score = _score_probablepeople(clean)
    gaz = _score_gazetteer(clean)
    layer_scores.update(shape=shape, probablepeople=pp_score, gazetteer=gaz)

    weighted: List[Tuple[float, float]] = []  # (weight, score)
    if shape is not None:
        weighted.append((_WEIGHT_SHAPE, shape))
        reasons.append(f"shape={shape:.0%}")
    if pp_score is not None:
        weighted.append((_WEIGHT_PROBABLEPEOPLE, pp_score))
        reasons.append(f"probablepeople={pp_score:.0%}")
    if gaz is not None:
        weighted.append((_WEIGHT_GAZETTEER, gaz))
        reasons.append(f"gazetteer={gaz:.0%}")

    if weighted:
        total_w = sum(w for w, _ in weighted)
        composite = sum(w * s for w, s in weighted) / total_w
    else:
        # No optional layers installed: only the denylist ran. Never
        # auto_accept on nothing — route to review.
        composite = 0.5
        reasons.append("no optional layers available → review")

    # Hard rules (bias ambiguity toward review, never toward auto_accept).
    shape_failed = shape == 0.0
    # Partial gazetteer corroboration: only ONE of first/last is a known
    # Census name. Common for event/org names that end in a word coinciding
    # with a surname ("Morning Train") — probablepeople still tags these
    # 'Person', so without this guard they auto_accept and spawn a spurious
    # Person/{Name}/ folder. Requiring BOTH names known for auto_accept keeps
    # precision high; unknown/non-Anglo names route to the review queue.
    gazetteer_partial = gaz is not None and gaz < 1.0
    # Ambiguous given name: first token is a common English word (season, month,
    # virtue, natural phenomenon) that also appears in Census given-name lists.
    # When gaz=1.0 with such a first token, the gazetteer cannot distinguish a
    # person ("Summer Hill") from a location/event ("Summer Hill Festival") —
    # both score identically. Cap at review so a human can confirm.
    # Derivation: see _AMBIGUOUS_GIVEN_NAMES constant above.
    tokens_lower = clean.lower().split()
    ambiguous_given = (
        gaz is not None
        and gaz >= 1.0  # would otherwise satisfy the gazetteer guard
        and bool(tokens_lower)
        and tokens_lower[0] in _AMBIGUOUS_GIVEN_NAMES
    )

    if composite >= AUTO_ACCEPT_THRESHOLD:
        decision: RouteDecision = "auto_accept"
    elif composite <= REJECT_THRESHOLD:
        decision = "reject"
    else:
        decision = "review"

    if decision == "auto_accept" and shape_failed:
        decision = "review"
        reasons.append("shape failed → capped at review")
    if decision == "auto_accept" and gazetteer_partial:
        decision = "review"
        reasons.append("gazetteer not fully corroborated → capped at review")
    if decision == "auto_accept" and ambiguous_given:
        decision = "review"
        reasons.append(f"ambiguous given name {tokens_lower[0]!r} → capped at review")

    return PersonNameValidation(clean, decision, round(composite, 4), layer_scores, reasons)
