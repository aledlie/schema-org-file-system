#!/usr/bin/env python3
"""
Agent Telemetry Audit — analyze OTEL trace spans for any agent type.

Extracts invocation volume, error rates, output size, duration percentiles,
background usage, and category distribution from local telemetry JSONL files.

Usage:
  python3 scripts/parse/agent_telemetry_audit.py code-reviewer
  python3 scripts/parse/agent_telemetry_audit.py code-reviewer --month 2026-02
  python3 scripts/parse/agent_telemetry_audit.py code-reviewer --days 14
  python3 scripts/parse/agent_telemetry_audit.py code-reviewer --json
"""

import argparse
import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.cli_utils import TELEMETRY_DIR, add_telemetry_args

PRE_TOOL_SPAN = "hook:agent-pre-tool"
POST_TOOL_SPAN = "hook:agent-post-tool"


def find_trace_files(month: Optional[str], days: Optional[int], telemetry_dir: str = TELEMETRY_DIR) -> list[str]:
    """Return sorted list of trace JSONL files matching the date filter."""
    pattern = os.path.join(telemetry_dir, "traces-*.jsonl")
    all_files = sorted(glob.glob(pattern))

    if month:
        prefix = f"traces-{month}-"
        return [f for f in all_files if os.path.basename(f).startswith(prefix)]

    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        filtered = []
        for f in all_files:
            base = os.path.basename(f).replace("traces-", "").replace(".jsonl", "")
            try:
                fdate = datetime.strptime(base, "%Y-%m-%d")
                if fdate >= cutoff:
                    filtered.append(f)
            except ValueError:
                continue
        return filtered

    return all_files


def parse_spans(files: list[str], agent_type: str):
    """Parse pre-tool and post-tool spans for the given agent type, plus all-agent post-tool."""
    pre_spans = []
    post_spans = []
    all_post_spans = []

    for fpath in files:
        date = os.path.basename(fpath).replace("traces-", "").replace(".jsonl", "")
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    span = json.loads(line)
                except json.JSONDecodeError:
                    continue

                name = span.get("name", "")
                attrs = span.get("attributes", {})
                atype = attrs.get("agent.type", "")

                if name == POST_TOOL_SPAN:
                    duration = span.get("duration")
                    dur_ms = None
                    if isinstance(duration, list) and len(duration) == 2:
                        dur_ms = duration[0] * 1000 + duration[1] / 1e6
                    elif isinstance(duration, (int, float)):
                        dur_ms = float(duration)

                    post_entry = {
                        "date": date,
                        "agent_type": atype,
                        "session_id": attrs.get("session.id", ""),
                        "has_error": attrs.get("agent.has_error", False),
                        "has_rate_limit": attrs.get("agent.has_rate_limit", False),
                        "output_size": attrs.get("agent.output_size", 0) or 0,
                        "is_background": attrs.get("agent.is_background", False),
                        "category": attrs.get("agent.category", ""),
                        "duration_ms": dur_ms,
                    }
                    all_post_spans.append(post_entry)
                    if atype == agent_type:
                        post_spans.append(post_entry)

                elif name == PRE_TOOL_SPAN and atype == agent_type:
                    pre_spans.append({
                        "date": date,
                        "session_id": attrs.get("session.id", ""),
                        "is_background": attrs.get("agent.is_background", False),
                        "category": attrs.get("agent.category", ""),
                    })

    return pre_spans, post_spans, all_post_spans


