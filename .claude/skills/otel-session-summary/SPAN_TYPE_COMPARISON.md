# Span Type Comparison: API vs Serialized

**Date**: 2026-04-05  
**Context**: Understanding the relationship between OpenTelemetry API types and serialized telemetry

## Executive Summary

Four distinct span type representations exist in the Claude Code codebase:

| Type | Module | Purpose | When Used |
|------|--------|---------|-----------|
| **api.Span** | @opentelemetry/api | Active span (mutable) | During hook execution |
| **ReadableSpan** | @opentelemetry/sdk-trace-node | Completed span (immutable) | After span ends, before export |
| **ExportedSpan** | hooks/lib/otel.ts | JSON-serialized span | Written to JSONL files |
| **SynthSpan** | hooks/lib/agent-context.ts | Programmatic span | Generate synthetic spans |

---

## 1. OpenTelemetry API Span (`api.Span`)

**Location**: `@opentelemetry/api` (re-exported from hooks/lib/otel.ts:764)

**Purpose**: Mutable span object for recording events during execution

**How It's Used**:
```typescript
// From otel.ts:388-407
export function withSpan<T>(
  name: string,
  attributes: api.Attributes = {},
  fn: (span: api.Span) => T | Promise<T>
): Promise<T> {
  const tracer = getTracer();
  return tracer.startActiveSpan(name, { attributes }, async (span) => {
    try {
      const result = await fn(span);
      span.setStatus({ code: api.SpanStatusCode.OK });
      return result;
    } catch (error) {
      span.setStatus({
        code: api.SpanStatusCode.ERROR,
        message: error instanceof Error ? error.message : String(error),
      });
      span.recordException(error);
      throw error;
    } finally {
      span.end();  // Converts to ReadableSpan
    }
  });
}
```

**Key Interface Members**:
```typescript
interface Span {
  // Read-only
  spanContext(): SpanContext;           // Contains traceId, spanId
  
  // Mutate span
  setAttributes(attributes: Attributes): Span;
  setStatus(status: SpanStatus): Span;
  addEvent(name: string, attributes?: Attributes): Span;
  recordException(error: Exception, time?: HrTime): Span;
  
  // Lifecycle
  end(endTime?: HrTime): void;          // Signals span completion
  isRecording(): boolean;
}

interface SpanContext {
  traceId: string;        // 32-char hex
  spanId: string;         // 16-char hex
  traceFlags: TraceFlags;
  traceState?: TraceState;
  isRemote: boolean;
}
```

**Lifecycle**: Created → Mutable (during execution) → `span.end()` → Becomes ReadableSpan → Exported

---

## 2. ReadableSpan (`@opentelemetry/sdk-trace-node`)

**Location**: `@opentelemetry/sdk-trace-node` (used in hooks/lib/otel.ts:23)

**Purpose**: Immutable representation of a completed span, ready for export

**How It's Created**:
- Automatically created when `api.Span.end()` is called
- Available in span processor callbacks and exporters

**Key Interface Members**:
```typescript
interface ReadableSpan {
  // Context
  spanContext(): SpanContext;           // Same as api.Span
  parentSpanId?: string;
  
  // Identification
  name: string;
  kind: SpanKind;                       // INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER
  
  // Timing (both in [seconds, nanoseconds] format)
  readonly startTime: HrTime;
  readonly endTime: HrTime;
  readonly duration: HrTime;
  
  // Status & Data
  readonly status: SpanStatus;
  readonly attributes: ReadonlyAttributes;
  readonly links: ReadonlyArray<Link>;
  readonly events: ReadonlyArray<TimedEvent>;
  readonly droppedAttributesCount: number;
  readonly droppedEventsCount: number;
  readonly droppedLinksCount: number;
  
  // Resource
  readonly resource: Resource;
}

interface SpanStatus {
  code: SpanStatusCode;    // UNSET, OK, ERROR
  message?: string;
}
```

**Conversion Point**: `FileSpanExporter.serialize(span: ReadableSpan)` → ExportedSpan

---

## 3. ExportedSpan (Serialized JSON)

