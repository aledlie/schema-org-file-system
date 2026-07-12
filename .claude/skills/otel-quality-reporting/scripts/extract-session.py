#!/usr/bin/env python3
"""Extract session telemetry data (traces, logs, evaluations) by session ID."""

import json
import glob
import os
import sys
import re

_EXPECTED_PREFIX = os.path.expanduser("~")
_SESSION_ID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def _safe_telemetry_dir(raw: str) -> str:
    """Validate telemetry dir is under home directory (no path traversal)."""
    expanded = os.path.expanduser(raw)
    resolved = os.path.realpath(expanded)
    if not resolved.startswith(_EXPECTED_PREFIX):
        print(f"TELEMETRY_DIR outside home directory: {resolved}", file=sys.stderr)
        sys.exit(1)
    return resolved


def _validate_session_id(sid: str) -> str:
    """Validate session ID is a valid UUID format."""
    if not _SESSION_ID_RE.fullmatch(sid):
        print(f"Invalid session ID format: {sid!r}", file=sys.stderr)
        sys.exit(1)
    return sid


TELEMETRY_DIR = _safe_telemetry_dir(
    os.environ.get("CLAUDE_TELEMETRY_DIR", "~/.claude-history/telemetry")
)

# Span attribute constants
SESSION_START_SPAN_NAME = "hook:session-start"
SESSION_ID_ATTRIBUTE = "session.id"
TRACE_ID_ATTRIBUTE = "traceId"
START_TIME_NANO_CAMEL = "startTimeUnixNano"
START_TIME_NANO_SNAKE = "start_time_unix_nano"

# Mode constants
MODE_SESSION_ID = "session-id"
MODE_TRACES = "traces"
MODE_LOGS = "logs"
MODE_EVALUATIONS = "evaluations"

# Output preview limits
TRACE_PREVIEW_LIMIT = 5
EVAL_PREVIEW_LIMIT = 10


def load_jsonl(pattern, filter_fn):
    results = []
    for f in glob.glob(os.path.join(TELEMETRY_DIR, pattern)):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    if filter_fn(obj):
                        results.append(obj)
                except json.JSONDecodeError:
                    print(f"Skipping malformed JSON in {f}", file=sys.stderr)
    return results


def _parse_timestamp(obj: dict) -> int:
    """Parse timestamp, handling non-numeric values gracefully."""
    raw = obj.get(START_TIME_NANO_CAMEL) or obj.get(START_TIME_NANO_SNAKE) or 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def find_latest_session_id():
    """Scan telemetry files newest-first so incomplete latest files don't block discovery.

    Returns: tuple of (session_id or None, files_checked)
    """
    best_ts = -1
    last = None
    files = sorted(glob.glob(os.path.join(TELEMETRY_DIR, "traces-*.jsonl")), reverse=True)
    files_checked = 0
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                        if obj.get("name") == SESSION_START_SPAN_NAME:
                            sid = obj.get("attributes", {}).get(SESSION_ID_ATTRIBUTE, "")
                            if not sid:
                                continue
                            ts = _parse_timestamp(obj)
                            if ts > best_ts:
                                best_ts = ts
                                last = sid
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
        files_checked += 1
        # Once we found a session in this file, stop scanning older files
        # since they are guaranteed to have older sessions
        if last:
            break
    return (last, files_checked)


def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not session_id:
        session_id, checked_files = find_latest_session_id()
        if not session_id:
            print(f"NO_TRACES (checked {checked_files} files in {TELEMETRY_DIR})", file=sys.stderr)
            sys.exit(1)

    session_id = _validate_session_id(session_id)

    mode = sys.argv[2] if len(sys.argv) > 2 else MODE_TRACES

    if mode == MODE_SESSION_ID:
        print(session_id)
        return

    if mode == MODE_TRACES:
        traces = load_jsonl(
            "traces-*.jsonl",
            lambda obj: obj.get("attributes", {}).get(SESSION_ID_ATTRIBUTE) == session_id,
        )
        print(json.dumps({
            "session_id": session_id,
            "count": len(traces),
            "hooks": sorted({t.get("name", "<unknown>") for t in traces if t.get("name")}),
        }, indent=2))
        for t in traces[:TRACE_PREVIEW_LIMIT]:
            print(json.dumps(t, indent=2))
        return

    if mode == MODE_LOGS:
        session_spans = load_jsonl(
            "traces-*.jsonl",
            lambda obj: obj.get("attributes", {}).get(SESSION_ID_ATTRIBUTE) == session_id,
        )
        trace_ids = {t[TRACE_ID_ATTRIBUTE] for t in session_spans if TRACE_ID_ATTRIBUTE in t}
        logs = load_jsonl(
            "logs-*.jsonl",
            lambda obj: obj.get(TRACE_ID_ATTRIBUTE) in trace_ids,
        )
        print(json.dumps({
            "session_id": session_id,
            "count": len(logs),
            "trace_count": len(trace_ids),
        }, indent=2))
        for log in logs[:TRACE_PREVIEW_LIMIT]:
            print(json.dumps(log, indent=2))
        return

    if mode == MODE_EVALUATIONS:
        evals = load_jsonl(
            "evaluations-*.jsonl",
            lambda obj: obj.get("attributes", {}).get(SESSION_ID_ATTRIBUTE) == session_id,
        )
        print(json.dumps({
            "session_id": session_id,
            "count": len(evals),
        }, indent=2))
        for e in evals[:EVAL_PREVIEW_LIMIT]:
            print(json.dumps(e, indent=2))
        return

    print(f"Unknown mode: {mode!r}. Valid modes: session-id, traces, logs, evaluations", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
