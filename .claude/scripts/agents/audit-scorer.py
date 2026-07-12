#!/usr/bin/env python3
"""
Agent Audit Scorer — score a Claude Code agent on 6 dimensions (max 60).

Implements the scoring rubric from agents/agent-auditor.md:
  1. Telemetry Health    (OTEL spans)
  2. Definition Quality  (rule-based checklist)
  3. Prompt Engineering  (rule-based checklist)
  4. Overlap & Redundancy (Jaccard similarity)
  5. Usage Alignment     (category telemetry)
  6. Efficiency & Cost   (OTEL spans)

Usage:
  python3 scripts/agents/audit-scorer.py code-reviewer
  python3 scripts/agents/audit-scorer.py code-reviewer --days 14
  python3 scripts/agents/audit-scorer.py code-reviewer --json
  python3 scripts/agents/audit-scorer.py --all --days 30
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Shared imports
_scripts_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _scripts_dir)
from lib.cli_utils import TELEMETRY_DIR, add_telemetry_args
from parse.agent_telemetry_audit import find_trace_files, parse_spans, compute_stats
AGENTS_DIRS = [
    os.path.expanduser("~/.claude/agents"),
    os.path.expanduser("~/.claude/lazy-agents"),
]
AGENTS_SKILL_GLOB = os.path.expanduser("~/.claude/skills/*/agents/*.md")

STOPWORDS = frozenset(
    "the a an is are for and or to in of on with this that use when you it be "
    "as by from at do not can if will all has have your was but they been its "
    "each no so should would could may any".split()
)

GRADE_THRESHOLDS = [(48, "A"), (36, "B"), (24, "C"), (0, "D")]

# Category keywords that map to agent purposes
CATEGORY_KEYWORDS = {
    "code": {"code", "typescript", "javascript", "react", "node", "python", "implement", "write", "develop", "build"},
    "testing": {"test", "testing", "spec", "assert", "coverage", "unit", "integration", "e2e"},
    "review": {"review", "reviewer", "check", "audit", "inspect", "quality", "lint"},
    "documentation": {"doc", "documentation", "readme", "comment", "explain"},
    "exploration": {"explore", "search", "find", "discover", "codebase", "navigate"},
    "planning": {"plan", "design", "architect", "strategy", "approach"},
    "error-handling": {"error", "debug", "fix", "bug", "resolve", "troubleshoot"},
    "web": {"web", "fetch", "http", "api", "url", "browser"},
    "scraping": {"scrape", "scraping", "crawl", "extract", "parse"},
    "observability": {"otel", "telemetry", "trace", "metric", "monitor", "observability", "span"},
    "security": {"security", "vulnerability", "safety", "sanitize", "injection", "hardened"},
    "version-control": {"git", "commit", "branch", "merge", "version", "changelog", "conventional"},
    "development": {"develop", "feature", "implement", "codebase", "analyze", "structure", "refactor"},
    "frontend": {"frontend", "css", "html", "component", "layout", "responsive", "interface"},
    "devops": {"devops", "infrastructure", "pipeline", "deploy", "container", "environment"},
    "research": {"research", "market", "intelligence", "benchmark", "analyst", "competitive"},
    "general": {"general", "purpose", "multi", "versatile"},
}


# ---------------------------------------------------------------------------
# Agent definition parsing
# ---------------------------------------------------------------------------

def find_all_agent_files() -> list[str]:
    """Find all agent .md files across standard locations."""
    files = []
    for d in AGENTS_DIRS:
        if os.path.isdir(d):
            files.extend(glob.glob(os.path.join(d, "*.md")))
    files.extend(glob.glob(AGENTS_SKILL_GLOB))
    return sorted(set(files))


def parse_frontmatter(content: str) -> dict:
    """Extract YAML-like frontmatter from agent markdown."""
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm


def read_agent(path: str) -> dict:
    """Read and parse an agent definition file."""
    with open(path) as f:
        content = f.read()
    fm = parse_frontmatter(content)
    return {
        "path": path,
        "name": fm.get("name", Path(path).stem),
        "description": fm.get("description", ""),
        "tools": fm.get("tools", ""),
        "model": fm.get("model", ""),
        "content": content,
        "lines": len(content.splitlines()),
        "tool_set": set(t.strip() for t in fm.get("tools", "").split(",") if t.strip()),
    }


def extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, excluding stopwords."""
    words = re.findall(r"[a-z]+", text.lower())
    return set(w for w in words if w not in STOPWORDS and len(w) > 2)


