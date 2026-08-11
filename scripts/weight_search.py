#!/usr/bin/env python3
"""Joint weight + threshold search over the DB replay (nevergrad).

``scripts/weight_grid_search.py`` perturbs one prior at a time by a fixed
factor set and sweeps the two decision thresholds in separate passes. That is
coordinate search: it cannot see interactions between the 20 correlated priors,
and it tunes the thresholds independently of the weights they gate. This script
optimises the whole space at once with a derivative-free optimiser, using the
same replay and the same agreement measure.

**It never writes weights.py.** Output is a proposal plus the evidence for it;
adopting a proposal is a human decision that still owes a calibration doc and a
golden-suite pass, exactly as the 2026-07-26 re-tune did.

Two guards against the thing joint search is bad at — overfitting a biased
oracle (stored decisions include manual corrections and pre-unified
placements):

- **Objective is the non-media slice.** The replay serves CLIP/scene votes from
  the embedding cache only, so stored media decisions disagree for fidelity
  reasons rather than weight reasons. Optimising overall agreement chases that
  noise. Overall agreement is still reported, so divergence is visible.
- **A holdout split, on by default.** Candidates are scored on a train slice;
  the winner is re-scored on rows the optimiser never saw. A proposal that
  gains on train and loses on holdout is overfitting, and the report says so.

Usage:
    PYTHONPATH=src:scripts:. python scripts/weight_search.py
    PYTHONPATH=src:scripts:. python scripts/weight_search.py \\
        --budget 200 --optimizer NGOpt --output results/weight_search.json
    PYTHONPATH=src:scripts:. python scripts/weight_search.py --weights-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Allow ``from shared.x import y`` / src imports when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_scoring import (  # noqa: E402
    WEIGHT_SIGNALS,
    build_replay_scorer,
    load_replay_rows,
    replay_rows,
    scene_path_lookup,
    screenshot_text_lookup,
)
from constants import DEFAULT_DB_PATH  # noqa: E402  (src on path)
from weight_grid_search import agreement_stats, classify_flips  # noqa: E402

# --------------------------------------------------------------------------- #
# Search space                                                                 #
# --------------------------------------------------------------------------- #

# Each prior is searched within this multiplicative band around its shipped
# value. Wide enough to reorder adjacent priors (the interactions coordinate
# search cannot see), narrow enough that the optimiser spends its budget near
# the calibrated optimum rather than rediscovering it.
WEIGHT_LOWER_FACTOR = 0.6
WEIGHT_UPPER_FACTOR = 1.4

# Decision-threshold bands. Chosen to span the shipped values with headroom on
# both sides without admitting degenerate regimes (a near-zero margin commits
# every coin-flip; a very high floor sends everything to fallback).
CONFIDENCE_BOUNDS = (0.25, 0.50)
MARGIN_BOUNDS = (0.02, 0.20)

# Fraction of replayable rows withheld from the objective. Deterministic split
# on file_id, so train/holdout membership is stable across runs and optimisers.
DEFAULT_HOLDOUT_FRACTION = 0.3

# Buckets the stable file_id digest is folded into for the train/holdout split.
_SPLIT_BUCKETS = 100

DEFAULT_BUDGET = 120
DEFAULT_OPTIMIZER = "NGOpt"
DEFAULT_SEED = 0

# Rounding used to memoise candidates. The replay is deterministic, so two
# candidates that agree to this precision produce identical outcomes; without
# it a converging optimiser pays full replay cost to re-evaluate its own best.
_CANDIDATE_PRECISION = 6

MEDIA_CATEGORY = "media"
EXIT_OK = 0
EXIT_NO_DATA = 1

_CONFIDENCE_KEY = "min_decision_confidence"
_MARGIN_KEY = "min_decision_margin"


# --------------------------------------------------------------------------- #
# Invariants — encoded as constraints, not discovered by search                #
# --------------------------------------------------------------------------- #


def _signal_of(const_name: str) -> str:
    for name, _weight, signal in WEIGHT_SIGNALS:
        if name == const_name:
            return signal
    raise KeyError(const_name)


def constraint_violations(candidate: Dict[str, float]) -> List[str]:
    """Return the invariants a candidate breaks (empty when it is admissible).

    These are locked by tests/unit/scoring/test_mime_commit_gap.py and stated
    in CLAUDE.md; an optimiser left to itself will violate all of them, because
    each is a statement about *behaviour* that the agreement objective cannot
    see.
    """
    from src.scoring.signals.mime_fallback import MIME_MATCH_CONFIDENCE

    violations: List[str] = []

    org = candidate[_signal_of("W_ORG")]
    person = candidate[_signal_of("W_PERSON")]
    legal = candidate[_signal_of("W_LEGAL")]
    if not org > person:
        violations.append(f"W_ORG ({org:.3f}) must exceed W_PERSON ({person:.3f})")
    if not person > legal:
        violations.append(f"W_PERSON ({person:.3f}) must exceed W_LEGAL ({legal:.3f})")

    mime_committed = candidate[_signal_of("W_MIME")] * MIME_MATCH_CONFIDENCE
    confidence = candidate[_CONFIDENCE_KEY]
    margin = candidate[_MARGIN_KEY]
    if not mime_committed >= confidence:
        violations.append(
            f"mime-only file must commit: W_MIME*{MIME_MATCH_CONFIDENCE} "
            f"({mime_committed:.3f}) >= MIN_DECISION_CONFIDENCE ({confidence:.3f})"
        )
    if not mime_committed < confidence + margin:
        violations.append(
            f"mime must not out-commit floor-clearing content: "
            f"W_MIME*{MIME_MATCH_CONFIDENCE} ({mime_committed:.3f}) < "
            f"MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN ({confidence + margin:.3f})"
        )
    return violations


# --------------------------------------------------------------------------- #
# Replay evaluation                                                            #
# --------------------------------------------------------------------------- #


def split_rows(rows: Sequence[Any], holdout_fraction: float) -> Tuple[List[Any], List[Any]]:
    """Deterministically split rows into (train, holdout).

    Splits on a stable digest of ``file_id`` rather than position, so adding
    rows to the database does not reshuffle existing membership and invalidate
    a prior run's comparison.

    Uses hashlib, NOT the builtin ``hash()``: Python randomises string hashing
    per process (PYTHONHASHSEED), so ``hash()`` here silently reshuffled the
    split on every run — two runs of this script reported different baselines
    off different row sets, which makes the train/holdout comparison
    meaningless.
    """
    if holdout_fraction <= 0:
        return list(rows), []
    train: List[Any] = []
    holdout: List[Any] = []
    cutoff = holdout_fraction * _SPLIT_BUCKETS
    for row in rows:
        digest = int(hashlib.sha1(str(row.file_id).encode()).hexdigest()[:8], 16)
        (holdout if digest % _SPLIT_BUCKETS < cutoff else train).append(row)
    return train, holdout


class ReplayEvaluator:
    """Scores candidate weight/threshold vectors against a fixed row set."""

    def __init__(self, rows: Sequence[Any], classifier: Any) -> None:
        self._rows = rows
        self._classifier = classifier
        self._text_by_path = screenshot_text_lookup(rows)
        self._scene_paths = scene_path_lookup(rows)
        self._cache: Dict[Tuple[float, ...], Dict[str, Any]] = {}

    def evaluate(self, candidate: Dict[str, float]) -> Dict[str, Any]:
        key = tuple(round(candidate[k], _CANDIDATE_PRECISION) for k in sorted(candidate))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        weights = {k: v for k, v in candidate.items() if k not in (_CONFIDENCE_KEY, _MARGIN_KEY)}
        scorer = build_replay_scorer(
            self._classifier,
            screenshot_text_by_path=self._text_by_path,
            weight_overrides=weights,
            min_decision_confidence=candidate[_CONFIDENCE_KEY],
            min_decision_margin=candidate[_MARGIN_KEY],
            scene_path_by_context_path=self._scene_paths,
        )
        outcomes, _ = replay_rows(self._rows, scorer)
        total, agree, nm_total, nm_agree, by_id = agreement_stats(outcomes)
        result = {
            "agree": agree,
            "total": total,
            "nonmedia_agree": nm_agree,
            "nonmedia_total": nm_total,
            "by_id": by_id,
        }
        self._cache[key] = result
        return result

    @property
    def evaluations(self) -> int:
        return len(self._cache)


def shipped_candidate() -> Dict[str, float]:
    """The currently shipped weights and thresholds, as a candidate vector."""
    from src.scoring.weights import MIN_DECISION_CONFIDENCE, MIN_DECISION_MARGIN

    candidate = {signal: weight for _name, weight, signal in WEIGHT_SIGNALS}
    candidate[_CONFIDENCE_KEY] = MIN_DECISION_CONFIDENCE
    candidate[_MARGIN_KEY] = MIN_DECISION_MARGIN
    return candidate


def _satisfies_invariants(candidate: Dict[str, float]) -> bool:
    return not constraint_violations(candidate)


def _bounded(ng: Any, init: float, lower: float, upper: float) -> Any:
    """A bounded scalar whose mutation sigma actually fits its band.

    nevergrad's default sigma is 1.0 regardless of bounds, which for these
    narrow bands (W_MIME spans 0.24) puts the bounds ~0.3 sigma apart and makes
    almost every mutation land outside and get clipped — it warns that it wants
    at least 3. Sizing sigma to span/6 puts the bounds at +/-3 sigma.

    ``set_mutation`` must come *before* ``set_bounds``: the sigma check runs
    inside ``set_bounds``, so the other order reaches the same final sigma but
    emits a spurious "bounds are 0.32 sigma away" warning against the default
    sigma it is about to replace. That warning is easy to dismiss as noise and
    then mistake for evidence the sigma was never applied.
    """
    return (
        ng.p.Scalar(init=init)
        .set_mutation(sigma=(upper - lower) / 6.0)
        .set_bounds(lower=lower, upper=upper)
    )


def build_parametrization(search_thresholds: bool, seed: int) -> Any:
    """Bounded search space with the behavioural invariants registered."""
    import nevergrad as ng

    from src.scoring.weights import MIN_DECISION_CONFIDENCE, MIN_DECISION_MARGIN

    space: Dict[str, Any] = {}
    for _name, weight, signal in WEIGHT_SIGNALS:
        space[signal] = _bounded(
            ng, weight, weight * WEIGHT_LOWER_FACTOR, weight * WEIGHT_UPPER_FACTOR
        )
    if search_thresholds:
        space[_CONFIDENCE_KEY] = _bounded(ng, MIN_DECISION_CONFIDENCE, *CONFIDENCE_BOUNDS)
        space[_MARGIN_KEY] = _bounded(ng, MIN_DECISION_MARGIN, *MARGIN_BOUNDS)
    else:
        space[_CONFIDENCE_KEY] = ng.p.Constant(MIN_DECISION_CONFIDENCE)
        space[_MARGIN_KEY] = ng.p.Constant(MIN_DECISION_MARGIN)

    parametrization = ng.p.Dict(**space)
    # Cheap: evaluated without a replay, so rejected candidates cost nothing.
    # A named function, not a lambda — nevergrad warns that lambdas break
    # pickling, which it needs for its parallel/portfolio optimisers.
    parametrization.register_cheap_constraint(_satisfies_invariants)
    parametrization.random_state.seed(seed)
    return parametrization


def run_search(
    db_path: Path,
    budget: int = DEFAULT_BUDGET,
    optimizer_name: str = DEFAULT_OPTIMIZER,
    seed: int = DEFAULT_SEED,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    search_thresholds: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Optimise on the train slice; report the winner on the holdout slice."""
    import nevergrad as ng

    from src.classifiers.content_classifier import ContentClassifier

    rows = load_replay_rows(db_path, limit=limit)
    if not rows:
        raise SystemExit(f"no stored File rows to replay in {db_path}")

    train_rows, holdout_rows = split_rows(rows, holdout_fraction)
    classifier = ContentClassifier()
    train = ReplayEvaluator(train_rows, classifier)

    shipped = shipped_candidate()
    baseline = train.evaluate(shipped)
    print(
        f"rows: {len(rows)} total, {len(train_rows)} train, {len(holdout_rows)} holdout\n"
        f"BASELINE (train) non-media {baseline['nonmedia_agree']}/{baseline['nonmedia_total']}  "
        f"overall {baseline['agree']}/{baseline['total']}"
    )

    parametrization = build_parametrization(search_thresholds, seed)
    optimizer = ng.optimizers.registry[optimizer_name](
        parametrization=parametrization, budget=budget, num_workers=1
    )

    best_value = float("inf")
    for iteration in range(budget):
        candidate = optimizer.ask()
        result = train.evaluate(dict(candidate.value))
        # Maximise non-media agreement; overall agreement breaks ties without
        # letting the media slice's fidelity noise drive the search.
        loss = -(result["nonmedia_agree"] + result["agree"] / (result["total"] + 1))
        optimizer.tell(candidate, loss)
        if loss < best_value:
            best_value = loss
            print(
                f"  [{iteration + 1}/{budget}] non-media "
                f"{result['nonmedia_agree']}/{result['nonmedia_total']} "
                f"(baseline {baseline['nonmedia_agree']}) overall {result['agree']}"
            )

    best = dict(optimizer.provide_recommendation().value)
    best_train = train.evaluate(best)
    fixes, breaks, neutral = classify_flips(baseline["by_id"], best_train["by_id"])

    report: Dict[str, Any] = {
        "optimizer": optimizer_name,
        "budget": budget,
        "seed": seed,
        "replays": train.evaluations,
        "search_thresholds": search_thresholds,
        "rows": {
            "total": len(rows),
            "train": len(train_rows),
            "holdout": len(holdout_rows),
            "holdout_fraction": holdout_fraction,
        },
        "shipped": {k: round(v, 4) for k, v in shipped.items()},
        "best": {k: round(v, 4) for k, v in best.items()},
        "train": {
            "baseline_nonmedia_agree": baseline["nonmedia_agree"],
            "baseline_agree": baseline["agree"],
            "best_nonmedia_agree": best_train["nonmedia_agree"],
            "best_agree": best_train["agree"],
            "nonmedia_total": best_train["nonmedia_total"],
            "total": best_train["total"],
            "fixes": fixes,
            "breaks": breaks,
            "neutral": neutral,
        },
        "constraint_violations": constraint_violations(best),
    }

    if holdout_rows:
        holdout = ReplayEvaluator(holdout_rows, classifier)
        holdout_baseline = holdout.evaluate(shipped)
        holdout_best = holdout.evaluate(best)
        h_fixes, h_breaks, h_neutral = classify_flips(
            holdout_baseline["by_id"], holdout_best["by_id"]
        )
        report["holdout"] = {
            "baseline_nonmedia_agree": holdout_baseline["nonmedia_agree"],
            "best_nonmedia_agree": holdout_best["nonmedia_agree"],
            "nonmedia_total": holdout_best["nonmedia_total"],
            "baseline_agree": holdout_baseline["agree"],
            "best_agree": holdout_best["agree"],
            "total": holdout_best["total"],
            "fixes": h_fixes,
            "breaks": h_breaks,
            "neutral": h_neutral,
        }
        report["generalizes"] = (
            holdout_best["nonmedia_agree"] >= holdout_baseline["nonmedia_agree"]
            and h_fixes >= h_breaks
        )

    return report


