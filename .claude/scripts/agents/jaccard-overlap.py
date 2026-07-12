#!/usr/bin/env python3
"""
agent-jaccard-overlap.py

Compute pairwise Jaccard similarity coefficients for agent manifests
based on their tool sets and keyword vocabularies. Flags pairs with J > 0.30
as overlap risks per the agent governance standard.

Usage:
  python3 ~/.claude/scripts/agents/jaccard-overlap.py
  python3 ~/.claude/scripts/agents/jaccard-overlap.py --threshold 0.25
  python3 ~/.claude/scripts/agents/jaccard-overlap.py --min-score 0.10
"""

import argparse

AGENT_TOOLS = {
    "auto-error-resolver": {"Read", "Write", "Edit", "MultiEdit", "Bash"},
    "code-simplifier": {"Read", "Write", "Edit", "MultiEdit", "Grep", "Glob"},
    "code-reviewer": {"Read", "Grep", "Glob", "Bash"},
    "agent-auditor": {"Read", "Write", "Edit", "Glob", "Grep", "Bash"},
    "skill-auditor": {"Read", "Write", "Edit", "Glob", "Grep", "Bash"},
    "web-research-analyst": {"Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch"},
    "webscraping-research-analyst": {"Read", "Grep", "Glob", "Bash", "WebFetch"},
    "genai-quality-monitor": {"Read", "Grep", "Glob", "Bash", "WebFetch"},
    "telemetry-archaeologist": {"Read", "Grep", "Glob", "Bash"},
    "telemetry-backfill": {"Read", "Grep", "Glob", "Bash"},
}

AGENT_KEYWORDS = {
    "auto-error-resolver": {
        "debug", "error", "typescript", "runtime", "test",
        "fix", "verify", "tsc", "logs", "compilation",
    },
    "code-simplifier": {
        "simplify", "refactor", "readability", "clarity",
        "maintainability", "clean", "code", "nesting", "duplication",
    },
    "code-reviewer": {
        "review", "typescript", "react", "node", "security",
        "type safety", "performance", "code", "modularity",
    },
    "agent-auditor": {
        "audit", "agent", "manifest", "governance", "routing",
        "telemetry", "rewrite", "dimension", "frontmatter", "scoring",
    },
    "skill-auditor": {
        "skill", "audit", "SKILL", "plugin", "activation",
        "injection", "telemetry", "evaluation", "frontmatter", "conversion",
    },
    "web-research-analyst": {
        "research", "market", "competitive", "business", "data",
        "web", "trends", "analysis", "intelligence", "sources",
    },
    "webscraping-research-analyst": {
        "scraping", "crawler", "extraction", "robots", "anti-bot",
        "library", "ethical", "web", "framework", "parsing",
    },
    "genai-quality-monitor": {
        "genai", "llm", "evaluation", "quality", "hallucination",
        "faithfulness", "metrics", "judge", "coherence", "relevance",
    },
    "telemetry-archaeologist": {
        "telemetry", "spans", "traces", "session", "otel",
        "correlate", "locate", "storage", "cross-reference", "jsonl",
    },
    "telemetry-backfill": {
        "backfill", "reconstruct", "missing", "spans", "otel",
        "recovery", "provenance", "idempotent", "secondary", "sources",
    },
}

DEFAULT_THRESHOLD = 0.30
DEFAULT_MIN_SCORE = 0.10


def jaccard(set_a: set, set_b: set) -> float:
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pairwise Jaccard overlap for agent manifests")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="J threshold for flagging (default 0.30)")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE, help="Minimum J to display (default 0.10)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agents = list(AGENT_TOOLS.keys())

    print(f"Pairwise Jaccard similarity (tools + keywords combined)")
    print(f"Flag threshold: J > {args.threshold}  |  Display minimum: J >= {args.min_score}")
    print("-" * 72)

    pairs = []
    for i, a in enumerate(agents):
        sa = AGENT_TOOLS[a] | AGENT_KEYWORDS[a]
        for b in agents[i + 1 :]:
            sb = AGENT_TOOLS[b] | AGENT_KEYWORDS[b]
            j = jaccard(sa, sb)
            pairs.append((j, a, b))

    pairs.sort(reverse=True)

    for j, a, b in pairs:
        if j < args.min_score:
            continue
        flag = "  *** OVERLAP FLAG" if j > args.threshold else ""
        print(f"  {a:<35} vs  {b:<35}  J={j:.3f}{flag}")

    flagged = [(j, a, b) for j, a, b in pairs if j > args.threshold]
    print()
    print(f"Total pairs flagged (J > {args.threshold}): {len(flagged)}")


if __name__ == "__main__":
    main()
