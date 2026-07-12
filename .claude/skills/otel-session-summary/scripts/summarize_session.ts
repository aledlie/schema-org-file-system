#!/usr/bin/env tsx
/**
 * Console summary of OTEL session telemetry data.
 *
 * Usage: summarize_session.ts [session-id] [--seed] [--json]
 *
 * Options:
 *   --json   Output structured JSON instead of console-formatted text.
 *   --seed   Emit SEED_JUDGE_DATA block for LLM-as-Judge phase.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

const MAX_PROMPT_CHARS = 500;
const SESSION_ID_PATTERN = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const TRANSCRIPT_EXT = '.jsonl';
const MAX_FILE_BYTES = 100 * 1024 * 1024; // 100 MB cap per telemetry file
const DEBUG = process.env['OTEL_LOG_LEVEL'] === 'debug';

const INGEST_API_URL = process.env['INGEST_API_URL'] ?? 'https://ingest.integritystudio.ai';
const TELEMETRY_DIR = process.env['CLAUDE_TELEMETRY_DIR'] ?? join(homedir(), '.claude-history', 'telemetry');

/**
 * Mirrors ExportedSpan from hooks/lib/otel.ts (FileSpanExporter.serialize output).
 * All fields are optional here because JSONL parsing is defensive; in practice
 * every field is present when written by the hooks exporter.
 * If the serializer shape changes, update both interfaces in sync.
 */
interface Span {
  traceId?: string;
  spanId?: string;
  parentSpanId?: string;
  name?: string;
  kind?: number;
  startTime?: [number, number];
  endTime?: [number, number];
  duration?: [number, number];
  status?: { code: number; message?: string };
  attributes?: Record<string, unknown>;
  events?: unknown[];
  links?: unknown[];
  resource?: { serviceName?: string; serviceVersion?: string };
  instrumentationScope?: { name: string; version?: string };
  [key: string]: unknown;
}

function debug(...args: unknown[]): void {
  if (DEBUG) console.error('DEBUG:', ...args);
}

async function queryRemoteTraces(sessionId: string, apiUrl = INGEST_API_URL): Promise<Span[]> {
  try {
    const url = new URL(`${apiUrl}/api/traces`);
    url.searchParams.set('session_id', sessionId);
    debug(`Querying remote API: ${url}`);

    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }

    const data = await response.json() as { spans?: Span[] };
    const spans = data.spans ?? [];
    debug(`Received ${spans.length} spans from remote API`);
    return spans;
  } catch (e) {
    debug(`Remote API query failed: ${e}. Falling back to local files.`);
    return loadTracesLocal(sessionId);
  }
}

function globTraceFiles(dir: string): string[] {
  try {
    return readdirSync(dir)
      .filter((f: string) => /^traces-.*\.jsonl$/.test(f))
      .sort()
      .map((f: string) => join(dir, f));
  } catch {
    return [];
  }
}

export function loadTracesLocal(sessionId: string, telemetryDir = TELEMETRY_DIR): Span[] {
  const traces: Span[] = [];
  const files = globTraceFiles(telemetryDir);
  debug(`Scanning ${files.length} telemetry files in ${telemetryDir}`);

  for (const f of files) {
    try {
      if (statSync(f).size > MAX_FILE_BYTES) {
        debug(`Skipping oversized file: ${f}`);
        continue;
      }
    } catch (e) {
      debug(`Cannot stat file, skipping: ${f} (${e})`);
      continue;
    }

    let fileCount = 0;
    try {
      for (const line of readFileSync(f, 'utf-8').split('\n')) {
        if (!line.trim()) continue;
        try {
          const obj = JSON.parse(line) as Record<string, unknown>;
          const attrs = obj['attributes'] as Record<string, unknown> | undefined;
          if (attrs?.['session.id'] === sessionId) {
            const span: Span = {
              traceId: (obj['traceId'] as string) || undefined,
              spanId: (obj['spanId'] as string) || undefined,
              name: (obj['name'] as string) || undefined,
              kind: (obj['kind'] as number) || undefined,
              startTime: obj['startTime'] as [number, number] | undefined,
              endTime: obj['endTime'] as [number, number] | undefined,
              duration: obj['duration'] as [number, number] | undefined,
              status: obj['status'] as { code: number } | undefined,
              attributes: attrs,
              events: obj['events'] as unknown[] | undefined,
              links: obj['links'] as unknown[] | undefined,
              resource: obj['resource'] as { serviceName: string; serviceVersion: string } | undefined,
            };
            traces.push(span);
            fileCount++;
            debug(`  ${f}: loaded span ${span.traceId}/${span.spanId} (${span.name})`);
          }
        } catch {
          // skip malformed lines
        }
      }
    } catch (e) {
      debug(`Cannot read file ${f}: ${e}`);
      continue;
    }
    if (fileCount) debug(`  ${f}: ${fileCount} matching spans`);
  }

  debug(`Total: ${traces.length} spans for session ${sessionId}`);
  return traces;
}

