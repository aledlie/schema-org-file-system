#!/usr/bin/env python3
"""Directional weight grid search over the DB replay (calibration harness).

Extends ``scripts/backtest_scoring.py`` (which reports undirected decision-flip
counts per weight) with a *directional* measure: for each candidate
``(signal, factor)`` the full replay is rerun with that one prior scaled, and
every decision flip is classified against the stored (production) decision:

- **fix**     — flipped row now matches the stored decision (was wrong)
- **break**   — flipped row no longer matches the stored decision (was right)
- **neutral** — flipped between two answers that both differ from stored

Agreement is reported on two slices:

- **overall**   — all replayed rows with a stored (category, subcategory)
- **non-media** — stored category != media. The replay serves CLIP/scene
  votes only from the embedding cache, so stored media decisions made with
  live CLIP + scene-probe votes (interiors/exteriors/graphics) disagree for
  fidelity reasons, not weight reasons; the non-media slice removes that
  noise floor.

The stored decisions are a biased oracle (they include manual corrections and
pre-unified-era placements), so treat deltas as evidence, not truth: a
candidate is interesting when it fixes more than it breaks on BOTH slices and
survives the golden corpus (``tests/integration/test_unified_scoring_golden.py``)
at 43/43. Used for the non-provisional weight re-tune
(``docs/architecture/scoring-calibration-20260726.md``).

Usage:
    PYTHONPATH=src:scripts:. python scripts/weight_grid_search.py
    PYTHONPATH=src:scripts:. python scripts/weight_grid_search.py \\
        --factors 0.9 1.1 --output results/weight_grid.json
"""

from __future__ import annotations

import argparse
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
    screenshot_text_lookup,
)
from constants import DEFAULT_DB_PATH  # noqa: E402  (src on path)

# Default perturbation factors applied to each prior (one at a time).
DEFAULT_FACTORS = (0.8, 0.9, 1.1, 1.2)

# Stored category excluded from the fidelity-filtered agreement slice (see
# module docstring: replay lacks live CLIP/scene votes for media decisions).
MEDIA_CATEGORY = "media"

EXIT_OK = 0
EXIT_NO_DATA = 1

Pair = Tuple[Optional[str], Optional[str]]


def agreement_stats(
    outcomes: Sequence[Any],
) -> Tuple[int, int, int, int, Dict[Any, Tuple[Pair, Pair]]]:
    """(total, agree, nonmedia_total, nonmedia_agree, {file_id: (stored, pred)})."""
    total = agree = nonmedia_total = nonmedia_agree = 0
    by_id: Dict[Any, Tuple[Pair, Pair]] = {}
    for outcome in outcomes:
        stored: Pair = (outcome.row.stored_category, outcome.row.stored_subcategory)
        if stored[0] is None:
            continue
        pred: Pair = (outcome.decision.category, outcome.decision.subcategory)
        by_id[outcome.row.file_id] = (stored, pred)
        total += 1
        matched = pred == stored
        agree += matched
        if stored[0] != MEDIA_CATEGORY:
            nonmedia_total += 1
            nonmedia_agree += matched
    return total, agree, nonmedia_total, nonmedia_agree, by_id


def classify_flips(
    base_by_id: Dict[Any, Tuple[Pair, Pair]],
    cand_by_id: Dict[Any, Tuple[Pair, Pair]],
) -> Tuple[int, int, int]:
    """Count (fixes, breaks, neutral) flips of the candidate vs the baseline."""
    fixes = breaks = neutral = 0
    for file_id, (stored, pred) in cand_by_id.items():
        base_entry = base_by_id.get(file_id)
        if base_entry is None:
            continue
        _, base_pred = base_entry
        if pred == base_pred:
            continue
        if pred == stored and base_pred != stored:
            fixes += 1
        elif base_pred == stored and pred != stored:
            breaks += 1
        else:
            neutral += 1
    return fixes, breaks, neutral


def run_grid(
    db_path: Path,
    factors: Sequence[float],
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Replay baseline + every (weight, factor) candidate; return the report."""
    from src.classifiers.content_classifier import ContentClassifier

    rows = load_replay_rows(db_path, limit=limit)
    if not rows:
        raise SystemExit(f"no stored File rows to replay in {db_path}")
    classifier = ContentClassifier()
    text_by_path = screenshot_text_lookup(rows)

    base_scorer = build_replay_scorer(classifier, screenshot_text_by_path=text_by_path)
    base_outcomes, _ = replay_rows(rows, base_scorer)
    total, agree, nm_total, nm_agree, base_by_id = agreement_stats(base_outcomes)
    print(
        f"BASELINE agreement {agree}/{total} ({100 * agree / total:.1f}%)  "
        f"non-media {nm_agree}/{nm_total} ({100 * nm_agree / nm_total:.1f}%)"
    )

    grid: List[Dict[str, Any]] = []
    for const_name, base_weight, signal_name in WEIGHT_SIGNALS:
        for factor in factors:
            scorer = build_replay_scorer(
                classifier,
                screenshot_text_by_path=text_by_path,
                weight_overrides={signal_name: base_weight * factor},
            )
            outcomes, _ = replay_rows(rows, scorer)
            _, cand_agree, _, cand_nm_agree, cand_by_id = agreement_stats(outcomes)
            fixes, breaks, neutral = classify_flips(base_by_id, cand_by_id)
            entry = {
                "const": const_name,
                "signal": signal_name,
                "factor": factor,
                "weight": round(base_weight * factor, 3),
                "agree": cand_agree,
                "d_agree": cand_agree - agree,
                "nonmedia_agree": cand_nm_agree,
                "d_nonmedia": cand_nm_agree - nm_agree,
                "fixes": fixes,
                "breaks": breaks,
                "neutral": neutral,
            }
            grid.append(entry)
            if fixes or breaks or neutral:
                print(
                    f"{const_name:<15} x{factor:<4} w={entry['weight']:<5} "
                    f"dAgree={entry['d_agree']:+3d} dNonMedia={entry['d_nonmedia']:+3d} "
                    f"fix={fixes} break={breaks} neutral={neutral}"
                )

    return {
        "baseline": {
            "agree": agree,
            "total": total,
            "nonmedia_agree": nm_agree,
            "nonmedia_total": nm_total,
        },
        "factors": list(factors),
        "grid": grid,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(DEFAULT_DB_PATH),
        help=f"SQLite database to replay (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--factors",
        type=float,
        nargs="+",
        default=list(DEFAULT_FACTORS),
        help=f"Per-weight scale factors to probe (default: {DEFAULT_FACTORS})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max File rows to replay (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the full grid report as JSON to this path",
    )
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"Error: database not found at {args.db_path}")
        return EXIT_NO_DATA

    report = run_grid(args.db_path, args.factors, limit=args.limit)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON report written to {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
