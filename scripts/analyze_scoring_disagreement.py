#!/usr/bin/env python3
"""Shadow-mode scoring disagreement report (UNIFIED_SCORING_PLAN §6 Phase 2).

Reads the JSONL shadow log written by ``ContentOrganizer._log_shadow_comparison``
(one record per classified file; shape per plan §7.1 with ``path`` instead of
``file_hash``, an ``agrees`` bool, and ``decision_state`` inside ``decision``)
and reports how often the unified scorer disagrees with the legacy chain,
grouped by (legacy -> unified) category/subcategory pair.

Usage:
    python scripts/analyze_scoring_disagreement.py [--log PATH] [--json PATH] [--top N]

Malformed lines are counted and skipped, never fatal.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_LOG_PATH = Path("results/scoring_shadow.jsonl")
DEFAULT_TOP = 10
RATE_PRECISION = 4
UNKNOWN = "unknown"

_EXIT_OK = 0
_EXIT_MISSING_LOG = 1

# (category, subcategory) pair — one side of a disagreement grouping key.
_Pair = Tuple[str, str]


def _decision_pair(decision: Any) -> _Pair:
    """Extract the (category, subcategory) pair from a decision dict."""
    if not isinstance(decision, dict):
        return (UNKNOWN, UNKNOWN)
    return (
        str(decision.get("category", UNKNOWN)),
        str(decision.get("subcategory", UNKNOWN)),
    )


def _record_agrees(record: Dict[str, Any]) -> bool:
    """The record's ``agrees`` bool, derived from the decisions when absent."""
    agrees = record.get("agrees")
    if isinstance(agrees, bool):
        return agrees
    return _decision_pair(record.get("decision")) == _decision_pair(record.get("legacy_decision"))


def _format_pair(pair: _Pair) -> str:
    return f"{pair[0]}/{pair[1]}"


def parse_records(lines: Iterable[str]) -> Tuple[List[Dict[str, Any]], int]:
    """Parse JSONL lines into shadow records.

    Returns ``(records, malformed_count)``. A line is malformed when it is not
    valid JSON or not a JSON object; blank lines are ignored without counting.
    """
    records: List[Dict[str, Any]] = []
    malformed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        records.append(record)
    return records, malformed


def summarize(
    records: List[Dict[str, Any]],
    malformed: int = 0,
    top: int = DEFAULT_TOP,
) -> Dict[str, Any]:
    """Aggregate shadow records into the disagreement report structure.

    ``top`` caps both the number of (legacy -> unified) pairs reported and the
    number of example paths listed per pair. Pairs are sorted by descending
    disagreement count (ties broken by pair name for determinism).
    """
    total = len(records)
    agree_count = 0
    decision_states: Counter = Counter()
    pair_counts: Counter = Counter()
    pair_examples: Dict[Tuple[_Pair, _Pair], List[str]] = defaultdict(list)

    for record in records:
        decision = record.get("decision")
        state = decision.get("decision_state") if isinstance(decision, dict) else None
        decision_states[str(state) if state is not None else UNKNOWN] += 1

        if _record_agrees(record):
            agree_count += 1
            continue

        key = (_decision_pair(record.get("legacy_decision")), _decision_pair(decision))
        pair_counts[key] += 1
        pair_examples[key].append(str(record.get("path", UNKNOWN)))

    ranked = sorted(pair_counts.items(), key=lambda item: (-item[1], item[0]))
    disagreements = [
        {
            "legacy": _format_pair(legacy_pair),
            "unified": _format_pair(unified_pair),
            "count": count,
            "examples": pair_examples[(legacy_pair, unified_pair)][:top],
        }
        for (legacy_pair, unified_pair), count in ranked[:top]
    ]

    return {
        "total_records": total,
        "malformed_lines": malformed,
        "agree_count": agree_count,
        "disagree_count": total - agree_count,
        "agreement_rate": round(agree_count / total, RATE_PRECISION) if total else None,
        "decision_states": dict(sorted(decision_states.items())),
        "disagreements": disagreements,
    }


def format_report(report: Dict[str, Any]) -> str:
    """Render the summary dict as the stdout report."""
    lines = [
        "Shadow scoring disagreement report",
        "=" * len("Shadow scoring disagreement report"),
        f"Total records:   {report['total_records']}",
        f"Malformed lines: {report['malformed_lines']}",
    ]

    rate = report["agreement_rate"]
    rate_text = f"{rate:.2%}" if rate is not None else "n/a"
    lines.append(
        f"Agreement:       {report['agree_count']}/{report['total_records']} ({rate_text})"
    )

    lines.append("Decision states:")
    if report["decision_states"]:
        for state, count in report["decision_states"].items():
            lines.append(f"  {state:<16} {count}")
    else:
        lines.append("  (none)")

    lines.append("Disagreements by (legacy -> unified) pair:")
    if report["disagreements"]:
        for entry in report["disagreements"]:
            lines.append(f"  {entry['count']:>4}  {entry['legacy']} -> {entry['unified']}")
            for example in entry["examples"]:
                lines.append(f"        - {example}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report legacy-vs-unified scoring disagreements from the shadow JSONL log"
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Shadow JSONL log path (default: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Also write the report as a JSON document to this path",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Max pairs reported and example paths per pair (default: {DEFAULT_TOP})",
    )
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"Error: shadow log not found at {args.log}")
        return _EXIT_MISSING_LOG

    with args.log.open("r", encoding="utf-8") as handle:
        records, malformed = parse_records(handle)

    report = summarize(records, malformed=malformed, top=args.top)
    print(format_report(report))

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON report written to {args.json}")

    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