export async function loadTraces(sessionId: string): Promise<Span[]> {
  return queryRemoteTraces(sessionId);
}

export function parseSpanTs(obj: Span): number {
  const raw = obj['startTimeUnixNano'] ?? obj['start_time_unix_nano'];
  if (raw != null) {
    const n = Number(raw);
    if (!isNaN(n)) return n;
  }
  const start = obj['startTime'];
  if (Array.isArray(start) && start.length >= 1) {
    const secs = Number(start[0]);
    const nanos = start.length > 1 ? Number(start[1]) : 0;
    if (!isNaN(secs) && !isNaN(nanos)) return secs * 1_000_000_000 + nanos;
  }
  return 0;
}

/**
 * Find the current session by checking the most recently modified transcript file.
 * Transcript filenames are {session-uuid}.jsonl, giving a reliable session ID.
 */
export function findCurrentSessionFromTranscript(): string | null {
  const projectsDir = join(homedir(), '.claude', 'projects');

  // Claude Code convention: replace `/` with `-`, then leading dot of each
  // path component (`-.`) becomes `--`.
  const deriveProjectName = (path: string): string =>
    path.replace(/\//g, '-').replace(/-\./g, '--');

  const scanDir = (dir: string): { sessionId: string; mtime: number; dir: string } | null => {
    let best: { sessionId: string; mtime: number; dir: string } | null = null;
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return null;
    }
    for (const f of entries) {
      if (!f.endsWith(TRANSCRIPT_EXT)) continue;
      const base = f.slice(0, -TRANSCRIPT_EXT.length);
      if (!SESSION_ID_PATTERN.test(base)) continue;
      try {
        const mtime = statSync(join(dir, f)).mtimeMs;
        if (!best || mtime > best.mtime) best = { sessionId: base, mtime, dir };
      } catch (err) {
        debug(`scanDir stat failed for ${join(dir, f)}: ${String(err)}`);
      }
    }
    return best;
  };

  let projectSet: Set<string>;
  try {
    projectSet = new Set(readdirSync(projectsDir));
  } catch (err) {
    debug(`Cannot read projects dir ${projectsDir}: ${String(err)}`);
    return null;
  }

  // Walk upward from CWD so that running from a subdirectory still maps to
  // the enclosing project's transcript dir.
  let cur = process.cwd();
  while (true) {
    const derived = deriveProjectName(cur);
    if (projectSet.has(derived)) {
      const result = scanDir(join(projectsDir, derived));
      if (result) {
        debug(`Found session from project transcript: ${result.sessionId} (mtime ${new Date(result.mtime).toISOString()}, dir ${derived}, cwd-ancestor ${cur})`);
        return result.sessionId;
      }
    }
    const parent = resolve(cur, '..');
    if (parent === cur) break;
    cur = parent;
  }

  // Fallback: scan all project directories. Crossing projects is a red flag,
  // so warn to stderr when it happens.
  let best: { sessionId: string; mtime: number; dir: string } | null = null;
  for (const name of projectSet) {
    const result = scanDir(join(projectsDir, name));
    if (result && (!best || result.mtime > best.mtime)) best = result;
  }

  if (best) {
    console.error(
      `WARNING: session ${best.sessionId} selected via cross-project fallback (dir ${best.dir}). ` +
      `CWD-derived lookup from ${process.cwd()} did not match any project transcript.`,
    );
    return best.sessionId;
  }
  return null;
}