def compute_stats(values: list[float]) -> dict:
    """Compute summary statistics for a list of numeric values."""
    if not values:
        return {"count": 0}
    values_sorted = sorted(values)
    n = len(values_sorted)
    return {
        "count": n,
        "min": values_sorted[0],
        "max": values_sorted[-1],
        "avg": round(statistics.mean(values_sorted), 1),
        "median": values_sorted[n // 2],
        "p75": values_sorted[int(n * 0.75)],
        "p95": values_sorted[int(n * 0.95)] if n >= 20 else None,
    }


def _trend_halves(daily_pre: Counter) -> tuple[list[str], int, int]:
    """Split dates in half and return (dates_sorted, first_half_count, second_half_count)."""
    dates_sorted = sorted(daily_pre.keys())
    mid = len(dates_sorted) // 2
    first_half_dates = set(dates_sorted[:mid])
    second_half_dates = set(dates_sorted[mid:])
    first_half_count = sum(v for k, v in daily_pre.items() if k in first_half_dates)
    second_half_count = sum(v for k, v in daily_pre.items() if k in second_half_dates)
    return dates_sorted, first_half_count, second_half_count


def _duration_percentile_rank(agent_durations: list, all_durations: list) -> Optional[float]:
    """Return percentile rank of agent median duration vs all agents."""
    if not (agent_durations and all_durations):
        return None
    agent_median = sorted(agent_durations)[len(agent_durations) // 2]
    rank = sum(1 for x in all_durations if x <= agent_median) / len(all_durations) * 100
    return round(rank, 1)


def analyze(agent_type: str, files: list[str]) -> dict:
    """Run full audit analysis and return structured results."""
    pre_spans, post_spans, all_post_spans = parse_spans(files, agent_type)

    # --- Invocation volume by date ---
    daily_pre = Counter(s["date"] for s in pre_spans)

    # --- Trend: split in half for comparison ---
    dates_sorted, first_half_count, second_half_count = _trend_halves(daily_pre)

    # --- Session diversity ---
    sessions = set(s["session_id"] for s in pre_spans if s["session_id"])

    # --- Error rates ---
    total_post = len(post_spans)
    errors = sum(1 for s in post_spans if s["has_error"] is True)
    rate_limits = sum(1 for s in post_spans if s["has_rate_limit"] is True)

    # --- Output size ---
    all_output_sizes = [s["output_size"] for s in post_spans if isinstance(s["output_size"], (int, float))]
    nonzero_output_sizes = [v for v in all_output_sizes if v > 0]

    # --- Duration ---
    agent_durations = [s["duration_ms"] for s in post_spans if s["duration_ms"] is not None]
    all_durations = [s["duration_ms"] for s in all_post_spans if s["duration_ms"] is not None]

    # --- Background usage ---
    bg_count = sum(1 for s in pre_spans if s["is_background"] is True)

    return {
        "agent_type": agent_type,
        "files_scanned": len(files),
        "date_range": f"{dates_sorted[0]} to {dates_sorted[-1]}" if dates_sorted else "none",
        "invocations": {
            "pre_tool_total": len(pre_spans),
            "post_tool_total": total_post,
            "unique_sessions": len(sessions),
            "daily_breakdown": dict(sorted(daily_pre.items())),
        },
        "trend": {
            "first_half": first_half_count,
            "second_half": second_half_count,
            "change_pct": round((second_half_count - first_half_count) / max(first_half_count, 1) * 100, 1),
        },
        "errors": {
            "total": total_post,
            "errors": errors,
            "error_rate_pct": round(errors / max(total_post, 1) * 100, 1),
            "rate_limits": rate_limits,
            "rate_limit_pct": round(rate_limits / max(total_post, 1) * 100, 1),
            "combined_amplification_pct": round((errors + rate_limits) / max(total_post, 1) * 100, 1),
        },
        "output_size": {
            "all": compute_stats(all_output_sizes),
            "nonzero": compute_stats(nonzero_output_sizes),
        },
        "duration_ms": {
            "agent": compute_stats(agent_durations),
            "percentile_rank_vs_all": _duration_percentile_rank(agent_durations, all_durations),
        },
        "background_usage": {
            "foreground": len(pre_spans) - bg_count,
            "background": bg_count,
            "background_pct": round(bg_count / max(len(pre_spans), 1) * 100, 1),
        },
        "categories": dict(Counter(s["category"] for s in pre_spans if s["category"]).most_common()),
    }


def print_report(data: dict):
    """Pretty-print the audit report to stdout."""
    print(f"\n{'='*60}")
    print(f"  Agent Telemetry Audit: {data['agent_type']}")
    print(f"  Files: {data['files_scanned']}  |  Range: {data['date_range']}")
    print(f"{'='*60}\n")

    inv = data["invocations"]
    print(f"INVOCATIONS")
    print(f"  Pre-tool spans:  {inv['pre_tool_total']}")
    print(f"  Post-tool spans: {inv['post_tool_total']}")
    print(f"  Unique sessions: {inv['unique_sessions']}")

    tr = data["trend"]
    arrow = "+" if tr["change_pct"] >= 0 else ""
    print(f"\nTREND (first half vs second half)")
    print(f"  First half:  {tr['first_half']}")
    print(f"  Second half: {tr['second_half']}  ({arrow}{tr['change_pct']}%)")

    err = data["errors"]
    print(f"\nERROR RATES")
    print(f"  Errors:      {err['errors']}/{err['total']} ({err['error_rate_pct']}%)")
    print(f"  Rate limits: {err['rate_limits']}/{err['total']} ({err['rate_limit_pct']}%)")
    print(f"  Combined:    {err['combined_amplification_pct']}%")

    for label, key in [("OUTPUT SIZE (all)", "all"), ("OUTPUT SIZE (non-zero)", "nonzero")]:
        stats = data["output_size"][key]
        print(f"\n{label}")
        if stats["count"] == 0:
            print("  No data")
        else:
            print(f"  Count:  {stats['count']}")
            print(f"  Min:    {stats['min']}")
            print(f"  Max:    {stats['max']}")
            print(f"  Avg:    {stats['avg']}")
            print(f"  Median: {stats['median']}")
            print(f"  P75:    {stats['p75']}")

    dur = data["duration_ms"]
    print(f"\nDURATION (ms)")
    ds = dur["agent"]
    if ds["count"] == 0:
        print("  No data")
    else:
        print(f"  Count:  {ds['count']}")
        print(f"  Median: {ds['median']:.1f}")
        print(f"  P75:    {ds['p75']:.1f}")
        if ds.get("p95"):
            print(f"  P95:    {ds['p95']:.1f}")
    if dur["percentile_rank_vs_all"] is not None:
        print(f"  Rank vs all agents: P{dur['percentile_rank_vs_all']}")

    bg = data["background_usage"]
    print(f"\nBACKGROUND USAGE")
    print(f"  Foreground: {bg['foreground']}")
    print(f"  Background: {bg['background']} ({bg['background_pct']}%)")

    cats = data["categories"]
    if cats:
        print(f"\nCATEGORIES")
        for cat, count in cats.items():
            print(f"  {cat}: {count}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Audit OTEL telemetry for a Claude Code agent type",
    )
    parser.add_argument("agent_type", help="Agent type to audit (e.g. code-reviewer)")
    add_telemetry_args(parser)
    args = parser.parse_args()

    telemetry_dir = args.telemetry_dir
    files = find_trace_files(args.month, args.days, telemetry_dir)
    if not files:
        print(f"No trace files found in {telemetry_dir}", file=sys.stderr)
        sys.exit(1)

    data = analyze(args.agent_type, files)

    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        print_report(data)


if __name__ == "__main__":
    main()
