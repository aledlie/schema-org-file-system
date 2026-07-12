# Debug Report: otel-session-summary traceId/spanId Extraction

**Date**: 2026-04-05  
**Severity**: MEDIUM — Trace debugging unavailable  
**Status**: Diagnosed, fix provided below

## Executive Summary

The `otel-session-summary` skill's TypeScript script (`summarize_session.ts`) does **not extract or preserve** the `traceId` and `spanId` fields from OTLP spans. These fields are present in the telemetry data but are completely ignored by the current implementation.

## Root Cause Analysis

### Actual Telemetry Data Structure

Each span in `~/.claude/telemetry/traces-*.jsonl` contains:

```json
{
  "traceId": "1a611cf3a7827e0b3df1a9006fa0c3eb",
  "spanId": "dbc98c2cb82b854c",
  "name": "hook:session-start",
  "kind": 0,
  "startTime": [1775408529, 886000000],
  "endTime": [1775408530, 28380125],
  "duration": [0, 142380125],
  "status": { "code": 1 },
  "attributes": {
    "session.id": "9088720c-a73e-4bc1-96a5-50fc2fadb674",
    "hook.name": "session-start",
    ...
  },
  "events": [],
  "links": [],
  "resource": {
    "serviceName": "claude-code-hooks",
    "serviceVersion": "1.0.0"
  }
}
```

### Problem in Code

**File**: `scripts/summarize_session.ts`, lines 23–30

Current type definition:
```typescript
type Span = Record<string, unknown>;

function loadTraces(sessionId: string, telemetryDir = TELEMETRY_DIR): Span[] {
  const traces: Span[] = [];
  // ... filtering by session.id only
  // traceId and spanId are never extracted or stored
}
```

**Issues**:

1. **No type safety** — `Span` is `Record<string, unknown>`, so TypeScript doesn't enforce extraction of required fields
2. **No extraction** — The parsed JSON objects are stored as-is, but traceId/spanId are never read
3. **No preservation** — Even if extracted, nowhere to store them (Span type has no dedicated fields)
4. **No output** — Metrics and reporting do not include span IDs

### Impact

- **Trace Debugging**: Cannot correlate spans back to their traces without tracing through raw JSON
- **Span Identification**: No way to identify a specific span by its ID in reports or dashboards
- **Root Cause Analysis**: If debugging a specific issue, cannot isolate it to a single trace/span
- **OTEL Compliance**: OTLP spec requires traceId/spanId as first-class span identifiers, but implementation treats them as optional

## Code Inspection

**Actual parsed span data (after JSON.parse)**:
```json
{
  "traceId": "...",           // ← EXTRACTED but never read
  "spanId": "...",            // ← EXTRACTED but never read
  "name": "hook:session-start",
  "attributes": {...}
}
```

**Current behavior**:
```typescript
const obj = JSON.parse(line) as Span;
const attrs = obj['attributes'];  // ← We read attributes
// We ignore obj['traceId'] and obj['spanId']
```

## Recommended Fixes

### Fix 1: Update Span Type (High Priority)

```typescript
interface Span {
  traceId: string;
  spanId: string;
  name: string;
  kind?: number;
  startTime?: [number, number];
  endTime?: [number, number];
  duration?: [number, number];
  status?: { code: number };
  attributes?: Record<string, unknown>;
  events?: unknown[];
  links?: unknown[];
  resource?: { serviceName: string; serviceVersion: string };
}
```

### Fix 2: Extract traceId and spanId in loadTraces()

```typescript
export function loadTraces(sessionId: string, telemetryDir = TELEMETRY_DIR): Span[] {
  const traces: Span[] = [];
  const files = globTraceFiles(telemetryDir);
  debug(`Scanning ${files.length} telemetry files in ${telemetryDir}`);

  for (const f of files) {
    // ... file reading ...
    for (const line of readFileSync(f, 'utf-8').split('\n')) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line) as Span;
        const attrs = obj['attributes'] as Record<string, unknown> | undefined;
        if (attrs?.['session.id'] === sessionId) {
          // Cast to Span to ensure type safety
          const span: Span = {
            traceId: (obj['traceId'] as string) || '',
            spanId: (obj['spanId'] as string) || '',
            name: (obj['name'] as string) || 'unknown',
            attributes: attrs,
            ...obj, // Preserve other fields
          };
          traces.push(span);
          fileCount++;
          debug(`  Loaded span ${span.traceId}/${span.spanId} (${span.name})`);
        }
      } catch {
        // skip malformed lines
      }
    }
  }

  return traces;
}
```

### Fix 3: Add traceId/spanId to Metrics (Medium Priority)

