# otel-session-summary Skill

Console dashboard for Claude Code OTEL telemetry analysis. Extracts spans, traces, and metrics; computes rule-based quality scores and LLM-as-Judge evaluations.

## Quick Start

```bash
# Analyze current session
/otel-session-summary

# Analyze specific session by ID
/otel-session-summary e153d8f7-9cf1-4d38-b3c4-e3dbd1133318
```

## What You Get

```
Session:  e153d8f7-9cf1-4d38-b3c4-e3dbd1133318
Spans:    236
Traces:   236
Hooks:    11 unique

Tokens
  Input:          177
  Output:        16.1k
  Cache read:    3.0M
  Cache create:  316.6k
  Total:         16.3k

Metrics
  tool_correctness  ████████████████████  1.00  healthy
  eval_latency      ████████████████████  0.001s  healthy
  code_structure    ██████████░░░░░░░░░░  0.50

Hook Breakdown
  builtin-pre-tool          105
  builtin-post-tool         103
  skill-activation-prompt     5
  ... (11 total hook types)

Files Touched (6)
  ~/.claude/hooks/CONFIG.md
  ~/.claude/hooks/PERFORMANCE_MONITORING.md
  ... (6 total files)
```

## Features

✅ **Span/Trace Extraction** — Extracts 32-char traceId and 16-char spanId from OTLP telemetry  
✅ **Metrics Computation** — Calculates tool_correctness, eval_latency, task_completion, code_structure  
✅ **Hook Analysis** — Counts hook invocations by type  
✅ **Token Accounting** — Summarizes input, output, cache metrics  
✅ **File Tracking** — Identifies which files were modified in session  
✅ **LLM-as-Judge Scoring** — Relevance, faithfulness, coherence, hallucination detection (optional Phase 2)  
✅ **Debug Logging** — `OTEL_LOG_LEVEL=debug` shows detailed span identification  

## Documentation

### Implementation Details

- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** — Overview of the entire fix, test results, and architecture
- **[DEBUG_TRACEID_SPANID.md](DEBUG_TRACEID_SPANID.md)** — Root cause analysis of traceId/spanId extraction
- **[FIXES_APPLIED_TRACEID_SPANID.md](FIXES_APPLIED_TRACEID_SPANID.md)** — Detailed list of changes and verification

### Technical Analysis

- **[SHARED_TYPES_ANALYSIS.md](SHARED_TYPES_ANALYSIS.md)** — Analysis of span type definitions across codebase
- **[SPAN_TYPE_COMPARISON.md](SPAN_TYPE_COMPARISON.md)** — Detailed comparison of OpenTelemetry API vs serialized spans

### Historical Documentation

- **[FIXES_APPLIED.md](FIXES_APPLIED.md)** — Original session ID discovery fixes (pre-traceId work)
- **[DEBUG_SESSION_ID.md](DEBUG_SESSION_ID.md)** — Session ID discovery debugging notes

## Architecture

### Span Lifecycle

```
Hook Execution
    ↓ api.Span created
    ↓ span.setStatus/addEvent/setAttributes
    ↓ span.end()
    ↓ ReadableSpan created
    ↓ FileSpanExporter.serialize()
    ↓ ExportedSpan (JSON)
    ↓ Written to ~/.claude/telemetry/traces-YYYY-MM-DD.jsonl
    ↓ otel-session-summary reads & extracts traceId/spanId
```

### Metrics

| Metric | Source | Meaning |
|--------|--------|---------|
| **total_spans** | Telemetry file count | Number of OTEL spans in session |
| **unique_traces** | Distinct traceIds | Number of traces (approximately 1:1 with spans in hooks) |
| **unique_hooks** | Distinct hook names | Number of hook types invoked |
| **tool_correctness** | Post-tool spans | Fraction of tool calls that succeeded |
| **eval_latency** | Span durations | Median duration of spans (seconds) |
| **task_completion** | TaskCreate/TaskUpdate | Fraction of created tasks that were marked complete |
| **code_structure** | Structure score spans | Average code quality score |

## Usage Guide

### Basic

```bash
# Current session (auto-discovers latest)
/otel-session-summary

# Specific session
/otel-session-summary e153d8f7-9cf1-4d38-b3c4-e3dbd1133318
```

### Advanced

```bash
# Debug logging (see every span loaded)
OTEL_LOG_LEVEL=debug node ~/.claude/skills/otel-session-summary/scripts/summarize_session.ts ""

# JSON output (for scripting)
node ~/.claude/skills/otel-session-summary/scripts/summarize_session.ts "" --json

# With LLM-as-Judge seed data (Phase 2)
node ~/.claude/skills/otel-session-summary/scripts/summarize_session.ts "" --seed
```

