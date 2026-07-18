"""Scorer: run registered signals in cost-tier waves and aggregate.

UNIFIED_SCORING_PLAN §3.3. Generalizes the shipped two-signal
``_merge_clip_text_scores`` image scorer to N signals × all files:

- Signals run in waves (cheap → mid → heavy, registry order within a wave);
  later waves are skipped once the best aggregate reaches
  ``EARLY_EXIT_CONFIDENCE``.
- ``score(cat, sub) = Σ over signals (signal.weight × confidence)`` for
  matching keys; duplicate (cat, sub) entries from the same signal dedupe by
  max confidence. The legacy agreement boost is subsumed by summation.
- Deterministic tie-breaking: higher aggregate → more distinct contributing
  signals → higher cost-tier among contributors → earliest registry order →
  first emission.
- Decisions below ``MIN_DECISION_CONFIDENCE`` (aggregate) or
  ``MIN_DECISION_MARGIN`` (lead over the best runner-up in a *different*
  category) route to ``LOW_CONFIDENCE_FALLBACK`` with the state recorded for
  telemetry. The margin is category-level: same-category subcategory rivals do
  not gate the commit (BACKLOG Phase-3 item #3).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast

from .types import (
    COST_TIER_ORDER,
    COST_TIER_PRIORITY,
    EVIDENCE_COMPANY,
    EVIDENCE_PEOPLE,
    EVIDENCE_SCHEMA_TYPE,
    CategoryScore,
    ClassificationDecision,
    Signal,
)
from .weights import (
    EARLY_EXIT_CONFIDENCE,
    LOW_CONFIDENCE_FALLBACK,
    MIN_DECISION_CONFIDENCE,
    MIN_DECISION_MARGIN,
)

CategoryKey = Tuple[str, str]


class Scorer:
    """Aggregates per-signal CategoryScores into one ClassificationDecision."""

    def __init__(
        self,
        signals: Sequence[Signal],
        *,
        early_exit_confidence: float = EARLY_EXIT_CONFIDENCE,
        min_decision_confidence: float = MIN_DECISION_CONFIDENCE,
        min_decision_margin: float = MIN_DECISION_MARGIN,
    ) -> None:
        self._signals: List[Signal] = list(signals)
        self._early_exit_confidence = early_exit_confidence
        self._min_decision_confidence = min_decision_confidence
        self._min_decision_margin = min_decision_margin

        seen: Dict[str, int] = {}
        for index, signal in enumerate(self._signals):
            if signal.cost_tier not in COST_TIER_PRIORITY:
                raise ValueError(
                    f"Signal {signal.name!r} has unknown cost_tier {signal.cost_tier!r}"
                )
            if signal.name in seen:
                raise ValueError(f"Duplicate signal name {signal.name!r} in registry")
            seen[signal.name] = index
        # name → (registry index, weight, cost tier); registry order is the
        # deterministic fallback for tie-breaking and entity precedence.
        self._by_name: Dict[str, Tuple[int, float, str]] = {
            signal.name: (index, signal.weight, signal.cost_tier)
            for index, signal in enumerate(self._signals)
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def classify(self, ctx: Any) -> ClassificationDecision:
        collected = self._run_waves(ctx)
        return self._decide(ctx, collected)

    # ------------------------------------------------------------------ #
    # Wave execution                                                       #
    # ------------------------------------------------------------------ #

    def _run_waves(self, ctx: Any) -> List[CategoryScore]:
        collected: List[CategoryScore] = []
        for tier_index, tier in enumerate(COST_TIER_ORDER):
            for signal in self._signals:
                if signal.cost_tier != tier:
                    continue
                try:
                    if not signal.applies_to(ctx):
                        continue
                    scores = signal.run(ctx) or []
                    deduped = self._dedupe_within_signal(signal, scores)
                except Exception as exc:  # one broken signal must not kill the file
                    print(f"  Signal {signal.name} error: {exc}")
                    continue
                collected.extend(deduped)
            is_last_tier = tier_index == len(COST_TIER_ORDER) - 1
            if not is_last_tier and self._best_total(collected) >= self._early_exit_confidence:
                break
        return collected

    @staticmethod
    def _dedupe_within_signal(
        signal: Signal, scores: Iterable[CategoryScore]
    ) -> List[CategoryScore]:
        """Keep one entry per (cat, sub) for a single signal — max confidence."""
        best: Dict[CategoryKey, CategoryScore] = {}
        order: List[CategoryKey] = []
        for score in scores:
            if score.signal_name != signal.name:
                raise ValueError(
                    f"Signal {signal.name!r} emitted a CategoryScore tagged "
                    f"{score.signal_name!r}"
                )
            key = (score.category, score.subcategory)
            if key not in best:
                best[key] = score
                order.append(key)
            elif score.confidence > best[key].confidence:
                best[key] = score
        return [best[key] for key in order]

    def _best_total(self, collected: List[CategoryScore]) -> float:
        totals = self._aggregate(collected)[0]
        return max(totals.values()) if totals else 0.0

    # ------------------------------------------------------------------ #
    # Aggregation + decision                                               #
    # ------------------------------------------------------------------ #

    def _aggregate(
        self, collected: List[CategoryScore]
    ) -> Tuple[
        Dict[CategoryKey, float], Dict[CategoryKey, Dict[str, float]], Dict[CategoryKey, int]
    ]:
        """Raw weighted sums, per-candidate contributor map, first-seen order."""
        totals: Dict[CategoryKey, float] = {}
        contributors: Dict[CategoryKey, Dict[str, float]] = {}
        first_seen: Dict[CategoryKey, int] = {}
        for position, score in enumerate(collected):
            _, weight, _ = self._by_name[score.signal_name]
            confidence = min(max(score.confidence, 0.0), 1.0)
            weighted = weight * confidence
            key = (score.category, score.subcategory)
            totals[key] = totals.get(key, 0.0) + weighted
            contributors.setdefault(key, {})[score.signal_name] = weighted
            first_seen.setdefault(key, position)
        return totals, contributors, first_seen

    def _decide(self, ctx: Any, collected: List[CategoryScore]) -> ClassificationDecision:
        totals, contributors, first_seen = self._aggregate(collected)

        if not totals:
            fallback_category, fallback_subcategory = LOW_CONFIDENCE_FALLBACK
            return ClassificationDecision(
                category=fallback_category,
                subcategory=fallback_subcategory,
                schema_type=ctx.schema_type,
                confidence=0.0,
                margin=0.0,
                winning_signals=[],
                all_scores=collected,
                company_name=self._merge_company(collected, winning_names=()),
                people_names=self._merge_people(collected),
                decision_state="low_confidence",
            )

        def sort_key(key: CategoryKey) -> Tuple[float, int, int, int, int]:
            candidate_contributors = contributors[key]
            best_tier = max(
                COST_TIER_PRIORITY[self._by_name[name][2]] for name in candidate_contributors
            )
            earliest_registry = min(self._by_name[name][0] for name in candidate_contributors)
            return (
                totals[key],
                len(candidate_contributors),
                best_tier,
                -earliest_registry,
                -first_seen[key],
            )

        winner = max(totals, key=sort_key)
        raw_total = totals[winner]
        # The margin gate adjudicates the CATEGORY (folder) decision. A
        # runner-up sharing the winner's category is not category ambiguity —
        # a file whose top candidates are all e.g. personal/* is unambiguously
        # personal, so the winning subcategory commits instead of falling back
        # (BACKLOG Phase-3 item #3). Only a rival in a DIFFERENT category
        # counts against the margin; same-category subcategory competition is
        # settled by the argmax winner above.
        winner_category = winner[0]
        cross_category_totals = [
            total for key, total in totals.items() if key[0] != winner_category
        ]
        runner_up = max(cross_category_totals, default=None)
        margin = raw_total - runner_up if runner_up is not None else raw_total

        winning_names = tuple(sorted(contributors[winner], key=lambda name: self._by_name[name][0]))

        if raw_total < self._min_decision_confidence:
            decision_state = "low_confidence"
            category, subcategory = LOW_CONFIDENCE_FALLBACK
        elif margin < self._min_decision_margin:
            decision_state = "low_margin"
            category, subcategory = LOW_CONFIDENCE_FALLBACK
        else:
            decision_state = "committed"
            category, subcategory = winner

        schema_type = ctx.schema_type
        if decision_state == "committed":
            schema_type = (
                self._schema_type_override(collected, winner, winning_names) or schema_type
            )

        return ClassificationDecision(
            category=category,
            subcategory=subcategory,
            schema_type=schema_type,
            confidence=min(raw_total, 1.0),
            margin=margin,
            winning_signals=list(winning_names),
            all_scores=collected,
            company_name=self._merge_company(collected, winning_names),
            people_names=self._merge_people(collected),
            decision_state=decision_state,
        )

    # ------------------------------------------------------------------ #
    # Entity + schema-type assembly (§4 "entity side-channel")             #
    # ------------------------------------------------------------------ #

    def _iter_registry_order(self, collected: List[CategoryScore]) -> List[CategoryScore]:
        return sorted(
            collected,
            key=lambda score: (self._by_name[score.signal_name][0],),
        )

    def _merge_company(
        self, collected: List[CategoryScore], winning_names: Tuple[str, ...]
    ) -> Optional[str]:
        """First non-empty company: winner contributors first, registry order."""
        ordered = self._iter_registry_order(collected)
        for scores in (
            [s for s in ordered if s.signal_name in winning_names],
            ordered,
        ):
            for score in scores:
                company = score.evidence.get(EVIDENCE_COMPANY)
                if company:
                    return cast(Optional[str], company)
        return None

    def _merge_people(self, collected: List[CategoryScore]) -> List[str]:
        """Ordered union of people across ALL signals (Option C: person
        attribution is a graph relationship, independent of the winner)."""
        people: List[str] = []
        for score in self._iter_registry_order(collected):
            for name in score.evidence.get(EVIDENCE_PEOPLE) or []:
                if name and name not in people:
                    people.append(name)
        return people

    def _schema_type_override(
        self,
        collected: List[CategoryScore],
        winner: CategoryKey,
        winning_names: Tuple[str, ...],
    ) -> Optional[str]:
        """schema_type from the winner's contributors, registry order."""
        for score in self._iter_registry_order(collected):
            if score.signal_name not in winning_names:
                continue
            if (score.category, score.subcategory) != winner:
                continue
            override = score.evidence.get(EVIDENCE_SCHEMA_TYPE)
            if override:
                return cast(Optional[str], override)
        return None
