"""Core interfaces for the unified scoring engine.

See docs/architecture/UNIFIED_SCORING_PLAN.md §3.2. Every signal is a pure
function over a :class:`~src.scoring.context.FileContext`; the
:class:`~src.scoring.scorer.Scorer` aggregates their
:class:`CategoryScore` emissions into one :class:`ClassificationDecision`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from .context import FileContext

# Scorer modes accepted by ``organize-files content --scorer`` and
# ``ContentOrganizer(scorer=...)``. ``legacy`` is the 10-tier priority chain;
# ``unified`` is the weighted scorer; ``shadow`` runs both (legacy controls
# placement, the unified decision is logged for disagreement analysis).
# ``SCORER_DEFAULT`` is the default for the CLI, ``ContentBasedFileOrganizer``,
# and now the base ``ContentOrganizer``; tests that exercise the legacy chain
# pass ``scorer=SCORER_LEGACY`` explicitly (Phase-5 default flip).
SCORER_LEGACY = "legacy"
SCORER_UNIFIED = "unified"
SCORER_SHADOW = "shadow"
SCORER_MODES = (SCORER_LEGACY, SCORER_UNIFIED, SCORER_SHADOW)
SCORER_DEFAULT = SCORER_UNIFIED  # default engine (was legacy before the unified rollout)

CostTier = Literal["cheap", "mid", "heavy"]

# Wave execution order: cheap signals run first, heavy last (§3.3). The
# scorer may stop before a later wave when the aggregate already exceeds
# ``EARLY_EXIT_CONFIDENCE``.
COST_TIER_ORDER: tuple = ("cheap", "mid", "heavy")

# Tie-break priority among a candidate's contributing signals: heavy signals
# are content-aware, so heavy > mid > cheap (§3.3 tie-break #3).
COST_TIER_PRIORITY: Dict[str, int] = {"cheap": 0, "mid": 1, "heavy": 2}

# ``committed``: winner cleared both decision thresholds.
# ``low_confidence``: aggregate below MIN_DECISION_CONFIDENCE (routed to the
#   fallback bucket).
# ``low_margin``: winner led by less than MIN_DECISION_MARGIN (also routed to
#   the fallback bucket pending Open Question #1).
DecisionState = Literal["committed", "low_confidence", "low_margin"]

# Evidence keys with cross-cutting meaning (any other key is signal-local):
# - ``company_name`` (str): merged into ClassificationDecision.company_name.
# - ``people_names`` (list[str]): unioned into decision.people_names
#   regardless of the winning category (Option C graph edges).
# - ``schema_type`` (str): overrides the context schema_type when the emitting
#   signal contributes to the winner (e.g. research → ScholarlyArticle).
# - ``event_name`` (str): detected event title; the organizer routes a
#   committed ``events`` winner to Events/{EventName}/ (mirrors company_name's
#   Organization/{OrgName}/ role, threaded via the _last_file_state stash).
EVIDENCE_COMPANY = "company_name"
EVIDENCE_PEOPLE = "people_names"
EVIDENCE_SCHEMA_TYPE = "schema_type"
EVIDENCE_EVENT_NAME = "event_name"


@dataclass(frozen=True)
class CategoryScore:
    """One signal's vote for a (category, subcategory) with local confidence."""

    category: str
    subcategory: str
    confidence: float  # signal-local, [0, 1]
    signal_name: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Signal(Protocol):
    """A registered classification signal (§3.2).

    Implementations must be pure over the context: no I/O outside clients
    injected at construction, no reliance on organizer instance state.
    """

    name: str
    weight: float
    cost_tier: str

    def applies_to(self, ctx: "FileContext") -> bool: ...

    def run(self, ctx: "FileContext") -> List["CategoryScore"]: ...


@dataclass(frozen=True)
class ClassificationDecision:
    """Aggregated scoring outcome for one file (§5.3).

    ``confidence`` is the argmax candidate's aggregate clamped to [0, 1];
    thresholds operate on the raw (unclamped) aggregate. ``margin`` is the raw
    lead over the best runner-up in a *different* category (the raw aggregate
    itself when no other-category candidate exists) — same-category
    subcategory rivals do not count, so an unambiguous category commits its
    best subcategory. ``winning_signals`` always describes the argmax
    candidate, even when ``decision_state`` routed the file to the fallback
    bucket.
    """

    category: str
    subcategory: str
    schema_type: str
    confidence: float
    margin: float
    winning_signals: List[str]
    all_scores: List[CategoryScore]
    company_name: Optional[str]
    people_names: List[str]
    decision_state: str = "committed"
