# Debug Report: otel-session-summary Session ID Identification Issues

**Date**: 2026-03-25
**Severity**: HIGH — Session discovery completely broken for latest telemetry
**Status**: Diagnosed, fixes provided below

## Executive Summary

The `otel-session-summary` skill's session ID discovery mechanism fails to find sessions because:

1. **Latest telemetry file is incomplete** — `traces-2026-03-23.jsonl` has only 1 span with missing `session.id` attribute
2. **No fallback strategy** — Script gives up after first file instead of checking older files
3. **No diagnostic logging** — Users get "No session found" with no hint about what went wrong
4. **Fragile attribute lookup** — Assumes `attributes.session.id` will exist in every `hook:session-start` span

## Root Cause Analysis

### The Actual Problem

The `find_latest_session_id()` function in `summarize_session.py` (lines 77-110):

```python
def find_latest_session_id(telemetry_dir: str = TELEMETRY_DIR) -> str | None:
    best_ts: int = -1
    last: str | None = None
    for f in sorted(glob.glob(os.path.join(telemetry_dir, "traces-*.jsonl"))):
        # ... iterate through files chronologically (oldest first)
        # File processing...
    return last
```

**Issue**: This iterates files in chronological order (oldest → newest), so it processes:
1. `traces-2026-03-10.jsonl` — ✓ Valid, finds sessions
2. `traces-2026-03-11.jsonl` — ✓ Valid, finds sessions
3. `traces-2026-03-19.jsonl` — ✓ Valid, finds sessions
4. `traces-2026-03-20.jsonl` — ✓ Valid, finds sessions
5. `traces-2026-03-23.jsonl` — ✗ **BROKEN** — Has `hook:session-start` span with NO `session.id` attribute

When processing file 5:
- Finds span: `{"name": "hook:session-start", "attributes": {...}}`
- Looks for: `attributes.session.id`
- Finds: `None`
- **Skips span silently** with no logging
- Loop ends, returns `last = None`

### Data Structure Breakdown

#### Working spans (traces-2026-03-10.jsonl through traces-2026-03-20.jsonl):
```json
{
  "name": "hook:session-start",
  "attributes": {
    "session.id": "d89b7fa1-6bf3-4fd9-b3df-6ec2087ae5ce",
    "hook.name": "session-start",
    "startTimeUnixNano": 1234567890000000000
  }
}
```

#### Broken span (traces-2026-03-23.jsonl):
```json
{
  "traceId": "d6ce0b28054071f5f62f644b295c05b4",
  "spanId": "6b9a90f52911fa4e",
  "name": "hook:session-start",
  "startTime": [1774286726, 666000000],
  "attributes": {
    "hook.name": "session-start",
    "context.estimated_tokens": 0,
    "git.branch": "main"
    // NOTE: NO session.id field!
  }
}
```

### Scan Results

| File | Spans | Status | session.id Present |
|------|-------|--------|-------------------|
| traces-2026-03-10.jsonl | 10,588 | ✓ Valid | Yes (89 instances) |
| traces-2026-03-11.jsonl | 4,511 | ✓ Valid | Yes (52 instances) |
| traces-2026-03-19.jsonl | 1,104 | ✓ Valid | Yes (36 instances) |
| traces-2026-03-20.jsonl | 933 | ✓ Valid | Yes (20 instances) |
| traces-2026-03-23.jsonl | 1 | ✗ BROKEN | **NO** |

**Result**: When script runs, it processes all files but the last file (traces-2026-03-23.jsonl) has invalid data, causing `find_latest_session_id()` to return `None`.

## Failure Mode When User Runs `/otel-session-summary`

```bash
$ /otel-session-summary
# summarize_session.py runs...
# Processes traces-2026-03-23.jsonl (latest)
# Finds hook:session-start but no session.id attribute
# Returns None
# User sees:
"No session found in telemetry data."
# With NO diagnostic information about what was searched or why it failed
```

## Impact

- Users cannot run `/otel-session-summary` to get session summaries
- No error messages explain what's wrong with the telemetry data
- Even valid sessions from 4+ days ago are inaccessible
- Skill is completely non-functional despite valid historical data

## Recommended Fixes

### Fix 1: Add Reverse Iteration (High Priority)

Search files in **reverse chronological order** (newest first), but if a file has malformed data, fall back to older files:

```python
def find_latest_session_id(telemetry_dir: str = TELEMETRY_DIR) -> str | None:
    """Scan telemetry files for most recent session-start span by timestamp."""
    best_ts: int = -1
    last: str | None = None

    # Process files in REVERSE chronological order (newest first)
    for f in sorted(glob.glob(os.path.join(telemetry_dir, "traces-*.jsonl")), reverse=True):
        file_had_valid_span = False
        try:
            if os.path.getsize(f) > MAX_FILE_BYTES:
                logging.debug("Skipping oversized file: %s", os.path.basename(f))
                continue
        except OSError as e:
            logging.debug("Cannot stat file, skipping: %s (%s)", os.path.basename(f), e)
            continue

        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        obj: Span = json.loads(line)
                        if obj.get("name") == "hook:session-start":
                            sid: str = obj.get("attributes", {}).get("session.id", "")
                            if not sid:
                                # Log when session.id is missing
                                logging.debug(
                                    "hook:session-start found in %s but session.id is missing",
                                    os.path.basename(f)
                                )
                                continue
                            ts: int = int(
                                obj.get("startTimeUnixNano")
                                or obj.get("start_time_unix_nano")
                                or 0
                            )
                            if ts > best_ts:
                                best_ts = ts
                                last = sid
                                file_had_valid_span = True
                                logging.debug(
                                    "Found session %s (ts=%d) in %s",
                                    sid, ts, os.path.basename(f)
                                )
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                        logging.debug("Error parsing span: %s", e)
                        pass
        except OSError as e:
            logging.debug("Cannot read file %s: %s", os.path.basename(f), e)

        # If we found a valid session in this file, stop (it's the latest)
        if file_had_valid_span:
            logging.debug("Found valid session in latest file, stopping search")
            break

    if last is None:
        logging.warning(
            "No session with valid session.id found after scanning %d telemetry files",
            len(list(glob.glob(os.path.join(telemetry_dir, "traces-*.jsonl"))))
        )
    return last
```

