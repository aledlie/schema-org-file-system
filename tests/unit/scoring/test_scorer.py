"""Scorer aggregation tests (UNIFIED_SCORING_PLAN §8.2).

Covers empty inputs, single/conflicting signals, tie-break orderings,
early-exit, low-confidence rejection, and margin routing — all against
synthetic signals with no extraction dependencies.
"""

from pathlib import Path
from typing import List

import pytest

from src.scoring.context import FileContext
from src.scoring.scorer import Scorer
from src.scoring.types import CategoryScore
from src.scoring.weights import LOW_CONFIDENCE_FALLBACK


class FakeSignal:
    """Minimal Signal implementation for scorer tests."""

    def __init__(
        self,
        name,
        weight,
        cost_tier,
        scores=None,
        applies=True,
        error=None,
    ):
        self.name = name
        self.weight = weight
        self.cost_tier = cost_tier
        self._scores = scores or []
        self._applies = applies
        self._error = error
        self.run_count = 0

    def applies_to(self, ctx) -> bool:
        return self._applies

    def run(self, ctx) -> List[CategoryScore]:
        self.run_count += 1
        if self._error is not None:
            raise self._error
        return [
            CategoryScore(
                category=cat,
                subcategory=sub,
                confidence=conf,
                signal_name=self.name,
                evidence=evidence or {},
            )
            for cat, sub, conf, evidence in self._scores
        ]


def make_ctx(schema_type="DigitalDocument"):
    return FileContext(path=Path("/tmp/example.pdf"), schema_type=schema_type)


def score_entry(cat, sub, conf, evidence=None):
    return (cat, sub, conf, evidence)