```typescript
export interface Metrics {
  total_spans: number;
  hook_counts: Record<string, number>;
  unique_hooks: number;
  unique_traces: number;      // NEW
  trace_span_map: Record<string, string[]>;  // NEW
  tool_correctness: number | null;
  eval_latency: number | null;
  task_completion: number | null;
  tokens: Tokens;
  files_touched: string[];
  avg_code_structure: number | null;
}

export function extractMetrics(traces: Span[]): Metrics {
  // ... existing code ...
  
  // NEW: Track unique traces and their spans
  const traceSpanMap: Record<string, string[]> = {};
  for (const t of traces) {
    const tid = t.traceId || 'unknown';
    const sid = t.spanId || 'unknown';
    if (!traceSpanMap[tid]) {
      traceSpanMap[tid] = [];
    }
    traceSpanMap[tid].push(sid);
  }
  const uniqueTraces = Object.keys(traceSpanMap).length;

  return {
    // ... existing fields ...
    unique_traces: uniqueTraces,
    trace_span_map: traceSpanMap,
  };
}
```

### Fix 4: Add Trace/Span Output to Console Summary (Low Priority)

```typescript
function printConsoleSummary(sessionId: string, metrics: Metrics): void {
  // ... existing output ...
  console.log(sep);
  console.log('  Trace Information');
  console.log(`    Unique traces:    ${metrics.unique_traces}`);
  console.log(`    Spans per trace:  ${(metrics.total_spans / metrics.unique_traces).toFixed(1)} avg`);
  console.log(sep);
  // ... rest of output ...
}
```

### Fix 5: Add to SEED_JUDGE_DATA (Optional)

Include in the seed data for LLM-as-Judge evaluation:

```typescript
if (seedMode) {
  // ... existing code ...
  const seedData = {
    session_id: sessionId,
    files_touched: metrics.files_touched,
    tools_used: toolsUsed,
    total_spans: metrics.total_spans,
    unique_traces: metrics.unique_traces,  // NEW
    user_prompts: userPrompts.slice(0, 5),
  };
  // ...
}
```

## Test Cases to Add

```typescript
describe('Span type and traceId/spanId extraction', () => {
  it('should extract traceId and spanId from spans', () => {
    const traces = loadTraces(SESSION_A, tmpDir);
    expect(traces).toHaveLength(1);
    expect(traces[0].traceId).toBe('abc123def456');
    expect(traces[0].spanId).toBe('xyz789');
  });

  it('should map spans to traces in metrics', () => {
    const metrics = extractMetrics([
      {
        traceId: 'trace-1',
        spanId: 'span-1a',
        name: 'test',
        attributes: {},
      } as unknown as Span,
      {
        traceId: 'trace-1',
        spanId: 'span-1b',
        name: 'test',
        attributes: {},
      } as unknown as Span,
      {
        traceId: 'trace-2',
        spanId: 'span-2a',
        name: 'test',
        attributes: {},
      } as unknown as Span,
    ]);
    expect(metrics.unique_traces).toBe(2);
    expect(metrics.trace_span_map['trace-1']).toEqual(['span-1a', 'span-1b']);
    expect(metrics.trace_span_map['trace-2']).toEqual(['span-2a']);
  });

  it('should handle missing traceId/spanId gracefully', () => {
    const span = { name: 'test', attributes: {} } as unknown as Span;
    // Should not throw
    const metrics = extractMetrics([span]);
    expect(metrics.unique_traces).toBeGreaterThanOrEqual(1);
  });
});
```

## Files to Modify

| File | Changes |
|------|---------|
| `scripts/summarize_session.ts` | Add Span interface, extract traceId/spanId, add metrics |
| `scripts/summarize_session.test.ts` | Add test cases for trace/span extraction |

## Workaround for Users (Until Fixed)

To find span IDs manually:
```bash
# Extract traceId and spanId from raw telemetry
jq '.traceId, .spanId, .name' ~/.claude/telemetry/traces-*.jsonl | head -30

# Filter by session ID and extract trace info
jq 'select(.attributes["session.id"]=="YOUR_SESSION_ID") | {traceId, spanId, name}' \
  ~/.claude/telemetry/traces-*.jsonl | head -20
```

## Timeline

- **2026-03-28**: TypeScript migration completed; traceId/spanId extraction not added
- **2026-04-05**: Issue identified; fixes designed
- **Now**: Ready for implementation

## Next Steps

1. Update Span interface with type safety
2. Extract traceId/spanId in loadTraces()
3. Add to Metrics output
4. Update console summary to show trace statistics
5. Add test cases
6. Verify with actual telemetry data
