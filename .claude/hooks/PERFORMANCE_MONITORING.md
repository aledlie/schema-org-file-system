# Hook Performance Monitoring Guide

Complete guide for adding performance monitoring to Claude Code hooks.

---

## Overview

The performance monitoring library (`lib/performance-monitor.sh`) provides:
- Automatic timing of hook execution
- Performance logging to `~/.claude/logs/hook-performance.log`
- Detection of slow hooks (>1000ms)
- Section-level timing for complex hooks
- Success/failure tracking

---

## Quick Start

### 1. Simple Hook (Recommended)

For most hooks, add these 3 lines:

```bash
#!/bin/bash

# Add at the top
source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "my-hook-name"

# Your existing hook code here
# ... your logic ...

# Add at the end
perf_end "success"
```

**Example:**

```bash
#!/bin/bash

# Source performance library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/performance-monitor.sh"

# Start timing
perf_start "skill-activation-prompt"

# Existing hook logic
cd "$SCRIPT_DIR"
cat | npx tsx skill-activation-prompt.ts

# End timing
perf_end "success"
```

---

### 2. Hook with Error Handling

Track success/failure:

```bash
#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "my-hook"

# Run your command
your-command arg1 arg2
EXIT_CODE=$?

# Log based on exit code
if [ $EXIT_CODE -eq 0 ]; then
    perf_end "success"
else
    perf_end "failed (exit $EXIT_CODE)"
fi

exit $EXIT_CODE
```

---

### 3. Hook with Conditional Logic

Log skipped executions:

```bash
#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "my-hook"

# Check condition
if [ -n "$SKIP_HOOK" ]; then
    perf_log "Skipped (SKIP_HOOK set)"
    perf_end "skipped"
    exit 0
fi

# Normal execution
run-hook-logic

perf_end "success"
```

---

## API Reference

### `perf_start "hook-name"`

Start timing a hook.

**Usage:**
```bash
perf_start "my-hook-name"
```

**Parameters:**
- `hook-name`: Identifier for this hook (used in logs)

**Notes:**
- Call once at the beginning of your hook
- Required before `perf_end`

---

### `perf_end [status]`

End timing and write to log.

**Usage:**
```bash
perf_end "success"
perf_end "failed (exit 1)"
perf_end "skipped"
```

**Parameters:**
- `status` (optional): Status message (default: "success")

**Log Format:**
```
[2025-01-17 14:23:45] hook-name | 123ms | success
[2025-01-17 14:24:10] slow-hook | 1500ms | success ⚠️ SLOW
[2025-01-17 14:25:00] failed-hook | 50ms | failed (exit 1)
```

**Slow Hook Detection:**
- Hooks >1000ms are flagged with ⚠️ SLOW

---

### `perf_log "message"`

Add a custom log entry.

**Usage:**
```bash
perf_log "Processing 10 files..."
perf_log "validation: 50ms"
```

**Log Format:**
```
[2025-01-17 14:23:45] hook-name | Processing 10 files...
```

**Use Cases:**
- Log milestones in long-running hooks
- Track section timings
- Debug information

---

### `perf_wrap "name" command [args...]`

Wrap a single command with timing.

**Usage:**
```bash
perf_wrap "tsc-compile" npx tsc --noEmit
perf_wrap "git-status" git status
```

**Benefits:**
- All-in-one: start, run, log, end
- Captures exit code
- Automatic success/failure tracking

**Example:**
```bash
#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"

# Entire hook is wrapped
perf_wrap "my-hook" npx tsx my-script.ts
```

---

## Advanced Usage

### Section Timing

For complex hooks with multiple steps:

```bash
#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "complex-hook"

# Function to time sections
time_section() {
    local name="$1"
    local start=$(date +%s%N)

    shift
    "$@"

    local end=$(date +%s%N)
    local duration=$((($end - $start) / 1000000))
    perf_log "$name: ${duration}ms"
}

# Time each section
time_section "validation" validate-inputs
time_section "processing" process-data
time_section "cleanup" cleanup-temp-files

perf_end "success"
```