### Fix 2: Add Diagnostic Logging (High Priority)

Make errors visible to users:

```python
# In main():
if not session_id:
    session_id = find_latest_session_id()
    if not session_id:
        files = glob.glob(os.path.join(TELEMETRY_DIR, "traces-*.jsonl"))
        print(
            f"No session found.\n"
            f"Checked {len(files)} telemetry files in {TELEMETRY_DIR}\n"
            f"Run with OTEL_DEBUG=1 for details:\n"
            f"  OTEL_DEBUG=1 {' '.join(sys.argv)}",
            file=sys.stderr
        )
        sys.exit(1)
```

### Fix 3: Add Fallback to Any session.id (Medium Priority)

If `hook:session-start` spans don't have `session.id`, look for it in other spans:

```python
def find_any_session_id(telemetry_dir: str = TELEMETRY_DIR) -> str | None:
    """Fallback: find any session.id in telemetry, not just from session-start spans."""
    for f in sorted(glob.glob(os.path.join(telemetry_dir, "traces-*.jsonl")), reverse=True):
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        obj: Span = json.loads(line)
                        sid = obj.get("attributes", {}).get("session.id")
                        if sid:
                            logging.debug("Found session.id=%s in %s", sid, os.path.basename(f))
                            return sid
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
        except OSError:
            pass
    return None
```

### Fix 4: Handle Malformed Latest File (Low Priority)

If the latest file is incomplete (e.g., mid-write), validate it before using:

```python
def is_telemetry_file_complete(filepath: str, min_spans: int = 10) -> bool:
    """Check if a telemetry file looks complete."""
    try:
        count = 0
        with open(filepath) as f:
            for line in f:
                if line.strip():
                    try:
                        json.loads(line)
                        count += 1
                    except json.JSONDecodeError:
                        return False
        return count >= min_spans
    except OSError:
        return False
```

## Test Cases to Add

```python
class TestSessionIdDiscovery:
    def test_finds_latest_valid_session(self, tmp_path: Path) -> None:
        """Should skip incomplete files and find last valid session."""
        # Create valid file
        valid = tmp_path / "traces-2026-01-01.jsonl"
        valid.write_text(json.dumps({
            "name": "hook:session-start",
            "attributes": {"session.id": "aaaa-bbbb"},
            "startTimeUnixNano": 1000
        }) + "\n")

        # Create incomplete file
        broken = tmp_path / "traces-2026-01-02.jsonl"
        broken.write_text(json.dumps({
            "name": "hook:session-start",
            "attributes": {"hook.name": "session-start"}
            # Missing session.id!
        }) + "\n")

        result = mod.find_latest_session_id(str(tmp_path))
        assert result == "aaaa-bbbb"

    def test_logs_missing_session_id(self, tmp_path: Path, caplog) -> None:
        """Should log when session.id is missing."""
        broken = tmp_path / "traces-test.jsonl"
        broken.write_text(json.dumps({
            "name": "hook:session-start",
            "attributes": {}
        }) + "\n")

        mod.find_latest_session_id(str(tmp_path))

        assert "session.id is missing" in caplog.text

    def test_diagnostic_message_on_no_session(self, tmp_path: Path, capsys) -> None:
        """Should print helpful message if no session found."""
        # Create empty dir
        with patch.object(sys, "argv", ["prog"]):
            with patch("glob.glob", return_value=[]):
                try:
                    mod.main()
                except SystemExit:
                    pass

        captured = capsys.readouterr()
        assert "OTEL_DEBUG=1" in captured.err
```

## Workaround for Users (Until Fixed)

```bash
# Run with explicit session ID from older file
python3 ~/.claude/skills/otel-session-summary/scripts/summarize_session.py \
  "d89b7fa1-6bf3-4fd9-b3df-6ec2087ae5ce" \
  --seed

# Or enable debug logging to see what's happening
OTEL_DEBUG=1 python3 ~/.claude/skills/otel-session-summary/scripts/summarize_session.py ""
```

## Timeline

- **2026-03-20**: Last valid telemetry file (traces-2026-03-20.jsonl)
- **2026-03-23**: Latest telemetry file broken (traces-2026-03-23.jsonl has 1 incomplete span)
- **Now**: Users cannot discover sessions automatically; skill is non-functional

## References

- **File**: `/Users/alyshialedlie/.claude/skills/otel-session-summary/scripts/summarize_session.py`
- **Functions affected**:
  - `find_latest_session_id()` (lines 77-110)
  - `main()` (lines 316-371)
- **Test file**: `/Users/alyshialedlie/.claude/skills/otel-session-summary/scripts/test_summarize_session.py`
