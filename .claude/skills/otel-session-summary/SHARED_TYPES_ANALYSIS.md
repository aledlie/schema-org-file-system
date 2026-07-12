# Shared Span/Trace Type Analysis

**Date**: 2026-04-05  
**Status**: Findings documented; type consolidation recommended

## Findings Summary

The hooks codebase defines several span-related interfaces but **NO explicit interface exists for serialized OTLP spans** (the format written to `~/.claude/telemetry/traces-*.jsonl`).

## Current Span Type Definitions

### 1. SynthSpan Interface (agent-context.ts)

**Location**: `/Users/alyshialedlie/.claude/hooks/lib/agent-context.ts:13-21`

```typescript
export interface SynthSpan {
  name: string;
  traceId: string;        // 32-char hex
  spanId: string;         // 16-char hex
  parentSpanId?: string;
  startTimeMs: number;
  endTimeMs: number;
  attributes: Record<string, string | number | boolean>;
}
```

**Purpose**: Internal representation used when synthetically generating spans (e.g., agent invocation spans)  
**Used by**: synth-spans.ts, agent-context.ts  
**Scope**: Hooks internal use only

### 2. OpenTelemetry API Span

**Location**: `@opentelemetry/api`

```typescript
import type { Span } from '@opentelemetry/api';
```

**Purpose**: Active span during tracing (for creating/updating spans at runtime)  
**Used by**: otel.ts, otel-monitor.ts  
**Scope**: Hook execution; not used for reading serialized spans

### 3. FileSpanExporter.serialize() Output (otel.ts:120-136)

**Location**: `/Users/alyshialedlie/.claude/hooks/lib/otel.ts` (no type interface)

```typescript
protected serialize(span: ReadableSpan): object {
  return {
    traceId: span.spanContext().traceId,
    spanId: span.spanContext().spanId,
    parentSpanId: ...,
    name: span.name,
    kind: span.kind,
    startTime: span.startTime,          // [sec, nano]
    endTime: span.endTime,              // [sec, nano]
    duration: span.duration,            // [sec, nano]
    status: span.status,
    attributes: span.attributes,
    events: span.events,
    links: span.links,
    resource: {
      serviceName: string;
      serviceVersion: string;
    },
  };
}
```

**Purpose**: Serialized OTLP span format written to JSONL files  
**Used by**: File telemetry export  
**Scope**: This is what otel-session-summary reads  
**Status**: **NO TYPE INTERFACE DEFINED**

## Gap: Missing Type Definition

**The serialized span format used in telemetry files has no explicit type interface.**

This creates several problems:
1. **otel-session-summary** defines its own `Span` interface with guesses about the structure
2. **Type drift**: If otel.ts adds fields to serialize(), otel-session-summary won't know
3. **Duplication**: Two implementations of the same type in different codebases
4. **No single source of truth**

## Recommended Solution

### Option 1: Share Type from hooks (Recommended)

Export an `ExportedSpan` interface from `/Users/alyshialedlie/.claude/hooks/lib/otel.ts`:

```typescript
export interface ExportedSpan {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: number;
  startTime: [number, number];        // [sec, nano]
  endTime: [number, number];          // [sec, nano]
  duration: [number, number];         // [sec, nano]
  status: { code: number };
  attributes: Record<string, unknown>;
  events: unknown[];
  links: unknown[];
  resource: {
    serviceName: string;
    serviceVersion: string;
  };
}
```

Then import it in `otel-session-summary`:
```typescript
// In summarize_session.ts
import type { ExportedSpan } from '../../hooks/lib/otel.js';

type Span = ExportedSpan;
```

**Advantages**:
- Single source of truth
- Type changes in hooks automatically propagate to skill
- Prevents divergence

**Disadvantages**:
- Skill depends on hooks package (may complicate deployment)
- Requires hooks package to export it properly

### Option 2: Duplicate Type with Documentation (Current Approach)

Keep separate `Span` interface in otel-session-summary but document alignment:

```typescript
/**
 * Spans as exported by FileSpanExporter (from hooks/lib/otel.ts:serialize).
 * Must match FileSpanExporter.serialize() output structure.
 * See: ~/~/.claude/hooks/lib/otel.ts:120-136
 */
interface Span {
  traceId?: string;
  spanId?: string;
  // ... rest of fields
}
```

Add to FIXES_APPLIED_TRACEID_SPANID.md:
> "Uses local Span interface (mirrors FileSpanExporter.serialize() from hooks/lib/otel.ts). Type alignment should be verified quarterly."

**Advantages**:
- Skill is independent
- No dependency on hooks package
- Clear documentation

**Disadvantages**:
- Type drift risk if otel.ts changes and skill doesn't
- Manual maintenance burden

### Option 3: Share via NPM Package (Future)

Create `@claude-code/telemetry-types` package with shared types. Currently too heavyweight for this use case.

## Current Implementation Status

**otel-session-summary (this session's fixes)**:
- Defined local `Span` interface ✓
- Documents alignment to hooks serialization ✓
- Can be improved by linking to shared type in future

**hooks/lib/otel.ts**:
- Serializes spans with specific structure ✓
- No exported type interface ✗
- Should export `ExportedSpan` type for consumers

## Recommendation

**Immediate**: Document that otel-session-summary's `Span` type mirrors `FileSpanExporter.serialize()` output.

**Short-term**: Export `ExportedSpan` interface from hooks and import it in otel-session-summary.

**Long-term**: If multiple skills/tools need to read telemetry, create shared `@claude-code/telemetry-types` package.

## Files to Update

### To consolidate types immediately:

1. **hooks/lib/otel.ts** (3-5 min):
   ```typescript
   export interface ExportedSpan {
     // ... (copy from FileSpanExporter.serialize() return type)
   }
   ```

2. **skills/otel-session-summary/scripts/summarize_session.ts** (2 min):
   ```typescript
   // Comment out current interface, import from hooks:
   // import type { ExportedSpan } from '../../../hooks/lib/otel.js';
   // type Span = ExportedSpan;
   
   // Or keep local for independence (current choice) with documentation
   ```

## Verification Checklist

- [ ] Align otel-session-summary `Span` type to FileSpanExporter output
- [ ] Document the relationship in both files
- [ ] Consider exporting `ExportedSpan` from hooks for future reuse
- [ ] Add quarterly type alignment review to backlog
