#!/usr/bin/env python3
"""Compute rule-based quality metrics from session traces."""

import json
import glob
import os
import statistics
import sys

TELEMETRY_DIR = os.path.expanduser(os.environ.get("CLAUDE_TELEMETRY_DIR", "~/.claude-history/telemetry"))


def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not session_id:
        print("Usage: compute-metrics.py <session-id>", file=sys.stderr)
        sys.exit(1)

    traces = []
    skipped = 0
    for f in sorted(glob.glob(os.path.join(TELEMETRY_DIR, "traces-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    if obj.get("attributes", {}).get("session.id") == session_id:
                        traces.append(obj)
                except json.JSONDecodeError:
                    skipped += 1

    if skipped:
        print(f"Warning: skipped {skipped} malformed JSONL lines", file=sys.stderr)

    if not traces:
        print(f"Warning: no traces found for session {session_id}", file=sys.stderr)

    # tool_correctness
    tool_spans = [
        t for t in traces
        if t.get("name") in ("hook:builtin-post-tool", "hook:mcp-post-tool")
    ]
    success_count = sum(
        1 for t in tool_spans
        if t.get("attributes", {}).get("builtin.success",
           t.get("attributes", {}).get("mcp.success", False))
    )
    tool_correctness = success_count / len(tool_spans) if tool_spans else None

    # evaluation_latency
    durations = []
    for t in traces:
        d = t.get("duration")
        if d is None:
            continue
        if isinstance(d, list) and len(d) == 2:
            try:
                durations.append(float(d[0]) + float(d[1]) / 1e9)
            except (TypeError, ValueError):
                continue
    eval_latency = statistics.median(durations) if durations else None

    # task_completion
    task_creates = sum(
        1 for t in tool_spans
        if t.get("attributes", {}).get("builtin.tool") == "TaskCreate"
    )
    task_completes = sum(
        1 for t in tool_spans
        if t.get("attributes", {}).get("builtin.tool") == "TaskUpdate"
        and t.get("attributes", {}).get("builtin.task_status") == "completed"
    )
    task_completion = task_completes / task_creates if task_creates > 0 else None

    # token summary
    token_spans = [t for t in traces if t.get("name") == "hook:token-metrics-extraction"]
    total_input = sum(t.get("attributes", {}).get("tokens.input", 0) for t in token_spans)
    total_output = sum(t.get("attributes", {}).get("tokens.output", 0) for t in token_spans)
    total_cache = sum(t.get("attributes", {}).get("tokens.cache_read", 0) for t in token_spans)

    print(json.dumps({
        "tool_correctness": round(tool_correctness, 4) if tool_correctness is not None else None,
        "evaluation_latency_seconds": round(eval_latency, 6) if eval_latency is not None else None,
        "task_completion": round(task_completion, 4) if task_completion is not None else None,
        "total_spans": len(traces),
        "tool_spans": len(tool_spans),
        "token_summary": {
            "input": total_input,
            "output": total_output,
            "cache_read": total_cache,
            "total": total_input + total_output,
        },
        "hooks_used": sorted(set(t.get("name", "unknown") for t in traces)),
    }, indent=2))


if __name__ == "__main__":
    main()