**Location**: Returned by `hooks/lib/otel.ts:FileSpanExporter.serialize()` (lines 120-136)

**Purpose**: JSON-serializable representation written to telemetry files

**Structure**:
```typescript
interface ExportedSpan {
  // OTLP-standard fields (root level)
  traceId: string;                    // 32-char hex
  spanId: string;                     // 16-char hex
  parentSpanId?: string;
  
  // Span metadata
  name: string;
  kind: number;                       // SpanKind (0-4)
  
  // Timing (converted to [seconds, nanoseconds] tuples)
  startTime: [number, number];
  endTime: [number, number];
  duration: [number, number];
  
  // Status
  status: {
    code: number;                     // 0=UNSET, 1=OK, 2=ERROR
    message?: string;
  };
  
  // Data
  attributes: Record<string, unknown>;
  events: Array<{                     // Includes event name, time, attributes
    name: string;
    time: [number, number];
    attributes?: Record<string, unknown>;
  }>;
  links: Array<{                      // References to other spans
    spanContext?: {
      traceId: string;
      spanId: string;
    };
    attributes?: Record<string, unknown>;
  }>;
  
  // Resource (where the span came from)
  resource: {
    serviceName: string;
    serviceVersion: string;
  };
}
```

**How It's Written**:
```typescript
// From otel.ts:120-136
protected serialize(span: ReadableSpan): object {
  return {
    traceId: span.spanContext().traceId,
    spanId: span.spanContext().spanId,
    parentSpanId: (span as ReadableSpan & { parentSpanId?: string }).parentSpanId,
    name: span.name,
    kind: span.kind,
    startTime: span.startTime,              // Already [sec, nano]
    endTime: span.endTime,
    duration: span.duration,
    status: span.status,
    attributes: span.attributes,
    events: span.events,
    links: span.links,
    resource: {
      serviceName: span.resource.attributes[ATTR_SERVICE_NAME],
      serviceVersion: span.resource.attributes[ATTR_SERVICE_VERSION],
    },
  };
}
```

**Where It's Stored**: `~/.claude/telemetry/traces-YYYY-MM-DD.jsonl` (one JSON object per line)

---

## 4. SynthSpan (Programmatically Generated)

**Location**: `hooks/lib/agent-context.ts:13-21`

**Purpose**: Generate spans for operations not instrumented with api.Span

**Structure**:
```typescript
export interface SynthSpan {
  name: string;
  traceId: string;        // 32-char hex
  spanId: string;         // 16-char hex
  parentSpanId?: string;
  startTimeMs: number;    // milliseconds (NOT [sec, nano])
  endTimeMs: number;
  attributes: Record<string, string | number | boolean>;
}
```

**How It's Used**:
```typescript
// From synth-spans.ts:29-71
function toReadableSpan(s: SynthSpan): unknown {
  const startTime = msToHrTime(s.startTimeMs);  // Convert to [sec, nano]
  const endTime = msToHrTime(s.endTimeMs);
  const duration = computeDuration(...);
  
  const spanCtx: SpanContext = {
    traceId: s.traceId,
    spanId: s.spanId,
    traceFlags: TraceFlags.SAMPLED,
    isRemote: false,
  };
  
  return {
    name: s.name,
    spanContext: () => spanCtx,
    parentSpanId: s.parentSpanId,
    startTime,
    endTime,
    duration,
    // ... other ReadableSpan fields
  };
}
```

**Conversion Path**: SynthSpan → duck-typed ReadableSpan → serialized via FileSpanExporter

---