export function findLatestSessionId(telemetryDir = TELEMETRY_DIR): string | null {
  let bestTs = -1;
  let last: string | null = null;
  const files = globTraceFiles(telemetryDir).reverse(); // newest first
  debug(`Scanning ${files.length} telemetry files (newest first)`);

  for (const f of files) {
    let fileHadValidSpan = false;
    try {
      if (statSync(f).size > MAX_FILE_BYTES) {
        debug(`Skipping oversized file: ${f}`);
        continue;
      }
    } catch (e) {
      debug(`Cannot stat file, skipping: ${f} (${e})`);
      continue;
    }

    try {
      for (const line of readFileSync(f, 'utf-8').split('\n')) {
        if (!line.trim()) continue;
        try {
          const obj = JSON.parse(line) as Span;
          const attrs = obj['attributes'] as Record<string, unknown> | undefined;
          const sid = (attrs?.['session.id'] as string | undefined) ?? '';
          if (!sid || !SESSION_ID_PATTERN.test(sid)) continue;
          const ts = parseSpanTs(obj);
          if (ts > bestTs) {
            bestTs = ts;
            last = sid;
            fileHadValidSpan = true;
            debug(`Found session ${sid} (span=${obj['name']}) in ${f}`);
          }
        } catch {
          // skip malformed lines
        }
      }
    } catch (e) {
      debug(`Cannot read file ${f}: ${e}`);
    }

    if (fileHadValidSpan) {
      debug(`Found valid session in ${f}, stopping search`);
      break;
    }
  }

  if (last === null) {
    console.error(`WARNING: No session with valid UUID session.id found after scanning ${files.length} files`);
  } else if (bestTs > 0) {
    const ageHours = (Date.now() / 1000 - bestTs / 1e9) / 3600;
    if (ageHours > 24) {
      console.error(
        `Warning: nearest session with telemetry is ${ageHours.toFixed(0)}h old (${last}).\n` +
        `Recent sessions may lack session.id — run hooks/build or check hook config.\n`,
      );
    }
  }
  return last;
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

type StatusResult = 'healthy' | 'warning' | 'critical' | 'n/a';

export function statusBadge(metric: string, value: number | null): StatusResult {
  if (value === null) return 'n/a';
  if (metric === 'eval_latency') {
    if (value <= 1.0) return 'healthy';
    if (value <= 5.0) return 'warning';
    return 'critical';
  }
  const thresholds: Record<string, [number, number]> = {
    tool_correctness: [0.95, 0.9],
    task_completion: [0.9, 0.7],
  };
  const t = thresholds[metric];
  if (!t) return 'n/a';
  if (value >= t[0]) return 'healthy';
  if (value >= t[1]) return 'warning';
  return 'critical';
}

export function bar(value: number | null, width = 20): string {
  if (value === null) return '?'.repeat(width);
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * width);
  return '\u2588'.repeat(filled) + '\u2591'.repeat(width - filled);
}