def infer_categories(agent: dict) -> set[str]:
    """Infer which categories an agent's description aligns with."""
    kw = extract_keywords(agent["description"] + " " + agent["name"])
    matched = set()
    for cat, cat_kw in CATEGORY_KEYWORDS.items():
        if kw & cat_kw:
            matched.add(cat)
    return matched or {"general"}


# ---------------------------------------------------------------------------
# Dimension 1: Telemetry Health
# ---------------------------------------------------------------------------

def _score_usage_freq(weekly_rate: float) -> int:
    if weekly_rate == 0:
        return 0
    if weekly_rate > 20:
        return 10
    if weekly_rate >= 5:
        return 7
    if weekly_rate >= 1:
        return 4
    return 1


def _score_error_rate(post_spans: list) -> tuple[int, float]:
    total = len(post_spans)
    errors = sum(1 for s in post_spans if s["has_error"] is True)
    error_pct = (errors / total * 100) if total else 0
    if total == 0:
        er = 0
    elif error_pct == 0:
        er = 10
    elif error_pct < 5:
        er = 7
    elif error_pct <= 15:
        er = 4
    else:
        er = 1
    return er, error_pct


def _score_trend(pre_spans: list) -> int:
    """Score usage trend: last 7d vs prior 7d."""
    dates = sorted(set(s["date"] for s in pre_spans))
    if len(dates) < 2:
        return 0
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    prior7_start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    last7 = sum(1 for s in pre_spans if s["date"] >= cutoff)
    prior7 = sum(1 for s in pre_spans if prior7_start <= s["date"] < cutoff)
    if prior7 > 0:
        change = (last7 - prior7) / prior7 * 100
    elif last7 > 0:
        change = 100
    else:
        change = 0
    if change > 20:
        return 10
    if change >= -20:
        return 7
    return 3


def _score_session_diversity(pre_spans: list) -> tuple[int, int]:
    sessions = len(set(s["session_id"] for s in pre_spans if s["session_id"]))
    if sessions > 5:
        sd = 10
    elif sessions >= 3:
        sd = 7
    elif sessions == 2:
        sd = 4
    elif sessions == 1:
        sd = 2
    else:
        sd = 0
    return sd, sessions


def score_telemetry_health(pre_spans: list, post_spans: list, days_span: int) -> dict:
    """Score telemetry health (0-10) with sub-metric breakdown."""
    weeks = max(days_span / 7, 1)
    weekly_rate = len(pre_spans) / weeks
    uf = _score_usage_freq(weekly_rate)
    er, error_pct = _score_error_rate(post_spans)
    tr = _score_trend(pre_spans)
    sd, sessions = _score_session_diversity(pre_spans)
    score = round(uf * 0.35 + er * 0.25 + tr * 0.20 + sd * 0.20, 1)
    return {
        "score": score,
        "usage_freq": {"weekly_rate": round(weekly_rate, 1), "score": uf},
        "error_rate": {"pct": round(error_pct, 1), "score": er},
        "trend": {"score": tr},
        "session_diversity": {"count": sessions, "score": sd},
    }


# ---------------------------------------------------------------------------
# Dimension 2: Definition Quality
# ---------------------------------------------------------------------------