## Conversion Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ During Hook Execution (MUTABLE)                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  api.Span (from tracer.startActiveSpan)                        │
│    ├─ setStatus(...)                                           │
│    ├─ addEvent(...)                                            │
│    ├─ setAttributes(...)                                       │
│    └─ end() ────────────────────────┐                          │
│                                      │                          │
└──────────────────────────────────────┼──────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ After Span Ends (IMMUTABLE)                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ReadableSpan (spans flow to SpanProcessor)                    │
│    ├─ spanContext() → { traceId, spanId, ... }                │
│    ├─ name, kind, status                                       │
│    ├─ startTime, endTime, duration [sec, nano]                │
│    ├─ attributes, events, links, resource                     │
│    └─ (immutable, read-only)                                   │
│                                                                  │
│  ┌──────────────────────┐                                       │
│  │ FileSpanExporter     │                                       │
│  │ .serialize()         │────────────────────┐                  │
│  └──────────────────────┘                    │                  │
│                                              ▼                  │
└──────────────────────────────────────────────┼──────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ Exported (JSONL, consumable by tools)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ExportedSpan (JSON object in traces-*.jsonl)                  │
│    ├─ traceId, spanId, parentSpanId (root level)              │
│    ├─ name, kind                                               │
│    ├─ startTime, endTime, duration ([sec, nano])              │
│    ├─ status, attributes, events, links                       │
│    ├─ resource { serviceName, serviceVersion }                │
│    └─ (consumed by otel-session-summary, analysis tools)      │
│                                                                  │
│  Written to: ~/.claude/telemetry/traces-YYYY-MM-DD.jsonl      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

PARALLEL PATH (Synthetic Spans)
─────────────────────────────────

  SynthSpan (from agent-context.ts)
    ├─ name, traceId, spanId, startTimeMs, endTimeMs
    └─ attributes
           │
           ▼
  toReadableSpan() [synth-spans.ts]
    └─ Converts to duck-typed ReadableSpan
         │
         ▼
    FileSpanExporter.serialize()
         │
         ▼
    ExportedSpan (same JSONL output)
```

---

## Key Differences

| Aspect | api.Span | ReadableSpan | ExportedSpan | SynthSpan |
|--------|----------|--------------|--------------|-----------|
| **Mutability** | Mutable | Immutable | Immutable | Template |
| **Timing Format** | HrTime [sec, nano] | HrTime [sec, nano] | [sec, nano] | Milliseconds |
| **Lifecycle** | Active | After end() | In files | Pre-created |
| **Created By** | tracer.startActiveSpan() | Span processor | Serializer | Programmer |
| **Used For** | Recording events | Processing | Analysis | Synthetic spans |
| **Interface** | Methods (setStatus, etc.) | Properties (read-only) | JSON object | Interface |
| **Location** | Runtime | Processor | JSONL files | In-memory |

---

## Implications for otel-session-summary

**The skill reads ExportedSpan** from JSONL files, NOT api.Span or ReadableSpan directly.

```typescript
// otel-session-summary/scripts/summarize_session.ts

// Define local interface matching ExportedSpan structure:
interface Span {
  traceId?: string;       // From ReadableSpan.spanContext().traceId
  spanId?: string;        // From ReadableSpan.spanContext().spanId
  parentSpanId?: string;
  name?: string;
  kind?: number;
  startTime?: [number, number];    // Already in [sec, nano]
  endTime?: [number, number];
  duration?: [number, number];
  status?: { code: number };
  attributes?: Record<string, unknown>;
  events?: unknown[];
  links?: unknown[];
  resource?: { serviceName: string; serviceVersion: string };
}

// Read JSONL and parse as ExportedSpan:
const obj = JSON.parse(line) as Span;
```

**Why this works**:
- FileSpanExporter.serialize() outputs all fields at the root level
- ExportedSpan JSON structure is directly readable
- No need to call methods (like api.Span.spanContext())
- All timing already converted to [sec, nano] tuples

---

## Future Improvement

Export `ExportedSpan` interface from hooks/lib/otel.ts:

```typescript
// hooks/lib/otel.ts
export interface ExportedSpan {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: number;
  startTime: [number, number];
  endTime: [number, number];
  duration: [number, number];
  status: { code: number; message?: string };
  attributes: Record<string, unknown>;
  events: unknown[];
  links: unknown[];
  resource: { serviceName: string; serviceVersion: string };
}
```

Then import in skill:
```typescript
// skills/otel-session-summary/scripts/summarize_session.ts
import type { ExportedSpan } from '../../../hooks/lib/otel.js';
type Span = ExportedSpan;
```

This creates a single source of truth for the serialized span format.