export function getToolSpans(traces: Span[]): Span[] {
  return traces.filter(t => t['name'] === 'hook:builtin-post-tool' || t['name'] === 'hook:mcp-post-tool');
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? (sorted[mid] as number)
    : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

export interface Tokens {
  input: number;
  output: number;
  cache_read: number;
  cache_create: number;
  total: number;
}

export interface Metrics {
  total_spans: number;
  hook_counts: Record<string, number>;
  unique_hooks: number;
  unique_traces: number;
  tool_correctness: number | null;
  eval_latency: number | null;
  task_completion: number | null;
  tokens: Tokens;
  files_touched: string[];
  avg_code_structure: number | null;
}

export function extractMetrics(traces: Span[]): Metrics {
  const hookCounts: Record<string, number> = {};
  for (const t of traces) {
    const name = (t['name'] as string | undefined) ?? 'unknown';
    hookCounts[name] = (hookCounts[name] ?? 0) + 1;
  }

  const toolSpans = getToolSpans(traces);

  const successCount = toolSpans.filter(t => {
    const attrs = t['attributes'] as Record<string, unknown> | undefined;
    return Boolean(attrs?.['builtin.success'] ?? attrs?.['mcp.success'] ?? false);
  }).length;
  const toolCorrectness = toolSpans.length > 0 ? successCount / toolSpans.length : null;

  const durations: number[] = [];
  for (const t of traces) {
    const d = t['duration'];
    if (!Array.isArray(d) || d.length !== 2) continue;
    const secs = Number(d[0]);
    const nanos = Number(d[1]);
    if (!isNaN(secs) && !isNaN(nanos)) durations.push(secs + nanos / 1e9);
  }
  const evalLatency = durations.length > 0 ? median(durations) : null;

  const getAttrs = (t: Span) => t['attributes'] as Record<string, unknown> | undefined;

  const taskCreates = toolSpans.filter(t => getAttrs(t)?.['builtin.tool'] === 'TaskCreate').length;
  const taskCompletes = toolSpans.filter(t => {
    const attrs = getAttrs(t);
    return attrs?.['builtin.tool'] === 'TaskUpdate' && attrs?.['builtin.task_status'] === 'completed';
  }).length;
  const taskCompletion = taskCreates > 0 ? taskCompletes / taskCreates : null;

  const tokenSpans = traces.filter(t => t['name'] === 'hook:token-metrics-extraction');
  const sumAttr = (key: string) => tokenSpans.reduce((acc, t) => {
    const v = Number(getAttrs(t)?.[key] ?? 0);
    return acc + (isNaN(v) ? 0 : v);
  }, 0);
  const totalInput = sumAttr('tokens.input');
  const totalOutput = sumAttr('tokens.output');
  const totalCache = sumAttr('tokens.cache_read');
  const totalCacheCreate = sumAttr('tokens.cache_creation');

  const filesTouched = new Set<string>();
  for (const t of toolSpans) {
    const attrs = getAttrs(t);
    const tool = (attrs?.['builtin.tool'] as string | undefined) ?? '';
    if (['Write', 'Edit', 'MultiEdit'].includes(tool)) {
      const fp = (attrs?.['builtin.file_path'] as string | undefined) ?? '';
      if (fp) filesTouched.add(fp);
    }
  }

  // OBP7b: dual-read — prefer canonical integritystudio.* key, fall back to legacy
  const readStructureScore = (t: (typeof traces)[number]) => {
    const a = getAttrs(t);
    return a?.['integritystudio.code.structure.score'] ?? a?.['code.structure.score'];
  };
  const structureSpans = traces.filter(t => readStructureScore(t) != null);
  const avgStructure = structureSpans.length > 0
    ? structureSpans.reduce((acc, t) => acc + Number(readStructureScore(t)), 0) / structureSpans.length
    : null;

  const uniqueTraceIds = new Set<string>();
  for (const t of traces) {
    const tid = t.traceId;
    if (tid) uniqueTraceIds.add(tid);
  }

  const sortedHookCounts = Object.fromEntries(
    Object.entries(hookCounts).sort(([, a], [, b]) => b - a),
  );

  return {
    total_spans: traces.length,
    hook_counts: sortedHookCounts,
    unique_hooks: Object.keys(hookCounts).length,
    unique_traces: uniqueTraceIds.size,
    tool_correctness: toolCorrectness,
    eval_latency: evalLatency,
    task_completion: taskCompletion,
    tokens: {
      input: totalInput,
      output: totalOutput,
      cache_read: totalCache,
      cache_create: totalCacheCreate,
      total: totalInput + totalOutput,
    },
    files_touched: [...filesTouched].sort(),
    avg_code_structure: avgStructure,
  };
}

function printConsoleSummary(sessionId: string, metrics: Metrics): void {
  const sep = '-'.repeat(56);
  console.log();
  console.log(sep);
  console.log('  OTEL Session Summary');
  console.log(sep);
  console.log(`  Session:  ${sessionId}`);
  console.log(`  Spans:    ${metrics.total_spans}`);
  console.log(`  Traces:   ${metrics.unique_traces}`);
  console.log(`  Hooks:    ${metrics.unique_hooks} unique`);
  console.log(sep);

  const { tokens } = metrics;
  console.log('  Tokens');
  console.log(`    Input:          ${fmtTokens(tokens.input).padStart(8)}`);
  console.log(`    Output:         ${fmtTokens(tokens.output).padStart(8)}`);
  console.log(`    Cache read:     ${fmtTokens(tokens.cache_read).padStart(8)}`);
  console.log(`    Cache create:   ${fmtTokens(tokens.cache_create).padStart(8)}`);
  console.log(`    Total:          ${fmtTokens(tokens.total).padStart(8)}`);
  console.log(sep);

  console.log('  Metrics');
  const { tool_correctness: tc, eval_latency: el, task_completion: tkc, avg_code_structure: avgS } = metrics;

  if (tc !== null) {
    console.log(`    tool_correctness  ${bar(tc)}  ${tc.toFixed(2)}  ${statusBadge('tool_correctness', tc)}`);
  } else {
    console.log(`    tool_correctness  ${'n/a'.padStart(26)}`);
  }

  if (el !== null) {
    const latScore = Math.max(0, Math.min(1, 1 - el / 5));
    console.log(`    eval_latency      ${bar(latScore)}  ${el.toFixed(3)}s  ${statusBadge('eval_latency', el)}`);
  } else {
    console.log(`    eval_latency      ${'n/a'.padStart(26)}`);
  }

  if (tkc !== null) {
    console.log(`    task_completion   ${bar(tkc)}  ${tkc.toFixed(2)}  ${statusBadge('task_completion', tkc)}`);
  } else {
    console.log(`    task_completion   ${'n/a'.padStart(26)}`);
  }

  if (avgS !== null) {
    console.log(`    code_structure    ${bar(avgS)}  ${avgS.toFixed(2)}`);
  }

  console.log(sep);

  console.log('  Hook Breakdown');
  for (const [hook, count] of Object.entries(metrics.hook_counts)) {
    const label = hook.replace('hook:', '');
    console.log(`    ${label.padEnd(32)} ${String(count).padStart(4)}`);
  }
  console.log(sep);

  if (metrics.files_touched.length > 0) {
    console.log(`  Files Touched (${metrics.files_touched.length})`);
    for (const fp of metrics.files_touched) {
      console.log(`    ${fp.replace(homedir(), '~')}`);
    }
    console.log(sep);
  }
}

async function main(): Promise<void> {
  const rawArgs = process.argv.slice(2);
  const seedMode = rawArgs.includes('--seed');
  const jsonMode = rawArgs.includes('--json');
  const args = rawArgs.filter(a => a !== '--seed' && a !== '--json');
  let sessionId: string | null = (args[0] ?? '').trim() || null;

  if (sessionId && !SESSION_ID_PATTERN.test(sessionId)) {
    console.error(`Invalid session ID format: ${JSON.stringify(sessionId)} (expected UUID)`);
    process.exit(1);
  }
  if (!sessionId) {
    const envSid = process.env.CLAUDE_SESSION_ID?.trim();
    if (envSid && SESSION_ID_PATTERN.test(envSid)) {
      sessionId = envSid;
      debug(`Using session ID from CLAUDE_SESSION_ID env var: ${sessionId}`);
    }
  }
  if (!sessionId) {
    sessionId = findCurrentSessionFromTranscript();
  }
  if (!sessionId) {
    sessionId = findLatestSessionId();
  }
  if (!sessionId) {
    const files = globTraceFiles(TELEMETRY_DIR);
    let msg =
      `No session found in telemetry data.\n` +
      `Checked ${files.length} files in ${TELEMETRY_DIR}\n\n` +
      `For debugging, run:\n  OTEL_LOG_LEVEL=debug tsx ${process.argv[1]} ${rawArgs.join(' ')}`;
    if (files.length === 0) msg += `\n\nNo traces files found. Check TELEMETRY_DIR is correct.`;
    console.error(msg);
    process.exit(1);
  }

  const traces = await loadTraces(sessionId);
  if (traces.length === 0) {
    const files = globTraceFiles(TELEMETRY_DIR);
    console.error(`Searched ${files.length} telemetry files, 0 spans matched session ${sessionId}`);
    console.log(`No traces found for session ${sessionId}`);
    process.exit(1);
  }

  const metrics = extractMetrics(traces);

  if (jsonMode) {
    console.log(JSON.stringify({ session_id: sessionId, ...metrics }, null, 2));
    return;
  }

  printConsoleSummary(sessionId, metrics);

  if (seedMode) {
    const toolSpans = getToolSpans(traces);
    const userPrompts: string[] = [];
    for (const t of traces) {
      const up = ((t['attributes'] as Record<string, unknown> | undefined)?.['user.prompt'] as string | undefined) ?? '';
      if (up) userPrompts.push(up.slice(0, MAX_PROMPT_CHARS));
    }
    const toolsUsed = [...new Set(
      toolSpans
        .map(t => ((t['attributes'] as Record<string, unknown>)?.['builtin.tool'] as string | undefined))
        .filter((x): x is string => Boolean(x)),
    )].sort();
    let minNs = Infinity;
    let maxNs = -Infinity;
    for (const t of traces) {
      const ts = parseSpanTs(t);
      if (ts > 0 && ts < minNs) minNs = ts;
      if (ts > maxNs) maxNs = ts;
    }
    const sessionStartEpochS = minNs === Infinity ? null : Math.floor(minNs / 1e9);
    const sessionEndEpochS = maxNs === -Infinity ? null : Math.ceil(maxNs / 1e9);

    const seedData = {
      session_id: sessionId,
      files_touched: metrics.files_touched,
      tools_used: toolsUsed,
      total_spans: metrics.total_spans,
      user_prompts: userPrompts.slice(0, 5),
      session_start_epoch_s: sessionStartEpochS,
      session_end_epoch_s: sessionEndEpochS,
    };
    console.log();
    console.log('SEED_JUDGE_DATA');
    console.log(JSON.stringify(seedData, null, 2));
  }

  console.log();
}

// Only run the CLI when executed directly (e.g. `tsx summarize_session.ts`),
// not when imported by tests or other modules.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error('Fatal error:', err);
    process.exit(1);
  });
}