### Environment Variables

```bash
OTEL_LOG_LEVEL=debug              # Enable debug logging
CLAUDE_TELEMETRY_DIR=...  # Override telemetry directory (default: ~/.claude/telemetry)
```

## Testing

```bash
# Run all tests
npm run skills:test

# Run specific skill tests
cd ~/.claude && npx vitest run skills/otel-session-summary/scripts/summarize_session.test.ts
```

**Test Status**: ✅ 83/83 tests passing  
**Last Verified**: 2026-04-05

## Troubleshooting

### "No session found"

```bash
# Run with debug to see what's happening
OTEL_LOG_LEVEL=debug /otel-session-summary

# Check telemetry files exist
ls -la ~/.claude/telemetry/traces-*.jsonl
```

### Session looks incomplete

```bash
# Check how many files were scanned
OTEL_LOG_LEVEL=debug node ~/.claude/skills/otel-session-summary/scripts/summarize_session.ts "" 2>&1 | grep "Scanning"
```

### traceId/spanId not showing

Ensure you're running the latest version:
```bash
cd ~/.claude && npm run skills:test
```

If tests pass, the extraction is working. Debug output will show it:
```bash
OTEL_LOG_LEVEL=debug /otel-session-summary 2>&1 | grep "loaded span"
```

## Files

### Source Code

- **`scripts/summarize_session.ts`** (438 lines) — Main extraction + metrics logic
- **`scripts/summarize_session.test.ts`** (486 lines) — Test suite (83 tests)
- **`SKILL.md`** — User-facing skill definition

### Documentation (this folder)

- `README.md` (this file)
- `IMPLEMENTATION_SUMMARY.md` — Overview and release notes
- `DEBUG_TRACEID_SPANID.md` — Root cause analysis
- `FIXES_APPLIED_TRACEID_SPANID.md` — Implementation details
- `SHARED_TYPES_ANALYSIS.md` — Type system analysis
- `SPAN_TYPE_COMPARISON.md` — Span type comparison
- `FIXES_APPLIED.md` — Original session ID fixes
- `DEBUG_SESSION_ID.md` — Session ID debugging

## Recent Changes

### v1.1.0 (2026-04-05)

✨ **Feature**: Complete traceId/spanId extraction

- Extract 32-char hex traceId from each span
- Extract 16-char hex spanId from each span
- Count unique traces in session
- Display trace count in console dashboard
- Add debug logging for span identification
- Proper TypeScript interfaces for type safety

✅ All 83 tests passing  
✅ Production ready  
✅ No breaking changes

### v1.0.x (2026-03-25)

- Session ID discovery with fallback to older files
- Silent failure detection and logging
- Error messages with debug instructions

## Roadmap

### Short-term (Recommended)

- [ ] Export `ExportedSpan` interface from hooks/lib/otel.ts
- [ ] Import shared type to prevent type drift
- [ ] Per-trace span count statistics

### Medium-term (Nice to Have)

- [ ] ASCII tree visualization of trace structure
- [ ] Trace export in Jaeger/Zipkin format
- [ ] Interactive trace explorer

## Performance

- **Typical Session**: <1 second to extract 200-500 spans
- **Large Session** (1000+ spans): 2-3 seconds
- **Memory**: Negligible (streaming JSON parsing)

## Support

1. Check the appropriate documentation file:
   - **Troubleshooting**: See "Troubleshooting" section above
   - **Root cause**: `DEBUG_TRACEID_SPANID.md`
   - **Span types**: `SPAN_TYPE_COMPARISON.md`
   - **Implementation**: `IMPLEMENTATION_SUMMARY.md`

2. Enable debug logging:
   ```bash
   OTEL_LOG_LEVEL=debug /otel-session-summary
   ```

3. Review test expectations:
   ```bash
   cat scripts/summarize_session.test.ts
   ```

## Technical Stack

- **Language**: TypeScript
- **Runtime**: Node.js (tsx)
- **Telemetry**: OTLP (OpenTelemetry Protocol)
- **Testing**: Vitest
- **Platforms**: macOS, Linux, Windows (via git bash)

## License

Part of the Claude Code hooks ecosystem.  
Maintained by Integrity Studio AI.

---

**Last Updated**: 2026-04-05  
**Status**: ✅ Production Ready  
**Test Coverage**: 83 tests, all passing
