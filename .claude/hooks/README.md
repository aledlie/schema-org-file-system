# Claude Code Hooks

Observability and quality-signal hooks for Claude Code sessions. Every tool invocation flows through a hook pipeline that emits OTEL traces, metrics, and local logs.

## Data Flow

```
Claude Code Session
       |
       v
+------------------+
|  Hook Events     |
|  (settings.json) |
+------------------+
  |  |  |  |  |  |
  |  |  |  |  |  +-- Notification
  |  |  |  |  +----- UserPromptSubmit
  |  |  |  +-------- Stop
  |  |  +----------- PostToolUse
  |  +-------------- PreToolUse
  +----------------- SessionStart
       |
       v
+---------------------------+
|  hook-runner.js            |
|  (dispatcher)              |
|  - reads stdin JSON        |
|  - extracts session_id     |
|  - routes to handler       |
+---------------------------+
       |
       +---> handlers/session-start.ts
       +---> handlers/pre-tool.ts
       +---> handlers/post-tool.ts  ----+
       +---> handlers/stop.ts           |
       +---> handlers/user-prompt.ts    |
       +---> handlers/notification.ts   |
                                        |
                                        v
                        +-------------------------------+
                        |  PostToolUse Router            |
                        |  handlePostTool()              |
                        |                               |
                        |  Tool type?                   |
                        |  +-- MCP --------> handleMcpPostTool()
                        |  +-- Plugin -----> handlePluginPostTool()
                        |  +-- Agent ------> handleAgentPostTool()
                        |  +-- McpResource > (resource handler)
                        |  +-- Write ------> tsc-check
                        |  |                 py-check
                        |  |                 ts-file-create
                        |  |                 code-structure
                        |  +-- Edit/Multi -> tsc-check
                        |  |                 py-check
                        |  |                 code-structure
                        |  +-- Bash -------> post-commit-review
                        |  +-- (other) ----> builtin fallback
                        +-------------------------------+
                                        |
                    +-------------------+-------------------+
                    |                   |                   |
                    v                   v                   v
          +----------------+  +------------------+  +--------------+
          | OTEL Pipeline  |  | Cache/Invocation |  | stderr       |
          |                |  | Logs             |  | Feedback     |
          | otel.ts        |  |                  |  |              |
          | otel-monitor.ts|  | mcp-cache/       |  | [MCP] ...    |
          | synth-spans.ts |  | plugin-cache/    |  | [Agent] ...  |
          | quality-signals|  | agent-cache/     |  | [post-tool]  |
          +----------------+  | task-state/      |  +--------------+
            |           |     +------------------+
            v           v
  +--------------+  +----------------------------+
  | Remote OTLP  |  | Local JSONL                |
  | POST /v1/    |  |                            |
  | {traces,     |  | ~/.claude-history/         |
  |  metrics,    |  |   telemetry/               |
  |  logs}       |  |   traces-YYYY-MM-DD.jsonl  |
  |              |  |   evaluations-*.jsonl      |
  | Endpoint:    |  +----------------------------+
  | $OTEL_       |
  | EXPORTER_    |
  | OTLP_        |
  | ENDPOINT     |
  +--------------+
```

## Core Libraries

| Library | Role |
|---------|------|
| `lib/otel.ts` | OTEL SDK init, BatchSpanProcessor, file + OTLP exporters |
| `lib/otel-monitor.ts` | `instrumentHook()` wrapper — auto-spans per handler |
| `lib/synth-spans.ts` | Serializes `SynthSpan[]` to protobuf and POSTs to OTLP endpoint; span construction occurs in `post-tool.ts` |
| `lib/quality-signals.ts` | Rule-based metrics: `llm.tool.correctness`, `llm.output.coherence_heuristic` |
| `lib/constants.ts` | Paths, tool lists, thresholds, LRU cache for agent source lookup |
| `lib/agent-context.ts` | LIFO stack tracking in-flight agents across pre/post tool boundaries |
| `lib/cache-tracker.ts` | Per-session invocation logs to `~/.claude/{type}-cache/{session_id}/` |
| `lib/circuit-breaker.ts` | Protects OTEL exporters: closed -> open -> half-open after N failures |
| `lib/write-buffer.ts` | Array-based O(1) append buffer, flush on interval/threshold |
| `lib/token-metrics.ts` | `gen_ai.client.token.usage`, `gen_ai.client.cost` |
| `lib/trace-context.ts` | Cross-hook span correlation — persists prompt context for pre/post linking |
| `lib/context-tracker.ts` | Context window utilization tracking across sessions |
| `lib/quality-sampler.ts` | T2 LLM judge session sampling decisions |
| `lib/quality-budget.ts` | Daily evaluation budget tracking for T2 quality evals |
| `lib/transcript-parser.ts` | Transcript JSONL turn extraction for quality evaluation |
| `lib/telemetry-alerts.ts` | Operational alert rules evaluated at session end |
| `lib/load-envrc.ts` | Parses `~/.claude/.envrc` into `process.env` on import |

## Span Types

| Span Name | Trigger |
|-----------|---------|
| `hook:builtin-post-tool` | Read, Write, Edit, Bash, Glob, Grep |
| `hook:mcp-post-tool` | MCP server tool calls |
| `hook:plugin-post-tool` | Skill invocations |
| `hook:agent-post-tool` | Agent launches |
| `hook:tsc-check` / `hook:py-check` | Type/syntax checks on file writes |
| `hook:code-structure` | Code quality signals on Write/Edit |
| `hook:ts-file-create` | New TypeScript file creation |
| `hook:post-commit-review` | Git commit detection via Bash |
| `hook:mcp-server-failure` | MCP server init failures |
| `create_agent` / `invoke_agent` / `execute_tool` | Synthetic agent lifecycle (protobuf) |

## Resource Attributes

Every exported span carries:

- `service.name` = `claude-code-hooks`
- `service.version` = `1.0.0`
- `project.name` = working directory basename
- `github.repo` = `owner/repo` from git remote (optional)
- Additional attributes from `OTEL_RESOURCE_ATTRIBUTES` env var (e.g. `deployment.environment`, `user.name`) via `envDetector`

## Transport

- **Protocol**: `http/protobuf`
- **Compression**: `gzip` if `OTEL_EXPORTER_OTLP_COMPRESSION` env var is set
- **Auth**: Bearer token via `OTEL_EXPORTER_OTLP_HEADERS`
- **Timeout**: SDK default (10s) for `OTLPTraceExporter`; 5s for synthetic span submission via `synth-spans.ts`
- **Processor**: `BatchSpanProcessor` (flush on shutdown or interval)
- **Circuit breaker**: Opens after repeated export failures, half-opens on cooldown

## Running Tests

```bash
npx vitest run hooks/handlers/   # handler tests
npx vitest run hooks/             # full suite
```