def score_definition_quality(agent: dict) -> dict:
    """Score definition quality (0-10) via rule-based checklist."""
    content = agent["content"]
    fm = parse_frontmatter(content)
    checks = {}

    checks["has_name"] = 1 if fm.get("name") else 0
    checks["has_description"] = 1 if fm.get("description") else 0
    checks["has_tools"] = 1 if fm.get("tools") else 0
    checks["has_model"] = 1 if fm.get("model") else 0

    desc_len = len(fm.get("description", ""))
    checks["desc_20_200"] = 1 if 20 <= desc_len <= 200 else 0

    checks["has_when_section"] = 1 if re.search(r"##\s*When", content) else 0
    checks["has_output_section"] = 1 if re.search(r"##\s*(Output|Format|Response)", content, re.I) else 0
    checks["lines_30_200"] = 1 if 30 <= agent["lines"] <= 200 else 0

    all_tools = {"Read", "Write", "Edit", "MultiEdit", "Bash", "Grep", "Glob",
                 "Agent", "WebFetch", "WebSearch", "NotebookEdit"}
    checks["tools_restricted"] = 1 if agent["tool_set"] and agent["tool_set"] != all_tools else 0
    checks["has_sections"] = 1 if content.count("## ") >= 2 else 0

    score = sum(checks.values())
    return {"score": min(score, 10), "checks": checks}


# ---------------------------------------------------------------------------
# Dimension 3: Prompt Engineering
# ---------------------------------------------------------------------------

def score_prompt_engineering(agent: dict) -> dict:
    """Score prompt engineering quality (0-10) via rule-based checklist."""
    content = agent["content"]
    checks = {}

    checks["role_statement"] = 1 if re.search(r"You are\b", content) else 0
    checks["numbered_steps"] = 1.5 if re.search(r"\n\d+\.\s", content) else 0
    checks["guardrails"] = 1 if re.search(r"(guardrail|constraint|never|do not|avoid)\b", content, re.I) else 0
    checks["code_examples"] = 1 if "```" in content else 0
    checks["tables"] = 1 if re.search(r"\|.*\|.*\|", content) else 0
    checks["output_spec"] = 1.5 if re.search(r"##\s*(Output|Format|Response|Return)", content, re.I) else 0
    checks["markdown_structure"] = 1 if content.count("## ") >= 2 and re.search(r"\n- ", content) else 0
    checks["scope_boundaries"] = 1 if re.search(r"(scope|boundar|only|limit|restrict)\b", content, re.I) else 0

    score = sum(checks.values())
    return {"score": min(round((score / 9) * 10, 1), 10), "checks": checks}


# ---------------------------------------------------------------------------
# Dimension 4: Overlap & Redundancy
# ---------------------------------------------------------------------------

def score_overlap(agent: dict, all_agents: list[dict]) -> dict:
    """Score overlap (0-10). Lower overlap = higher score."""
    agent_kw = extract_keywords(agent["content"])
    max_overlap = 0.0
    max_peer = ""

    for peer in all_agents:
        if peer["name"] == agent["name"]:
            continue
        # Pre-filter: must share at least 1 tool
        if not (agent["tool_set"] & peer["tool_set"]):
            continue

        tool_union = agent["tool_set"] | peer["tool_set"]
        tool_j = len(agent["tool_set"] & peer["tool_set"]) / len(tool_union) if tool_union else 0
        if tool_j <= 0.8 and len(all_agents) > 50:
            continue

        peer_kw = extract_keywords(peer["content"])
        kw_union = agent_kw | peer_kw
        kw_j = len(agent_kw & peer_kw) / len(kw_union) if kw_union else 0

        if kw_j > max_overlap:
            max_overlap = kw_j
            max_peer = peer["name"]

    score = max(0, round(10 - (max_overlap * 10), 1))
    return {"score": score, "max_overlap": round(max_overlap, 3), "max_peer": max_peer}


# ---------------------------------------------------------------------------
# Dimension 5: Usage Alignment
# ---------------------------------------------------------------------------

def score_usage_alignment(agent: dict, pre_spans: list) -> dict:
    """Score category alignment (0-10)."""
    if not pre_spans:
        return {"score": 0, "note": "no telemetry"}

    expected = infer_categories(agent)
    cats = Counter(s["category"] for s in pre_spans if s["category"])
    total = sum(cats.values())
    if total == 0:
        return {"score": 0, "note": "no category data"}

    matching = sum(v for k, v in cats.items() if k in expected)
    score = round((matching / total) * 10, 1)
    return {
        "score": min(score, 10),
        "expected": sorted(expected),
        "actual": dict(cats.most_common()),
        "matching_pct": round(matching / total * 100, 1),
    }