def print_report(report: Dict[str, Any]) -> None:
    train = report["train"]
    delta = train["best_nonmedia_agree"] - train["baseline_nonmedia_agree"]
    print(
        f"\nBEST (train) non-media {train['best_nonmedia_agree']}/{train['nonmedia_total']} "
        f"({delta:+d} vs shipped)  fix={train['fixes']} break={train['breaks']} "
        f"neutral={train['neutral']}"
    )
    print(f"{report['replays']} distinct replays over a budget of {report['budget']}.")

    changed = {
        key: (report["shipped"][key], value)
        for key, value in report["best"].items()
        if abs(value - report["shipped"][key]) > 1e-4
    }
    if changed:
        print("\nProposed changes:")
        for key, (was, now) in sorted(changed.items()):
            print(f"  {key:<24} {was:>6} -> {now:<6} ({now - was:+.3f})")

    holdout = report.get("holdout")
    if holdout:
        h_delta = holdout["best_nonmedia_agree"] - holdout["baseline_nonmedia_agree"]
        print(
            f"\nHOLDOUT (unseen) non-media "
            f"{holdout['best_nonmedia_agree']}/{holdout['nonmedia_total']} "
            f"({h_delta:+d} vs shipped)  fix={holdout['fixes']} break={holdout['breaks']}"
        )
        if report.get("generalizes"):
            print("  Holds up on unseen rows.")
        else:
            print("  DOES NOT hold up on unseen rows — treat as overfitting, not a re-tune.")

    if report["constraint_violations"]:
        print("\nCONSTRAINT VIOLATIONS in the recommendation (should be empty):")
        for violation in report["constraint_violations"]:
            print(f"  - {violation}")

    print(
        "\nNothing was written. Adopting this needs `make golden` at 43/43 and a "
        "calibration doc, same as any weight change."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Joint weight + threshold search over the DB replay (nevergrad). "
        "Reports a proposal; never edits weights.py."
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="Replay evaluations (default: %(default)s)",
    )
    parser.add_argument(
        "--optimizer",
        default=DEFAULT_OPTIMIZER,
        help="nevergrad optimizer name, e.g. NGOpt, TwoPointsDE, CMA (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Seeds the parametrization RNG. NOTE: a no-op under the default "
        "NGOpt, which picks a deterministic local algorithm from the shipped "
        "init at this budget/dimension — seeds 0/1/2 produce byte-identical "
        "runs. Vary --optimizer (CMA, TwoPointsDE) to sample different "
        "searches (default: %(default)s)",
    )
    parser.add_argument(
        "--holdout-fraction",
        type=float,
        default=DEFAULT_HOLDOUT_FRACTION,
        help="Rows withheld from the objective and used to test generalisation "
        "(0 disables; default: %(default)s)",
    )
    parser.add_argument(
        "--weights-only",
        action="store_true",
        help="Hold the decision thresholds at their shipped values",
    )
    parser.add_argument("--limit", type=int, default=None, help="Replay at most this many rows")
    parser.add_argument("--output", type=Path, default=None, help="Write the report as JSON")
    args = parser.parse_args(argv)

    report = run_search(
        db_path=args.db_path,
        budget=args.budget,
        optimizer_name=args.optimizer,
        seed=args.seed,
        holdout_fraction=args.holdout_fraction,
        search_thresholds=not args.weights_only,
        limit=args.limit,
    )
    print_report(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(f"Wrote {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
