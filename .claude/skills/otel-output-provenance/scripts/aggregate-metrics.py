#!/usr/bin/env python3
"""Compute aggregate telemetry metrics across multiple sessions.

Usage:
  aggregate-metrics.py <session-id-1> [session-id-2] ... [session-id-N]

Output: JSON with per-session metrics and aggregate totals.
"""

import json
import glob
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

TELEMETRY_DIR = os.path.expanduser(os.environ.get("CLAUDE_TELEMETRY_DIR", "~/.claude-history/telemetry"))
EST = timezone(timedelta(hours=-5))


def load_session_traces(session_id):
    """Load all trace spans for a session."""
    traces = []
    for f in sorted(glob.glob(os.path.join(TELEMETRY_DIR, "traces-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    if obj.get("attributes", {}).get("session.id") == session_id:
                        traces.append(obj)
                except json.JSONDecodeError:
                    pass
    return traces


def load_session_evaluations(session_id):
    """Load evaluations for a session."""
    evals = []
    for f in sorted(glob.glob(os.path.join(TELEMETRY_DIR, "evaluations-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    sid = (obj.get("attributes", {}).get("session.id", "")
                           or obj.get("sessionId", ""))
                    if sid == session_id:
                        evals.append(obj)
                except json.JSONDecodeError:
                    pass
    return evals


def compute_session_metrics(session_id, traces):
    """Compute metrics for a single session."""
    # Time range
    epochs = []
    for t in traces:
        start = t.get("startTime", [0, 0])
        epoch = start[0] if isinstance(start, list) else 0
        if epoch > 0:
            epochs.append(epoch)

    min_epoch = min(epochs) if epochs else 0
    max_epoch = max(epochs) if epochs else 0
    start_est = datetime.fromtimestamp(min_epoch, tz=EST).strftime("%Y-%m-%d %H:%M:%S") if min_epoch else None
    end_est = datetime.fromtimestamp(max_epoch, tz=EST).strftime("%Y-%m-%d %H:%M:%S") if max_epoch else None
    duration_min = round((max_epoch - min_epoch) / 60, 1) if max_epoch > min_epoch else 0

    # Tool spans
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

    # Tool usage profile
    tool_counts = defaultdict(int)
    for t in tool_spans:
        tool = t.get("attributes", {}).get("builtin.tool", "") or t.get("attributes", {}).get("mcp.tool", "")
        if tool:
            tool_counts[tool] += 1

    # Evaluation latency
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

    # Task completion
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

    # Agent descriptions
    agent_descs = set()
    for t in traces:
        desc = t.get("attributes", {}).get("agent.description", "")
        if desc:
            agent_descs.add(desc)

    # Task IDs and statuses
    task_ids = set()
    for t in traces:
        tid = t.get("attributes", {}).get("builtin.task_id")
        if tid:
            task_ids.add(str(tid))

    # Token metrics (from token-metrics-extraction spans)
    token_spans = [t for t in traces if t.get("name") == "hook:token-metrics-extraction"]
    token_summary = {
        "input": sum(t.get("attributes", {}).get("tokens.input", 0) for t in token_spans),
        "output": sum(t.get("attributes", {}).get("tokens.output", 0) for t in token_spans),
        "cache_read": sum(t.get("attributes", {}).get("tokens.cache_read", 0) for t in token_spans),
        "cache_creation": sum(t.get("attributes", {}).get("tokens.cache_creation", 0) for t in token_spans),
        "messages": sum(t.get("attributes", {}).get("tokens.messages", 0) for t in token_spans),
    }

    # Models used
    models = set()
    for t in token_spans:
        model = t.get("attributes", {}).get("tokens.model", "")
        if model and model != "<synthetic>":
            models.add(model)

    # Hooks used
    hooks = sorted(set(t.get("name", "") for t in traces))

    return {
        "session_id": session_id,
        "total_spans": len(traces),
        "tool_spans": len(tool_spans),
        "start": start_est,
        "end": end_est,
        "duration_minutes": duration_min,
        "tool_correctness": round(tool_correctness, 4) if tool_correctness is not None else None,
        "evaluation_latency_seconds": round(eval_latency, 6) if eval_latency is not None else None,
        "task_completion": round(task_completion, 4) if task_completion is not None else None,
        "tools": dict(tool_counts),
        "agent_descriptions": sorted(agent_descs),
        "task_ids": sorted(task_ids),
        "token_summary": token_summary,
        "models": sorted(models),
        "hooks": hooks,
    }


def compute_token_window(min_epoch, max_epoch):
    """Compute token usage for a time window from all token-metrics-extraction spans."""
    by_model = defaultdict(lambda: {"count": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})

    for f in sorted(glob.glob(os.path.join(TELEMETRY_DIR, "traces-*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("name") != "hook:token-metrics-extraction":
                    continue
                start = obj.get("startTime", [0, 0])
                epoch = start[0] if isinstance(start, list) else 0
                if epoch < min_epoch or epoch > max_epoch:
                    continue
                attrs = obj.get("attributes", {})
                model = attrs.get("tokens.model", "unknown")
                if model == "<synthetic>":
                    model = "synthetic"
                m = by_model[model]
                m["count"] += 1
                m["input"] += attrs.get("tokens.input", 0)
                m["output"] += attrs.get("tokens.output", 0)
                m["cache_read"] += attrs.get("tokens.cache_read", 0)
                m["cache_creation"] += attrs.get("tokens.cache_creation", 0)

    return dict(by_model)


def main():
    if len(sys.argv) < 2:
        print("Usage: aggregate-metrics.py <session-id> [session-id...]", file=sys.stderr)
        sys.exit(1)

    session_ids = sys.argv[1:]
    per_session = []
    all_min_epoch = float("inf")
    all_max_epoch = 0

    for sid in session_ids:
        traces = load_session_traces(sid)
        metrics = compute_session_metrics(sid, traces)

        # Track global time range
        for t in traces:
            start = t.get("startTime", [0, 0])
            epoch = start[0] if isinstance(start, list) else 0
            if epoch > 0:
                all_min_epoch = min(all_min_epoch, epoch)
                all_max_epoch = max(all_max_epoch, epoch)

        # Load evaluations
        evals = load_session_evaluations(sid)
        eval_counts = defaultdict(int)
        for e in evals:
            name = e.get("evaluationName", "") or e.get("attributes", {}).get("evaluation.name", "")
            if name:
                eval_counts[name] += 1
        metrics["evaluation_counts"] = dict(eval_counts)
        metrics["total_evaluations"] = len(evals)

        per_session.append(metrics)

    # Aggregate totals
    total_spans = sum(s["total_spans"] for s in per_session)
    total_tool_spans = sum(s["tool_spans"] for s in per_session)
    total_success = sum(
        s["tool_spans"] * s["tool_correctness"]
        for s in per_session
        if s["tool_correctness"] is not None
    )
    total_evals = sum(s["total_evaluations"] for s in per_session)

    agg_tool_correctness = total_success / total_tool_spans if total_tool_spans > 0 else None
    latencies = [s["evaluation_latency_seconds"] for s in per_session if s["evaluation_latency_seconds"] is not None]
    agg_latency = statistics.median(latencies) if latencies else None

    # Aggregate task completion (use best available)
    task_completions = [s["task_completion"] for s in per_session if s["task_completion"] is not None]
    agg_task_completion = max(task_completions) if task_completions else None

    # Aggregate tool counts
    agg_tools = defaultdict(int)
    for s in per_session:
        for tool, count in s["tools"].items():
            agg_tools[tool] += count

    # Token window
    token_by_model = {}
    if all_min_epoch < float("inf") and all_max_epoch > 0:
        token_by_model = compute_token_window(all_min_epoch, all_max_epoch)

    result = {
        "session_count": len(per_session),
        "aggregate": {
            "total_spans": total_spans,
            "total_tool_spans": total_tool_spans,
            "tool_correctness": round(agg_tool_correctness, 4) if agg_tool_correctness is not None else None,
            "evaluation_latency_seconds": round(agg_latency, 6) if agg_latency is not None else None,
            "task_completion": round(agg_task_completion, 4) if agg_task_completion is not None else None,
            "total_evaluations": total_evals,
            "tools": dict(agg_tools),
            "token_by_model": token_by_model,
        },
        "per_session": per_session,
    }

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