# ---------------------------------------------------------------------------
# Dimension 6: Efficiency & Cost
# ---------------------------------------------------------------------------

def _score_duration(
    ok_spans: list, post_spans: list, all_ok_spans: list, all_post_spans: list
) -> tuple[int, float | None]:
    """Score duration percentile vs all agents. Returns (score, agent_median_ms)."""
    agent_durs = sorted(s["duration_ms"] for s in (ok_spans or post_spans) if s["duration_ms"] is not None)
    all_durs = sorted(s["duration_ms"] for s in (all_ok_spans or all_post_spans) if s["duration_ms"] is not None)
    if not (agent_durs and all_durs):
        return 5, None  # neutral if no data
    agent_med = agent_durs[len(agent_durs) // 2]
    all_med = all_durs[len(all_durs) // 2]
    all_p75 = all_durs[int(len(all_durs) * 0.75)]
    if agent_med <= all_med:
        return 10, agent_med
    if agent_med <= all_p75:
        return 7, agent_med
    return 3, agent_med


def _score_amplification(post_spans: list) -> tuple[int, float, float]:
    """Score retry/error amplification weighted by session concentration.

    Returns (score, amp_pct, raw_amp_pct).
    """
    total = len(post_spans)
    err_count = sum(1 for s in post_spans if s["has_error"] is True)
    rl_count = sum(1 for s in post_spans if s["has_rate_limit"] is True)
    raw_amp_pct = (err_count + rl_count) / total * 100
    if err_count > 0:
        err_sessions = len(set(s["session_id"] for s in post_spans if s["has_error"] is True))
        total_sessions = len(set(s["session_id"] for s in post_spans))
        session_spread = err_sessions / total_sessions if total_sessions else 1
        # Concentrated errors (1 session) get 50% discount; spread across all sessions = full weight
        amp_pct = raw_amp_pct * (0.5 + 0.5 * session_spread)
    else:
        amp_pct = 0
    if amp_pct == 0:
        amp_s = 10
    elif amp_pct < 5:
        amp_s = 7
    elif amp_pct <= 15:
        amp_s = 4
    else:
        amp_s = 1
    return amp_s, amp_pct, raw_amp_pct


def _score_output_density(
    ok_spans: list, post_spans: list, all_ok_spans: list, all_post_spans: list
) -> int:
    """Score output density vs all agents median."""
    density_spans = ok_spans if ok_spans else post_spans
    all_density_spans = all_ok_spans if all_ok_spans else all_post_spans
    agent_out = sorted(s["output_size"] for s in density_spans if isinstance(s["output_size"], (int, float)) and s["output_size"] > 0)
    all_out = sorted(s["output_size"] for s in all_density_spans if isinstance(s["output_size"], (int, float)) and s["output_size"] > 0)
    if not (agent_out and all_out):
        return 5
    a_med = agent_out[len(agent_out) // 2]
    g_med = all_out[len(all_out) // 2]
    if a_med >= g_med:
        return 10
    if a_med >= g_med * 0.5:
        return 7
    return 3


def _score_background(post_spans: list, agent: dict) -> tuple[int, float, bool]:
    """Score background usage appropriateness. Returns (score, bg_pct, should_bg)."""
    total = len(post_spans)
    # Only check description+name to avoid false positives from rubric tables in content body
    desc_lower = (agent.get("description", "") + " " + agent.get("name", "")).lower()
    should_bg = any(w in desc_lower for w in ["proactiv", "after code", "automatic", "background"])
    bg_count = sum(1 for s in post_spans if s.get("is_background") is True)
    bg_pct = bg_count / total * 100 if total else 0
    if should_bg and bg_pct == 0:
        bg_s = 3  # penalty
    elif should_bg and bg_pct > 10:
        bg_s = 10
    else:
        bg_s = 7  # neutral
    return bg_s, bg_pct, should_bg


def score_efficiency(post_spans: list, all_post_spans: list, agent: dict) -> dict:
    """Score efficiency (0-10) with sub-metric breakdown."""
    if not post_spans:
        return {"score": 0, "note": "no telemetry"}

    # Separate success vs error spans — duration and output density should only
    # measure successful invocations to avoid double-counting with amplification
    ok_spans = [s for s in post_spans if s["has_error"] is not True]
    all_ok_spans = [s for s in all_post_spans if s["has_error"] is not True]

    dur_s, agent_med = _score_duration(ok_spans, post_spans, all_ok_spans, all_post_spans)
    amp_s, amp_pct, raw_amp_pct = _score_amplification(post_spans)
    out_s = _score_output_density(ok_spans, post_spans, all_ok_spans, all_post_spans)
    bg_s, bg_pct, should_bg = _score_background(post_spans, agent)

    score = round(dur_s * 0.30 + amp_s * 0.25 + out_s * 0.25 + bg_s * 0.20, 1)
    return {
        "score": score,
        "duration": {"score": dur_s, "agent_median_ms": round(agent_med, 1) if agent_med is not None else None},
        "amplification": {"pct": round(amp_pct, 1), "raw_pct": round(raw_amp_pct, 1), "score": amp_s},
        "output_density": {"score": out_s},
        "background": {"pct": round(bg_pct, 1), "should_bg": should_bg, "score": bg_s},
    }


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------

def grade(total: float) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if total >= threshold:
            return letter
    return "D"


def audit_agent(agent_name: str, files: list[str], all_agents: list[dict]) -> dict:
    """Run full 6-dimension audit for one agent."""
    # Find agent definition
    agent = None
    for a in all_agents:
        if a["name"] == agent_name:
            agent = a
            break
    if not agent:
        return {"error": f"Agent '{agent_name}' not found"}

    # Parse telemetry
    pre_spans, post_spans, all_post_spans = parse_spans(files, agent_name)

    dates = sorted(set(s["date"] for s in pre_spans)) if pre_spans else []
    if len(dates) >= 2:
        d0 = datetime.strptime(dates[0], "%Y-%m-%d")
        d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
        days_span = max((d1 - d0).days, 1)
    else:
        days_span = max(len(files), 1)

    d1 = score_telemetry_health(pre_spans, post_spans, days_span)
    d2 = score_definition_quality(agent)
    d3 = score_prompt_engineering(agent)
    d4 = score_overlap(agent, all_agents)
    d5 = score_usage_alignment(agent, pre_spans)
    d6 = score_efficiency(post_spans, all_post_spans, agent)

    total = round(d1["score"] + d2["score"] + d3["score"] + d4["score"] + d5["score"] + d6["score"], 1)

    return {
        "agent": agent_name,
        "path": agent["path"],
        "total": total,
        "grade": grade(total),
        "dimensions": {
            "telemetry_health": d1,
            "definition_quality": d2,
            "prompt_engineering": d3,
            "overlap_redundancy": d4,
            "usage_alignment": d5,
            "efficiency_cost": d6,
        },
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_scorecard(result: dict):
    """Pretty-print a single agent scorecard."""
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    dims = result["dimensions"]
    print(f"\n{'='*60}")
    print(f"  Agent Audit: {result['agent']}  —  {result['total']}/60  Grade: {result['grade']}")
    print(f"  {result['path']}")
    print(f"{'='*60}")

    rows = [
        ("Telemetry Health", dims["telemetry_health"]),
        ("Definition Quality", dims["definition_quality"]),
        ("Prompt Engineering", dims["prompt_engineering"]),
        ("Overlap & Redundancy", dims["overlap_redundancy"]),
        ("Usage Alignment", dims["usage_alignment"]),
        ("Efficiency & Cost", dims["efficiency_cost"]),
    ]
    print(f"\n  {'Dimension':<24} {'Score':>6}")
    print(f"  {'-'*24} {'-'*6}")
    for label, dim in rows:
        print(f"  {label:<24} {dim['score']:>5}/10")
    print(f"  {'-'*24} {'-'*6}")
    print(f"  {'TOTAL':<24} {result['total']:>5}/60")

    # Detail sections
    th = dims["telemetry_health"]
    print(f"\n  Telemetry: freq={th['usage_freq']['weekly_rate']}/wk({th['usage_freq']['score']}), "
          f"err={th['error_rate']['pct']}%({th['error_rate']['score']}), "
          f"trend({th['trend']['score']}), "
          f"sessions={th['session_diversity']['count']}({th['session_diversity']['score']})")

    dq = dims["definition_quality"]
    missing = [k for k, v in dq["checks"].items() if v == 0]
    if missing:
        print(f"  Definition missing: {', '.join(missing)}")

    pe = dims["prompt_engineering"]
    pe_missing = [k for k, v in pe["checks"].items() if v == 0]
    if pe_missing:
        print(f"  Prompting missing: {', '.join(pe_missing)}")

    ol = dims["overlap_redundancy"]
    if ol["max_peer"]:
        print(f"  Overlap: max peer={ol['max_peer']} (J={ol['max_overlap']:.3f})")

    ua = dims["usage_alignment"]
    if "expected" in ua:
        print(f"  Alignment: expected={ua['expected']}, actual={ua.get('actual', {})}, match={ua['matching_pct']}%")
    elif "note" in ua:
        print(f"  Alignment: {ua['note']}")

    ef = dims["efficiency_cost"]
    if "note" not in ef:
        dur_med = ef['duration'].get('agent_median_ms')
        dur_info = f"dur={dur_med}ms({ef['duration']['score']})" if dur_med else f"dur({ef['duration']['score']})"
        amp = ef['amplification']
        amp_info = f"amp={amp['pct']}%({amp['score']})"
        if amp.get('raw_pct') and amp['raw_pct'] != amp['pct']:
            amp_info += f" [raw={amp['raw_pct']}%]"
        print(f"  Efficiency: {dur_info}, {amp_info}, "
              f"output({ef['output_density']['score']}), bg={ef['background']['pct']}%({ef['background']['score']})")
    print()


def print_summary_table(results: list[dict]):
    """Print a summary table for multiple agents."""
    print(f"\n{'='*90}")
    print(f"  Agent Audit Summary")
    print(f"{'='*90}")
    print(f"\n  {'Agent':<22} {'Telem':>5} {'Defn':>5} {'Prompt':>6} {'Overlap':>7} {'Align':>5} {'Effic':>5} {'Total':>6} {'Grade':>5}")
    print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*6} {'-'*7} {'-'*5} {'-'*5} {'-'*6} {'-'*5}")
    for r in sorted(results, key=lambda x: x.get("total", 0), reverse=True):
        if "error" in r:
            print(f"  {r.get('agent', '?'):<22} {'ERROR':>50}")
            continue
        d = r["dimensions"]
        print(f"  {r['agent']:<22} {d['telemetry_health']['score']:>5} {d['definition_quality']['score']:>5} "
              f"{d['prompt_engineering']['score']:>6} {d['overlap_redundancy']['score']:>7} "
              f"{d['usage_alignment']['score']:>5} {d['efficiency_cost']['score']:>5} "
              f"{r['total']:>5}/60 {r['grade']:>5}")

    grades = Counter(r.get("grade", "?") for r in results if "error" not in r)
    print(f"\n  Distribution: A={grades.get('A',0)} B={grades.get('B',0)} C={grades.get('C',0)} D={grades.get('D',0)}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Score Claude Code agents on 6 audit dimensions (max 60)")
    parser.add_argument("agent", nargs="?", help="Agent name to audit (omit with --all)")
    parser.add_argument("--all", action="store_true", help="Audit all agents")
    add_telemetry_args(parser)
    args = parser.parse_args()

    if not args.agent and not args.all:
        parser.error("Provide an agent name or use --all")

    files = find_trace_files(args.month, args.days, args.telemetry_dir)
    all_agents = [read_agent(f) for f in find_all_agent_files()]

    if args.all:
        targets = [a["name"] for a in all_agents]
    else:
        targets = [args.agent]

    results = [audit_agent(name, files, all_agents) for name in targets]

    if args.json:
        json.dump(results if len(results) > 1 else results[0], sys.stdout, indent=2)
        print()
    elif len(results) == 1:
        print_scorecard(results[0])
    else:
        print_summary_table(results)
        for r in results:
            print_scorecard(r)


if __name__ == "__main__":
    main()