class TestAggregation:
    def test_no_signals_returns_low_confidence_fallback(self):
        decision = Scorer([]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == LOW_CONFIDENCE_FALLBACK
        assert decision.decision_state == "low_confidence"
        assert decision.confidence == 0.0
        assert decision.winning_signals == []

    def test_single_strong_signal_commits(self):
        signal = FakeSignal(
            "filename", 1.1, "cheap", [score_entry("financial", "invoices", 0.9)]
        )
        decision = Scorer([signal]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("financial", "invoices")
        assert decision.decision_state == "committed"
        assert decision.winning_signals == ["filename"]
        # Raw aggregate 0.99 stays below the clamp.
        assert decision.confidence == pytest.approx(0.99)

    def test_confidence_clamped_to_one(self):
        signals = [
            FakeSignal("a", 1.1, "cheap", [score_entry("legal", "contracts", 1.0)]),
            FakeSignal("b", 0.8, "cheap", [score_entry("legal", "contracts", 1.0)]),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert decision.confidence == 1.0
        assert decision.margin == pytest.approx(1.9)

    def test_cross_signal_scores_sum(self):
        signals = [
            FakeSignal("text", 0.8, "cheap", [score_entry("legal", "contracts", 0.5)]),
            FakeSignal("org", 1.0, "cheap", [score_entry("legal", "contracts", 0.4)]),
            FakeSignal("game", 0.8, "cheap", [score_entry("game_assets", "textures", 0.6)]),
        ]
        decision = Scorer(signals).classify(make_ctx())
        # legal: 0.8*0.5 + 1.0*0.4 = 0.80 beats game: 0.8*0.6 = 0.48
        assert (decision.category, decision.subcategory) == ("legal", "contracts")
        assert decision.margin == pytest.approx(0.80 - 0.48)
        assert decision.winning_signals == ["text", "org"]

    def test_same_signal_duplicate_key_dedupes_by_max(self):
        signal = FakeSignal(
            "text",
            1.0,
            "cheap",
            [
                score_entry("legal", "contracts", 0.3),
                score_entry("legal", "contracts", 0.7),
                score_entry("legal", "contracts", 0.5),
            ],
        )
        decision = Scorer([signal]).classify(make_ctx())
        assert decision.confidence == pytest.approx(0.7)

    def test_out_of_range_confidence_clamped(self):
        signals = [
            FakeSignal("hot", 1.0, "cheap", [score_entry("media", "photos_other", 1.7)]),
            FakeSignal("cold", 1.0, "cheap", [score_entry("technical", "other", -0.4)]),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("media", "photos_other")
        assert decision.confidence == 1.0


class TestTieBreaks:
    """Tie-breaking is orthogonal to margin gating: exact ties have margin 0,
    so these scorers disable the margin threshold to expose the argmax pick."""

    @staticmethod
    def tie_scorer(signals):
        return Scorer(signals, min_decision_margin=0.0)

    def test_more_distinct_signals_wins_on_equal_score(self):
        signals = [
            FakeSignal("solo", 1.0, "cheap", [score_entry("technical", "other", 0.8)]),
            FakeSignal("pair_a", 1.0, "cheap", [score_entry("legal", "contracts", 0.4)]),
            FakeSignal("pair_b", 1.0, "cheap", [score_entry("legal", "contracts", 0.4)]),
        ]
        decision = self.tie_scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("legal", "contracts")

    def test_higher_cost_tier_wins_on_equal_score_and_count(self):
        signals = [
            FakeSignal("cheap_one", 1.0, "cheap", [score_entry("technical", "other", 0.8)]),
            FakeSignal("heavy_one", 1.0, "heavy", [score_entry("legal", "contracts", 0.8)]),
        ]
        decision = self.tie_scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("legal", "contracts")

    def test_registry_order_breaks_remaining_ties(self):
        signals = [
            FakeSignal("first", 1.0, "cheap", [score_entry("legal", "contracts", 0.8)]),
            FakeSignal("second", 1.0, "cheap", [score_entry("technical", "other", 0.8)]),
        ]
        decision = self.tie_scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("legal", "contracts")

    def test_emission_order_is_final_fallback(self):
        signal = FakeSignal(
            "multi",
            1.0,
            "cheap",
            [
                score_entry("legal", "contracts", 0.8),
                score_entry("technical", "other", 0.8),
            ],
        )
        decision = self.tie_scorer([signal]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("legal", "contracts")


class TestWavesAndEarlyExit:
    def test_early_exit_skips_later_waves(self):
        heavy = FakeSignal("clip", 0.7, "heavy", [score_entry("media", "photos_other", 0.9)])
        cheap = FakeSignal("filename", 1.1, "cheap", [score_entry("financial", "invoices", 0.95)])
        decision = Scorer([cheap, heavy]).classify(make_ctx())
        assert heavy.run_count == 0
        assert (decision.category, decision.subcategory) == ("financial", "invoices")

    def test_no_early_exit_below_threshold(self):
        heavy = FakeSignal("clip", 0.7, "heavy", [score_entry("media", "photos_other", 0.9)])
        cheap = FakeSignal("filename", 1.1, "cheap", [score_entry("financial", "invoices", 0.5)])
        Scorer([cheap, heavy]).classify(make_ctx())
        assert heavy.run_count == 1

    def test_early_exit_considers_aggregate_not_single_signal(self):
        heavy = FakeSignal("clip", 0.7, "heavy", [score_entry("media", "photos_other", 0.9)])
        cheap_a = FakeSignal("path", 0.6, "cheap", [score_entry("technical", "other", 0.9)])
        cheap_b = FakeSignal("mime", 0.6, "cheap", [score_entry("technical", "other", 0.9)])
        # Aggregate 0.54 + 0.54 = 1.08 ≥ 0.95 even though each signal is weak.
        Scorer([cheap_a, cheap_b, heavy]).classify(make_ctx())
        assert heavy.run_count == 0

    def test_applies_to_false_skips_run(self):
        skipped = FakeSignal(
            "never", 1.0, "cheap", [score_entry("legal", "contracts", 0.9)], applies=False
        )
        decision = Scorer([skipped]).classify(make_ctx())
        assert skipped.run_count == 0
        assert decision.decision_state == "low_confidence"

    def test_signal_exception_is_isolated(self):
        broken = FakeSignal("broken", 1.0, "cheap", error=RuntimeError("boom"))
        healthy = FakeSignal("ok", 1.0, "cheap", [score_entry("legal", "contracts", 0.9)])
        decision = Scorer([broken, healthy]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("legal", "contracts")


class TestThresholds:
    def test_below_min_confidence_routes_to_fallback(self):
        weak = FakeSignal("mime", 0.3, "cheap", [score_entry("technical", "other", 0.5)])
        decision = Scorer([weak]).classify(make_ctx())
        assert (decision.category, decision.subcategory) == LOW_CONFIDENCE_FALLBACK
        assert decision.decision_state == "low_confidence"
        # Telemetry still reports the argmax candidate's evidence.
        assert decision.winning_signals == ["mime"]

    def test_below_min_margin_routes_to_fallback(self):
        signals = [
            FakeSignal("a", 1.0, "cheap", [score_entry("legal", "contracts", 0.5)]),
            FakeSignal("b", 1.0, "cheap", [score_entry("technical", "other", 0.45)]),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == LOW_CONFIDENCE_FALLBACK
        assert decision.decision_state == "low_margin"
        assert decision.margin == pytest.approx(0.05)

    def test_unopposed_margin_is_raw_total(self):
        signal = FakeSignal("solo", 1.0, "cheap", [score_entry("legal", "contracts", 0.6)])
        decision = Scorer([signal]).classify(make_ctx())
        assert decision.margin == pytest.approx(0.6)
        assert decision.decision_state == "committed"

    def test_thresholds_are_configurable(self):
        weak = FakeSignal("mime", 0.3, "cheap", [score_entry("technical", "other", 0.5)])
        decision = Scorer([weak], min_decision_confidence=0.1).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("technical", "other")


class TestEntityMerge:
    def test_company_prefers_winner_contributors_in_registry_order(self):
        signals = [
            FakeSignal(
                "org",
                1.0,
                "cheap",
                [score_entry("organization", "vendors", 0.9, {"company_name": "Acme Corp"})],
            ),
            FakeSignal(
                "text",
                0.8,
                "cheap",
                [score_entry("organization", "vendors", 0.9, {"company_name": "Other LLC"})],
            ),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert decision.company_name == "Acme Corp"

    def test_company_falls_back_to_losing_signals(self):
        signals = [
            FakeSignal("game", 0.8, "cheap", [score_entry("game_assets", "sprites", 0.9)]),
            FakeSignal(
                "text",
                0.8,
                "cheap",
                [score_entry("business", "clients", 0.1, {"company_name": "Acme Corp"})],
            ),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert (decision.category, decision.subcategory) == ("game_assets", "sprites")
        assert decision.company_name == "Acme Corp"

    def test_people_union_across_all_signals_option_c(self):
        signals = [
            FakeSignal(
                "person",
                0.9,
                "cheap",
                [score_entry("personal", "contacts", 0.2, {"people_names": ["Ada Lovelace"]})],
            ),
            FakeSignal(
                "text",
                0.8,
                "cheap",
                [
                    score_entry(
                        "legal",
                        "litigation",
                        0.9,
                        {"people_names": ["Ada Lovelace", "Grace Hopper"]},
                    )
                ],
            ),
        ]
        decision = Scorer(signals).classify(make_ctx())
        # Legal wins the filing decision, but person attribution survives.
        assert (decision.category, decision.subcategory) == ("legal", "litigation")
        assert decision.people_names == ["Ada Lovelace", "Grace Hopper"]

    def test_schema_type_override_from_winning_signal(self):
        signal = FakeSignal(
            "filename",
            1.1,
            "cheap",
            [score_entry("research", "arxiv", 0.9, {"schema_type": "ScholarlyArticle"})],
        )
        decision = Scorer([signal]).classify(make_ctx())
        assert decision.schema_type == "ScholarlyArticle"

    def test_schema_type_untouched_when_override_loses(self):
        signals = [
            FakeSignal(
                "filename",
                1.1,
                "cheap",
                [score_entry("financial", "invoices", 0.9)],
            ),
            FakeSignal(
                "text",
                0.8,
                "cheap",
                [score_entry("research", "arxiv", 0.2, {"schema_type": "ScholarlyArticle"})],
            ),
        ]
        decision = Scorer(signals).classify(make_ctx())
        assert decision.schema_type == "DigitalDocument"


class TestRegistryValidation:
    def test_duplicate_names_rejected(self):
        with pytest.raises(ValueError, match="Duplicate signal name"):
            Scorer(
                [
                    FakeSignal("dup", 1.0, "cheap"),
                    FakeSignal("dup", 0.5, "mid"),
                ]
            )

    def test_unknown_cost_tier_rejected(self):
        with pytest.raises(ValueError, match="unknown cost_tier"):
            Scorer([FakeSignal("odd", 1.0, "luxury")])

    def test_mislabeled_emission_rejected(self):
        class Mislabeled(FakeSignal):
            def run(self, ctx):
                return [
                    CategoryScore(
                        category="legal",
                        subcategory="contracts",
                        confidence=0.9,
                        signal_name="someone_else",
                    )
                ]

        decision = Scorer([Mislabeled("honest", 1.0, "cheap")]).classify(make_ctx())
        # The ValueError is contained by the per-signal isolation barrier.
        assert decision.decision_state == "low_confidence"