**Log Output:**
```
[2025-01-17 14:23:45] complex-hook | validation: 50ms
[2025-01-17 14:23:45] complex-hook | processing: 200ms
[2025-01-17 14:23:45] complex-hook | cleanup: 10ms
[2025-01-17 14:23:45] complex-hook | 260ms | success
```

---

### Conditional Performance Tracking

Only track performance in certain environments:

```bash
#!/bin/bash

# Only enable perf tracking if variable is set
if [ -n "$ENABLE_PERF_TRACKING" ]; then
    source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
    perf_start "my-hook"
fi

# Your hook logic
run-hook

# End tracking if enabled
if [ -n "$ENABLE_PERF_TRACKING" ]; then
    perf_end "success"
fi
```

---

### Custom Log File

Override the default log location:

```bash
#!/bin/bash

# Set custom log location
export CLAUDE_LOGS_DIR="/custom/path/to/logs"

source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "my-hook"

# Hook logic...

perf_end "success"
```

---

## Migration Guide

### Before (No Monitoring)

```bash
#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")"
cat | npx tsx my-script.ts
```

### After (With Monitoring)

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/performance-monitor.sh"
perf_start "my-script"

cd "$SCRIPT_DIR"
cat | npx tsx my-script.ts
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    perf_end "success"
else
    perf_end "failed (exit $EXIT_CODE)"
fi

exit $EXIT_CODE
```

### Changes Made:
1. ✅ Source performance library
2. ✅ Call `perf_start` with hook name
3. ✅ Capture exit code
4. ✅ Call `perf_end` with status
5. ✅ Exit with original code

---

## Analyzing Performance Logs

### View Recent Performance

```bash
# Last 20 entries
tail -20 ~/.claude/logs/hook-performance.log

# Watch in real-time
tail -f ~/.claude/logs/hook-performance.log
```

### Find Slow Hooks

```bash
# Hooks over 1000ms
grep "SLOW" ~/.claude/logs/hook-performance.log

# Hooks over 500ms (custom threshold)
awk -F'|' '$2 ~ /[0-9]+ms/ && $2+0 > 500' ~/.claude/logs/hook-performance.log
```

### Hook Statistics

```bash
# Average execution time for a specific hook
grep "skill-activation-prompt" ~/.claude/logs/hook-performance.log | \
  awk -F'|' '{sum+=$2; count++} END {print sum/count "ms average"}'

# Count hook executions
grep "my-hook" ~/.claude/logs/hook-performance.log | wc -l
```

### Failed Hooks

```bash
# Find all failures
grep "failed" ~/.claude/logs/hook-performance.log

# Count failures by hook
grep "failed" ~/.claude/logs/hook-performance.log | \
  awk -F'|' '{print $1}' | sort | uniq -c
```

---

## Performance Analysis Script

Create `~/.claude/scripts/analyze-hook-performance.sh`:

```bash
#!/bin/bash

LOG_FILE="${CLAUDE_LOGS_DIR:-$HOME/.claude/logs}/hook-performance.log"

echo "=== Hook Performance Analysis ==="
echo ""

# Total executions
echo "Total executions: $(wc -l < "$LOG_FILE")"

# Slow hooks
slow_count=$(grep -c "SLOW" "$LOG_FILE" 2>/dev/null || echo 0)
echo "Slow hooks (>1000ms): $slow_count"

# Failed hooks
failed_count=$(grep -c "failed" "$LOG_FILE" 2>/dev/null || echo 0)
echo "Failed hooks: $failed_count"

echo ""
echo "=== Top 5 Slowest Hooks ==="
awk -F'|' '$2 ~ /[0-9]+ms/ {print $2, $1, $3}' "$LOG_FILE" | \
  sort -rn | \
  head -5

echo ""
echo "=== Hook Execution Count ==="
awk -F'|' '{gsub(/^ *| *$/, "", $1); print $1}' "$LOG_FILE" | \
  sed 's/\[.*\] //' | \
  sort | uniq -c | sort -rn | head -10
