# Hooks Architecture

**Last updated**: 2026-04-19
**Status**: current-state reference

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Distributed Trace Context Propagation](#<redacted-token>)
4. [Component Reference](#component-reference)
5. [Performance Characteristics](#performance-characteristics)
6. [Connection to observability-toolkit MCP Server](#<redacted-token>)
7. [Design Principles](#design-principles)
8. [Debugging](#debugging)
9. [Related Files](#related-files)
10. [References](#references)

---

## Overview

The hooks system is Claude Code's instrumentation layer. It runs on every tool invocation (MCP, Builtin, Plugin, Agent) and provides:

- **OpenTelemetry integration** — distributed tracing, metrics, structured logs
- **Tool output analysis** — error classification, size tracking, correctness signals
- **Agent span reparenting** — synthetic GenAI spans for multi-step agent work
- **Quality metrics** — coherence heuristics, tool correctness, token usage, LLM-judge evaluations
- **File I/O batching** — non-blocking appends via WriteBuffer
- **Caching & circuit breakers** — bounded memory and cascade-failure protection

The runtime is **long-lived** (the hook-runner daemon persists across sessions) and **high-frequency** (100s–1000s of invocations per session). Every component is designed around that profile: pre-compiled work at module load, O(1) fast paths, bounded caches, and fire-and-forget I/O.

---

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Claude Code Hook Event (MCP, Plugin, Agent, Builtin)           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                ┌────────▼────────┐
                │ post-tool.ts    │ (unified handler router)
                └────────┬────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼────┐   ┌──────▼──────┐  ┌─────▼────┐
   │MCP tool │   │Plugin/Agent  │  │Builtin   │
   │handler  │   │handler       │  │handler   │
   └────┬────┘   └──────┬──────┘  └─────┬────┘
        │                │              │
        └────────────────┼──────────────┘
                         │
        ┌────────────────▼────────────────┐
        │ Shared Instrumentation          │
        │ - error detection (regex)       │
        │ - output analysis               │
        │ - agent span building           │
        │ - quality metrics               │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┼────────────────────────┐
        │                │                        │
   ┌────▼────┐   ┌──────▼──────┐   ┌────────────▼──┐
   │OTel      │   │WriteBuffer   │   │Agent Context  │
   │metrics   │   │(log batching)│   │(span state)   │
   └─────────┘   └──────────────┘   └───────────────┘
```

### End-to-End Pipeline

The hooks are one half of a producer-consumer pipeline. They write telemetry; the `observability-toolkit` MCP server reads it back and surfaces it to Claude. The MCP server is itself instrumented by the hooks, creating a self-observation loop.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Claude Code session                                                       │
│                                                                           │
│   tool call ─► hook-runner process (one per invocation)                   │
│                                                                           │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │ HookMonitor.run(eventName)               [lib/otel-monitor.ts]  │    │
│   │   ├─ loadSessionContext(sessionId)       [lib/trace-context.ts] │    │
│   │   │    ← ~/.claude/telemetry/trace-ctx/{sessionId}.session-    │    │
│   │   │        trace.json   (TTL 24h)                              │    │
│   │   ├─ setSpanContext(..., isRemote:true) → remote parent         │    │
│   │   └─ withSpan(name, opts, fn, parentContext)    [lib/otel.ts]   │    │
│   │         ├─ post-tool.ts route dispatch                          │    │
│   │         │    MCP → Plugin → Agent → McpResource                 │    │
│   │         │    → Write → Edit/MultiEdit → Bash → builtin          │    │
│   │         ├─ output-analyzer  (pre-compiled regex; head/tail      │    │
│   │         │                    sample for >50KB outputs)          │    │
│   │         ├─ agent-context    (pendingAgents + LIFO stack)        │    │
│   │         ├─ quality-signals  (T1 rule-based, T2 LLM judge)       │    │
│   │         └─ span export ─────────────┐                           │    │
│   └────────────────────────────────────── │ ──────────────────────────┘    │
│                                           │                                │
│   session-start hook (once per session) ──┤                                │
│     saveSessionContext(sessionId, root) ──┼──► trace-ctx/*.session-        │
│                                           │       trace.json               │
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
                                            │
       ┌────────────────────────────────────┼────────────────────────────────┐
       │                                    │                                │
       ▼                                    ▼                                ▼
  WriteBuffer                      FileSpanExporter                OTLPTraceExporter
  (p-queue,                        (batched append                 (when configured)
   8KB/200ms flush)                 of ExportedSpan JSON)
       │                                    │                                │
       ▼                                    ▼                                ▼
  ~/.claude-history/telemetry/              ~/.claude-history/        ingest.integritystudio.ai
    evaluations-YYYY-MM-DD.jsonl             telemetry/                    │
                                             traces-YYYY-MM-DD.jsonl       ▼
                                                                    Cloudflare R2 + D1
       │                                    │                                │
       │  [ Contract surface: on-disk JSONL + R2/D1 schema ]                 │
       │  ExportedSpan (writer) ─ must stay in sync with ──►                 │
       │  FlatSpan (local reader)  +  traceSpanSchema (Zod)                  │
       │                                                                     │
       ▼                                    ▼                                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ observability-toolkit MCP server                                          │
│                                                                           │
│   src/backends/local-jsonl.ts                                             │
│     ├─ streamJsonl(traces-*.jsonl)         → FlatSpan                    │
│     └─ streamJsonl(evaluations-*.jsonl)    → evaluationResultSchema       │
│                                                                           │
│   src/backends/cloud.ts                                                   │
│     └─ GET api.integritystudio.ai/v1/traces  → traceSpanSchema            │
│                                                                           │
│   Default read path: ~/.claude-history/telemetry/  (aligned w/ writer,    │
│                      override via TELEMETRY_DIR)                          │
│                                                                           │
│   56 MCP tools: obs_query_traces, obs_query_evaluations, ...              │
│     └─ Claude invokes these via MCP                                       │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                │  tool call ─► hook fires ─► post-tool.ts ─┐
                                │                                            │
                                └────────────────────────────────────────────┘
                                    (self-instrumentation loop; MCP server
                                     spans land in the same traces-*.jsonl)
```

**Contract surface**: the two systems share no runtime imports. Coupling lives in the on-disk JSONL shape and the R2/D1 schema. Three type definitions must be kept in sync manually — `ExportedSpan` (`hooks/lib/otel.ts`), `FlatSpan` (`src/backends/local-jsonl.ts`), and `traceSpanSchema` (`src/backends/backend-schemas.ts`). See [Connection to observability-toolkit MCP Server](#<redacted-token>) for detail.

### Handler Routing

`post-tool.ts::handlePostTool()` dispatches in this order:

1. **MCP** → `handleMcpPostTool` (identified by `mcp__*` tool name)
2. **Plugin** → plugin-specific handler
3. **Agent** → `handleAgentPostTool` (for `Agent` / `Task` tool calls)
4. **McpResource** → resource-read handler
5. **Write** → `tsc-check` + `py-check` + `ts-file-create` + `code-structure`
6. **Edit / MultiEdit** → `tsc-check` + `py-check` + `code-structure`
7. **Bash** → `post-commit-review` (git state + error capture)
8. **Builtin fallback** → generic tool span

Each route emits an OTel span, runs its handler-specific analysis, and records metrics. Failures are caught and logged; they never propagate up and crash the hook.

---

## Distributed Trace Context Propagation

### Problem

Each Claude Code hook invocation runs in a separate Node.js module context (the hook-runner daemon re-imports modules per invocation type). Without cross-process propagation, every hook span would be a standalone root span with its own `traceId` — a typical session would emit 100–1000 single-span "traces" with no parent-child relationships. Technically valid OTel, but not W3C-compliant distributed tracing.

### Design

The session-start span is the **trace root**. Its `traceId` and `spanId` are persisted to disk synchronously, before the span ends. Every subsequent hook reads the persisted context, reconstructs a **remote parent** via `api.trace.setSpanContext(..., { isRemote: true })`, and passes it as the 4th argument to `tracer.startActiveSpan(name, options, context, fn)`. All hook spans in the session then share one `traceId` with proper parent-child links.

### Span Layout

```
traceId=T  spanId=S0  name="hook:session-start"    parentSpanId=none   ← session root
traceId=T  spanId=S1  name="hook:builtin-pre-tool"  parentSpanId=S0    ← child
traceId=T  spanId=S2  name="hook:builtin-post-tool" parentSpanId=S0    ← child
traceId=T  spanId=S3  name="tsc-check"              parentSpanId=S2    ← grandchild
```

Grandchildren (e.g. `tsc-check`) inherit their parent automatically because `startActiveSpan` sets the hook span as the active context for the callback scope.

### Key OTel APIs

- `api.trace.setSpanContext(ROOT_CONTEXT, { traceId, spanId, traceFlags: SAMPLED, isRemote: true })` — builds an injectable remote parent context
- `tracer.startActiveSpan(name, options, context, fn)` — creates a child of the injected context and activates it for the callback
- `TraceFlags.SAMPLED = 0x01` — marks the remote parent as sampled so children are exported

### Context Storage

```
~/.claude/telemetry/trace-ctx/
  {sessionId}.session-trace.json   ← W3C session root  (TTL: 24h)
  {sessionId}.json                 ← prompt span link  (TTL: 10min)
```

Written synchronously inside the session-start span callback, so it is available to all subsequent hook processes with no race condition.

### Fallback

If no session context is found (session-start not yet run, TTL expired, write failure, or corrupted JSON), `loadSessionContext()` returns `null`, `parentContext` remains `undefined`, and the span starts as a root. All logic is fail-silent.

### Files Involved

| File | Role |
|------|------|
| `hooks/lib/trace-context.ts` | `saveSessionContext()`, `loadSessionContext()` |
| `hooks/lib/otel.ts` | `withSpan(name, opts, fn, parentContext?)` 4-arg form |
| `hooks/lib/otel-monitor.ts` | Loads session context, builds remote parent, passes to `withSpan` |
| `hooks/handlers/session-start.ts` | Saves session context inside the hook callback |

---

## Component Reference

### Post-Tool Handler (`handlers/post-tool.ts`)

Main router. Responsibilities:

- **Route dispatch** — MCP → Plugin → Agent → McpResource → Write → Edit/MultiEdit → Bash → builtin
- **Output resolution** — `resolveOutputText()` materializes `tool_response` into a string. For object responses it calls `roughEstimateSize()` first and short-circuits with a sentinel (`[response too large to serialize]`) when the estimate exceeds `THRESHOLDS.MAX_JSON_SIZE_BYTES` (10MB), avoiding full `JSON.stringify` on multi-MB payloads.
- **Size estimation** — `roughEstimateSize()` samples the first 10 top-level entries, extrapolates `(sampleBytes / sampleCount) × totalEntries`, and short-circuits when the projection exceeds the threshold. Full iteration runs only when the projection is safe.
- **Agent output scanning** — `handleAgentPostTool()` scans agent output against error regexes. For outputs larger than `THRESHOLDS.LARGE_OUTPUT_BYTES` (50KB), matches run against `slice(0, 5000) + slice(-5000)` only (error markers cluster at head/tail).
- **Circuit breaker** — `CircuitBreaker` (lib/circuit-breaker.ts) halts repeated failures after `MAX_FAILURES` hits, resets after `RESET_MS`.

### Output Analysis (`lib/output-analyzer.ts`)

All error-detection patterns are **pre-compiled at module load** (16+ regexes):

```typescript
const NETWORK_ERROR_PATTERN = /econnrefused|etimedout|enotfound|econnreset|enetunreach|socket hang up|connection refused|connection.?failed|connection.?error/i;
const RATE_LIMIT_PATTERN    = /\b429\b|rate.?limit|too many requests|throttl/i;
const AUTH_ERROR_PATTERN    = /\b401\b|\b403\b|unauthorized|invalid.?credentials|auth.*fail/i;
// ... 13 more
```

`classifyError()` walks the patterns and returns `{ errorType, errorCategory }` where `errorCategory ∈ { network | auth | rate_limit | timeout | validation | not_found | permission | unknown }`.

Tool-specific paths (Read, Write, Edit, Bash, Glob, Grep, WebFetch, TaskOutput) add bespoke parsing — notably `countTscErrors` / `countPyErrors` for type-check output.

### Agent Context (`lib/agent-context.ts`)

Tracks pending agent invocations and accumulates their `execute_tool` child spans.

- **`pendingAgents: Map<string, PendingAgent>`** — keyed `sessionId:agentName:invokeSpanId`; O(1) lookup
- **`activeAgentStack: PendingAgent[]`** — LIFO; `popPendingAgent()` checks the top first (O(1) fast path), falls back to linear search for out-of-order pops (nested agents, error recovery)
- **`seenAgents: Map<sessionId, agentName>`** — deduplicates `create_agent` spans per session
- **Eviction** — TTL-based pruning (30 min stale threshold); `MAX_TOOL_SPANS_PER_AGENT` cap (500)

### Constants & Agent Lookup (`lib/constants.ts`)

- **`getAgentSourceType(name)`** — resolves agent to `active | lazy | builtin | skill | settings` with a process-level LRU cache
- **Skill index** — all skills are batch-loaded on first lookup (`ensureSkillsFullyLoaded()`), replacing per-name file-system probes with a single directory walk
- **Thresholds** — `MAX_JSON_SIZE_BYTES = 10MB`, `LARGE_OUTPUT_BYTES = 50KB`, `MAX_TOOL_SPANS_PER_AGENT = 500`, circuit-breaker tuning, plus pruning TTLs

### WriteBuffer (`lib/write-buffer.ts`)

Non-blocking JSONL append buffer.

```typescript
interface BufferEntry {
  lines: string[];    // O(1) push
  totalBytes: number; // tracked without iteration
  dirEnsured: boolean;
}
```

- **Append** — O(1) `lines.push(line)` and byte accumulation
- **Flush trigger** — 200ms interval or 8KB size threshold, whichever comes first
- **Concurrency** — `p-queue` (concurrency 1) guards writes per file; `flushing` flag prevents reentrance
- **Join at flush** — `entry.lines.join('')` is done only at write time
- **Exit safety** — synchronous flush on `beforeExit` / `exit` / `SIGINT`

### OpenTelemetry (`lib/otel.ts`, `lib/otel-monitor.ts`)

- **`withSpan(name, opts, fn, parentContext?)`** — creates a span, optionally as a child of a remote parent context (used for W3C propagation)
- **`instrumentHook(name, fn)`** — top-level wrapper that loads session trace context, builds the remote parent, and invokes `withSpan`
- **Exporters** — `FileSpanExporter` writes `~/.claude-history/telemetry/traces-YYYY-MM-DD.jsonl`; optional `OTLPTraceExporter` ships to `ingest.integritystudio.ai`
- **Metrics** — cached `Counter` / `Histogram` instruments, per-context attributes
- **Logs** — structured severity-tagged records (trace / debug / info / warn / error)

### Quality Signals (`lib/quality-signals.ts`)

- **T1 (rule-based)** — `emitToolCorrectness()` (0.0 or 1.0 per invocation), `emitCoherenceHeuristic()` (0.0–1.0)
- **T2 (LLM-based)** — relevance, coherence, explanation quality, sourced from agent-auditor
- **Task completion** — ratio of completed tasks at session end
- **Evaluation records** — `appendEvaluation()` writes JSONL via WriteBuffer to `evaluations-YYYY-MM-DD.jsonl`

---

## Performance Characteristics

### Per-Component Cost

| Component | Frequency | Typical cost | Technique |
|-----------|-----------|--------------|-----------|
| Output analysis | per tool | 1–5 ms | pre-compiled regex at module load |
| Output size gating | per object response | <1 ms for small, projected for large | sampling + extrapolation in `roughEstimateSize()` |
| Agent output scanning | per agent completion | <5 ms for 50KB+ outputs | head+tail 5KB sampling |
| Agent span building | per agent completion | O(1) common case | LIFO top-of-stack fast path |
| Agent lookup | per unique agent | O(1) after first | batched skill index + LRU source cache |
| WriteBuffer append | per log line | <1 ms | array push; join deferred to flush |
| Pruning | amortized | <1 ms | TTL eviction, O(n) per prune |
| Metric recording | per tool | <1 ms | cached instruments, O(1) lookup |

### Memory Profile

- **pendingAgents** — O(concurrent agents); typically 1–5
- **activeAgentStack** — O(agent nesting depth); typically 1–3
- **skillAgentIndex** — O(skills); one-time load
- **agentSourceCache** — bounded LRU (`lru-cache` v11)
- **WriteBuffer** — bounded by flush interval and size threshold

### Session-Scope State

All state lives at module scope in the long-lived hook-runner:

```typescript
const pendingAgents = new Map<string, PendingAgent>();      // sessionId:agentName:invokeSpanId
const activeAgentStack: PendingAgent[] = [];                 // LIFO
const seenAgents = new Map<string, string>();                // per-session first-seen
const agentSourceCache = new Map<string, AgentSourceInfo>(); // process-lifetime
const skillAgentIndex = new Map<string, string>();           // one-time loaded
```

Cleanup runs on session end via `clearSession(sessionId)` from `stop.ts`.

### Test Coverage

```
Test Files  5 passed (5)
Tests       169 passed (169)
TypeScript  no errors
```

---

## Connection to observability-toolkit MCP Server

The hooks system and the `observability-toolkit` MCP server (`~/.claude/mcp-servers/observability-toolkit/`) are coupled as **producer and consumer** across a shared telemetry boundary. The hooks write; the MCP server reads.

### Transport Paths

```
hooks/lib/otel.ts (FileSpanExporter)
  └─► ~/.claude-history/telemetry/traces-YYYY-MM-DD.jsonl
        └─► src/backends/local-jsonl.ts          (local backend)

hooks/lib/otel.ts (OTLPTraceExporter, when configured)
  └─► ingest.integritystudio.ai → R2 + D1
        └─► src/backends/cloud.ts                (cloud backend)

hooks/lib/quality-signals.ts
  └─► ~/.claude-history/telemetry/evaluations-YYYY-MM-DD.jsonl
        └─► src/tools/query-evaluations.ts
```

### Type Chain at the JSONL Boundary

Three files define the span shape independently (no shared import):

| Role | File | Type |
|------|------|------|
| Writer | `hooks/lib/otel.ts` | `ExportedSpan` — HrTime tuples, raw SDK fields |
| Local reader | `src/backends/local-jsonl.ts` | `FlatSpan` — normalized, `startTimeUnixNano` |
| Schema validation | `src/backends/backend-schemas.ts` | `traceSpanSchema` — Zod, normalized shape |

`ExportedSpan` is the canonical definition. Changes to it must be mirrored in `FlatSpan` and `traceSpanSchema` manually (cross-reference comment added in INV-1, 2026-04-06).

### Self-Instrumentation

The MCP server is itself a Claude Code MCP server. Every time Claude invokes one of its 56 tools, the post-tool hook fires — so the hooks system instruments the MCP server's own invocations. Those spans land in the same JSONL files the local backend then queries.

### Path Alignment

Both sides default to `~/.claude-history/telemetry/`:

- Hooks: `hooks/lib/constants.ts:11` — `TELEMETRY_DIR = process.env.CLAUDE_TELEMETRY_DIR || join(HOME, '.claude-history', 'telemetry')`
- MCP server: `src/lib/core/constants-telemetry.ts:23` — `DEFAULT_TELEMETRY_DIR = join(homedir(), '.claude-history', 'telemetry')` (aligned as of observability-toolkit `01dcd2e`, 2026-04-07)

`TELEMETRY_DIR` (or `CLAUDE_TELEMETRY_DIR` for hooks) overrides the default — useful for test isolation and alternate layouts.

For the full architectural diagram and coupling detail, see [observability-toolkit: docs/hooks-integration.md](../mcp-servers/observability-toolkit/docs/hooks-integration.md).

---

## Design Principles

1. **Single-threaded model** — hooks execute sequentially. LIFO assumptions, state mutations, and timer-based flushing all depend on this.
2. **Fail-open** — instrumentation failures never crash hooks. Try/catch wraps every side effect; non-critical operations are fire-and-forget.
3. **Lazy initialization** — session-scoped state is created on demand and torn down via `clearSession()` on session end.
4. **Bounded memory** — long-lived daemon requires explicit limits: TTL eviction (30 min), per-agent span cap (500), LRU caches.
5. **Non-blocking I/O** — critical path uses async WriteBuffer. Heavy operations (OTEL export, type-check spawn) are fire-and-forget.
6. **Sampling over full scans** — size estimation and large-output regex matching sample representative slices rather than traversing full payloads.

---

## Debugging

### Enable OTel Debug Logging

```bash
export OTEL_LOG_LEVEL=debug
```

### Inspect Hook Traces

```bash
# Local files
ls ~/.claude-history/telemetry/traces-*.jsonl

# Remote OTLP
curl -H "Authorization: <redacted> $OBTOOL_API_KEY" \
  'https://ingest.integritystudio.ai/v1/traces?service=claude-code-hooks'
```

### Profile a Session

```bash
/otel-session-summary SESSION_ID
```

### Inspect Agent State

```typescript
// Temporary instrumentation in post-tool.ts
const agentCtx = getActiveAgentContext();
const pending = popPendingAgent(sessionId, agentType);
console.error('[debug] agent state', { agentCtx, pending });
```

---

## Related Files

| File | Purpose |
|------|---------|
| `hooks/handlers/post-tool.ts` | Main hook router & handlers |
| `hooks/handlers/session-start.ts` | Writes session trace context |
| `hooks/handlers/stop.ts` | Session teardown, state cleanup |
| `hooks/handlers/mcp-status.ts` | MCP server error tracking |
| `hooks/handlers/post-tool-changelog-sync.ts` | Changelog version sync |
| `hooks/lib/otel.ts` | OpenTelemetry init, `withSpan`, exporters |
| `hooks/lib/otel-monitor.ts` | `instrumentHook` — top-level wrapper + trace context injection |
| `hooks/lib/trace-context.ts` | Session & prompt trace context persistence |
| `hooks/lib/write-buffer.ts` | Non-blocking log buffering |
| `hooks/lib/agent-context.ts` | Agent span state management |
| `hooks/lib/constants.ts` | Agent/skill lookup, thresholds, `TELEMETRY_DIR` |
| `hooks/lib/output-analyzer.ts` | Pre-compiled error detection & classification |
| `hooks/lib/quality-signals.ts` | Rule-based + LLM-judge quality metrics |
| `hooks/lib/circuit-breaker.ts` | Cascade-failure protection |

---

## References

- **OpenTelemetry Semantic Conventions**: https://opentelemetry.io/docs/specs/otel/protocol/exporter/
- **GenAI Conventions**: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- **W3C Trace Context**: https://www.w3.org/TR/trace-context/
- **OTel Context API**: `api.trace.setSpanContext()`, `TraceFlags.SAMPLED`, `isRemote: true`
- **Project-level summary**: `CLAUDE.md` § Hooks Architecture
