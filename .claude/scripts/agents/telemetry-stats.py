#!/usr/bin/env python3
"""
agent-telemetry-stats.py

Parse OTEL trace JSONL files and agent-cache logs to compute per-agent telemetry stats:
  - span counts, error rates, session diversity (from OTEL traces)
  - invocation counts, session counts (from agent-cache logs)
  - 7-day vs prior-7-day trend (from OTEL spans)

Usage:
  python3 ~/.claude/scripts/agents/telemetry-stats.py
  python3 ~/.claude/scripts/agents/telemetry-stats.py --agents code-reviewer agent-auditor
  python3 ~/.claude/scripts/agents/telemetry-stats.py --days 14
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

_scripts_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _scripts_dir)
from lib.cli_utils import TELEMETRY_DIR
from parse.agent_telemetry_audit import find_trace_files
AGENT_CACHE_DIR = os.path.expanduser("~/.claude/agent-cache")

DEFAULT_AGENTS = [
    "auto-error-resolver",
    "code-simplifier",
    "code-reviewer",
    "agent-auditor",
    "skill-auditor",
    "web-research-analyst",
    "webscraping-research-analyst",
    "genai-quality-monitor",
    "telemetry-archaeologist",
    "telemetry-backfill",
]

TODAY = datetime.now()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-agent telemetry stats from OTEL traces + agent-cache logs")
    parser.add_argument("--agents", nargs="+", default=DEFAULT_AGENTS, help="Agent names to report on")
    parser.add_argument("--days", type=int, default=30, help="How many days back to look in trace files")
    return parser.parse_args()


def _accumulate_span(span: dict, agents: list, counts: dict, days_ago: int) -> None:
    """Accumulate a single span's metrics into the counts dict."""
    attrs = span.get("attributes", {})
    atype = attrs.get("agent.type", "")
    if atype not in agents:
        return
    counts[atype]["total"] += 1
    has_error = attrs.get("agent.has_error", False)
    if has_error or span.get("status", {}).get("code", 0) == 2:
        counts[atype]["errors"] += 1
    sid = attrs.get("session.id", "")
    if sid:
        counts[atype]["sessions"].add(sid)
    if span.get("name", "").endswith("pre-tool"):
        if days_ago <= 7:
            counts[atype]["recent"] += 1
        elif days_ago <= 14:
            counts[atype]["older"] += 1


def _parse_trace_file(fpath: str, agents: list, counts: dict, days: int) -> None:
    """Parse one trace file and accumulate span metrics. Skips files outside `days` range."""
    fname = os.path.basename(fpath)
    try:
        fdate = datetime.strptime(fname, "traces-%Y-%m-%d.jsonl")
    except ValueError:
        return
    days_ago = (TODAY - fdate).days
    if days_ago > days:
        return
    with open(fpath, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                span = json.loads(line)
            except json.JSONDecodeError:
                continue
            _accumulate_span(span, agents, counts, days_ago)


def collect_otel_stats(agents: list, days: int) -> dict:
    """Parse trace JSONL files for span counts, errors, sessions, and trend."""
    counts = defaultdict(lambda: {"total": 0, "errors": 0, "sessions": set(), "recent": 0, "older": 0})

    for fpath in find_trace_files(None, None, TELEMETRY_DIR):
        _parse_trace_file(fpath, agents, counts, days)

    result = {}
    for a in agents:
        c = counts[a]
        t = c["total"]
        e = c["errors"]
        r = c["recent"]
        o = c["older"]
        result[a] = {
            "spans": t,
            "errors": e,
            "error_pct": round(e / t * 100, 1) if t else None,
            "otel_sessions": len(c["sessions"]),
            "recent_7d": r,
            "prev_7d": o,
            "trend": "up" if r > o else ("flat" if r == o else "down"),
        }
    return result


def collect_cache_stats(agents: list) -> dict:
    """Parse agent-cache logs for invocation counts and session diversity."""
    result = {a: {"cache_invocations": 0, "cache_sessions": 0} for a in agents}
    agent_set = set(agents)

    log_files = glob.glob(f"{AGENT_CACHE_DIR}/*/agent-invocations.log")
    session_sets = defaultdict(set)

    for log_file in log_files:
        session_id = os.path.basename(os.path.dirname(log_file))
        with open(log_file, encoding="utf-8") as fh:
            for line in fh:
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue
                agent_name = parts[1]
                if agent_name not in agent_set:
                    continue
                # Only count STARTED entries
                if "STARTED" in parts:
                    result[agent_name]["cache_invocations"] += 1
                    session_sets[agent_name].add(session_id)

    for a in agents:
        result[a]["cache_sessions"] = len(session_sets[a])

    return result


def print_report(agents: list, otel: dict, cache: dict) -> None:
    header = f"{'Agent':<35} {'Spans':>6} {'Err%':>6} {'OtelSess':>9} {'CacheInv':>9} {'CacheSess':>10} {'7d':>4} {'P7d':>4} {'Trend':>5}"
    print(header)
    print("-" * len(header))
    for a in agents:
        o = otel[a]
        c = cache[a]
        err = f"{o['error_pct']}%" if o["error_pct"] is not None else "n/a"
        print(
            f"{a:<35} {o['spans']:>6} {err:>6} {o['otel_sessions']:>9} "
            f"{c['cache_invocations']:>9} {c['cache_sessions']:>10} "
            f"{o['recent_7d']:>4} {o['prev_7d']:>4} {o['trend']:>5}"
        )


def main() -> None:
    args = parse_args()
    agents = args.agents
    otel = collect_otel_stats(agents, args.days)
    cache = collect_cache_stats(agents)
    print_report(agents, otel, cache)


if __name__ == "__main__":
    main()