```

---

## Best Practices

### Do ✅

- **Always** call `perf_start` and `perf_end` in pairs
- **Always** capture and preserve exit codes
- **Use descriptive names** for hooks
- **Log important milestones** with `perf_log`
- **Track failures** with status messages
- **Review logs** regularly for slow hooks

### Don't ❌

- Don't add performance tracking to performance-critical hooks if overhead matters
- Don't forget to source the library
- Don't call `perf_end` multiple times
- Don't hardcode log paths (use `CLAUDE_LOGS_DIR`)
- Don't ignore slow hook warnings

---

## Troubleshooting

### Performance library not found

**Error:**
```
./my-hook.sh: line 3: performance-monitor.sh: No such file or directory
```

**Fix:**
```bash
# Ensure correct path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/performance-monitor.sh"

# Verify library exists
ls ~/.claude/hooks/lib/performance-monitor.sh
```

### Logs directory doesn't exist

**Error:**
```
mkdir: cannot create directory
```

**Fix:**
```bash
# Create logs directory
mkdir -p ~/.claude/logs

# Or set environment variable
export CLAUDE_LOGS_DIR="$HOME/.claude/logs"
```

### High-resolution timing not working

**Error:**
```
Timing shows 0ms for fast hooks
```

**Fix:**
The library uses:
- macOS: Perl's Time::HiRes (microsecond precision)
- Linux: `date +%s%N` (nanosecond precision)

Ensure these are available on your system.

---

## Log Rotation

Prevent logs from growing too large:

```bash
# Add to crontab
# Rotate logs monthly
0 0 1 * * mv ~/.claude/logs/hook-performance.log ~/.claude/logs/hook-performance-$(date +%Y%m).log && touch ~/.claude/logs/hook-performance.log
```

Or use logrotate:

```
# /etc/logrotate.d/claude-hooks
/Users/you/.claude/logs/hook-performance.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

---

## OpenTelemetry Integration

The hooks system now integrates with OpenTelemetry for comprehensive observability:

### Automatic Telemetry

All hooks automatically export telemetry via OTLP:
- **Traces**: Hook execution spans with timing
- **Metrics**: `hook.duration`, `hook.executions` counters
- **Logs**: Structured logs with severity levels

### Configuration

Telemetry is configured in `~/.claude/settings.json`:

```json
{
  "env": {
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://ingest.integritystudio.ai",
    "OTEL_SERVICE_NAME": "claude-code-hooks"
  }
}
```

### Instrumented Hooks

| Handler | Span Name | Tracked Metrics |
|---------|-----------|-----------------|
| session-start | `hook:session-start` | session.starts |
| user-prompt | `hook:user-prompt` | prompt metrics, context usage |
| pre-tool | `hook:pre-tool` | mcp.invocations, agent.invocations |
| post-tool | `hook:post-tool` | builtin.invocations, file tracking |
| stop | `hook:stop` | build.errors, type check duration |

### Viewing Telemetry

**Local files:**
```bash
~/.claude-history/telemetry/traces-YYYY-MM-DD.jsonl
~/.claude-history/telemetry/logs-YYYY-MM-DD.jsonl
```

**OTEL Dashboard:** https://ingest.integritystudio.ai/

### Context Tracking

The `context-tracker.ts` module tracks session context usage:
- `session.context.size` - Total token estimate
- `session.context.utilization` - Percentage of 200K window
- `session.context.by_type` - Breakdown (system_prompt, system_tools, memory_files, mcp, messages)

---

## Performance Impact

The monitoring library adds minimal overhead:
- Startup: ~5-10ms
- Per hook: ~2-5ms
- Log write: ~1-2ms

**Total overhead: ~10-20ms per hook execution**

For most hooks, this is negligible. Disable for ultra-performance-critical hooks if needed.

---

## Summary

**Minimal setup:**
```bash
source "$(dirname "${BASH_SOURCE[0]}")/lib/performance-monitor.sh"
perf_start "hook-name"
# ... your code ...
perf_end "success"
```

**Benefits:**
- Track hook execution time
- Identify slow hooks
- Debug hook failures
- Monitor performance over time
- No external dependencies
