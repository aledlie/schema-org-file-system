#!/usr/bin/env tsx
/**
 * Generate a self-contained HTML review dashboard from OTEL session telemetry.
 *
 * Queries traces, evaluations, and computes quality metrics via the
 * observability-toolkit library. Outputs a single HTML file with all data inlined.
 *
 * Usage:
 *   npx tsx generate-review-dashboard.ts [options]
 *
 * Options:
 *   --session <id>    Session ID (default: auto-detect latest)
 *   --date <YYYY-MM-DD>  Filter date (default: today)
 *   --output <path>   Output HTML path (default: ./review-dashboard-<date>.html)
 *   --title <text>    Dashboard title (default: "Review Session")
 *   --findings <json> Path to JSON file with review findings to overlay
 *   --commits <json>  Path to JSON file with commit data to overlay
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { join, resolve } from 'path';

import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OBS_TOOLKIT = resolve(__dirname, '..', '..', '..', 'mcp-servers', 'observability-toolkit');
const TELEMETRY_DIR = join(process.env.HOME ?? '', '.claude', 'telemetry');

// Lazy-loaded observability-toolkit imports (resolved at runtime to avoid top-level await)
let _MultiDirectoryBackend: any;
let _computeDashboardSummary: any;

async function loadObsToolkit(): Promise<void> {
  const backends = await import(join(OBS_TOOLKIT, 'dist', 'backends', 'local-jsonl.js'));
  _MultiDirectoryBackend = backends.MultiDirectoryBackend;
  const lib = await import(join(OBS_TOOLKIT, 'dist', 'lib', 'index.js'));
  _computeDashboardSummary = lib.computeDashboardSummary;
}

// --- CLI args ---
const args = process.argv.slice(2);
function getArg(name: string): string | undefined {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 ? args[idx + 1] : undefined;
}

const today = new Date().toISOString().slice(0, 10);
const sessionId = getArg('session');
const dateFilter = getArg('date') ?? today;
if (!/^\d{4}-\d{2}-\d{2}$/.test(dateFilter)) {
  console.error('[generate-review-dashboard] Invalid --date format. Use YYYY-MM-DD');
  process.exit(1);
}
const rawOutput = getArg('output') ?? `review-dashboard-${dateFilter}.html`;
// S2: restrict output to .html files in current directory (no path traversal)
const outputBasename = rawOutput.replace(/^.*[\\/]/, '');
if (!/^[\w\-.]+\.html$/.test(outputBasename)) {
  console.error('[generate-review-dashboard] Invalid --output. Must be a .html filename');
  process.exit(1);
}
const outputPath = resolve(process.cwd(), outputBasename);
const dashTitle = getArg('title') ?? 'Review Session';
const findingsPath = getArg('findings');
const commitsPath = getArg('commits');

// --- Trace types (matching derive-evaluations.ts) ---
interface TraceSpan {
  traceId: string;
  spanId: string;
  name: string;
  startTime: [number, number];
  endTime: [number, number];
  duration: [number, number];
  status: { code: number };
  attributes: Record<string, unknown>;
}

// --- Load trace spans for session ---
function loadTraces(sid?: string): TraceSpan[] {
  const spans: TraceSpan[] = [];
  const files = readdirSync(TELEMETRY_DIR)
    .filter(f => f.startsWith('traces-') && f.endsWith('.jsonl'))
    .sort();

  for (const file of files) {
    const lines = readFileSync(join(TELEMETRY_DIR, file), 'utf-8').split('\n').filter(Boolean);
    for (const line of lines) {
      try {
        const span = JSON.parse(line) as TraceSpan;
        if (!sid || span.attributes['session.id'] === sid) {
          spans.push(span);
        }
      } catch { /* skip malformed */ }
    }
  }
  return spans;
}

function findLatestSessionId(): string | null {
  let last: string | null = null;
  const files = readdirSync(TELEMETRY_DIR)
    .filter(f => f.startsWith('traces-') && f.endsWith('.jsonl'))
    .sort();

  for (const file of files) {
    const lines = readFileSync(join(TELEMETRY_DIR, file), 'utf-8').split('\n').filter(Boolean);
    for (const line of lines) {
      try {
        const span = JSON.parse(line) as TraceSpan;
        if (span.name === 'hook:session-start') {
          const sid = span.attributes['session.id'];
          if (typeof sid === 'string' && sid) last = sid;
        }
      } catch { /* skip */ }
    }
  }
  return last;
}

function hrtToSeconds(hrt: [number, number]): number {
  return hrt[0] + hrt[1] / 1e9;
}

// --- Compute session metrics from raw traces ---
interface SessionMetrics {
  sessionId: string;
  totalSpans: number;
  toolSpans: number;
  toolSuccess: number;
  toolFailure: number;
  toolCorrectness: number | null;
  evaluationLatencyMedian: number | null;
  taskCreates: number;
  taskCompletes: number;
  taskCompletion: number | null;
  tokenInput: number;
  tokenOutput: number;
  tokenCacheRead: number;
  tokenTotal: number;
  hooksUsed: string[];
  toolBreakdown: Record<string, { success: number; failure: number }>;
  agentBreakdown: Record<string, number>;
  spanDurations: number[];
}

function computeSessionMetrics(spans: TraceSpan[]): SessionMetrics {
  const toolSpans = spans.filter(s =>
    s.name === 'hook:builtin-post-tool' || s.name === 'hook:mcp-post-tool'
  );

  let toolSuccess = 0;
  let toolFailure = 0;
  const toolBreakdown: Record<string, { success: number; failure: number }> = {};

  for (const s of toolSpans) {
    const isBuiltin = s.name === 'hook:builtin-post-tool';
    const success = isBuiltin ? s.attributes['builtin.success'] : s.attributes['mcp.success'];
    const tool = String(isBuiltin ? s.attributes['builtin.tool'] : s.attributes['mcp.tool'] ?? 'unknown');
    const server = !isBuiltin ? s.attributes['mcp.server'] : undefined;
    const label = server ? `${server}/${tool}` : tool;

    if (!toolBreakdown[label]) toolBreakdown[label] = { success: 0, failure: 0 };
    if (success === true) {
      toolSuccess++;
      toolBreakdown[label].success++;
    } else {
      toolFailure++;
      toolBreakdown[label].failure++;
    }
  }

  // Durations
  const durations: number[] = [];
  for (const s of spans) {
    if (s.duration) durations.push(hrtToSeconds(s.duration));
  }
  durations.sort((a, b) => a - b);
  const medianLatency = durations.length > 0
    ? durations[Math.floor(durations.length / 2)]
    : null;

  // Tasks
  let taskCreates = 0;
  let taskCompletes = 0;
  for (const s of toolSpans) {
    const tool = s.attributes['builtin.tool'];
    if (tool === 'TaskCreate') taskCreates++;
    if (tool === 'TaskUpdate' && s.attributes['builtin.task_status'] === 'completed') taskCompletes++;
  }

  // Tokens
  const tokenSpans = spans.filter(s => s.name === 'hook:token-metrics-extraction');
  let tokenInput = 0, tokenOutput = 0, tokenCacheRead = 0;
  for (const s of tokenSpans) {
    tokenInput += Number(s.attributes['tokens.input'] ?? 0);
    tokenOutput += Number(s.attributes['tokens.output'] ?? 0);
    tokenCacheRead += Number(s.attributes['tokens.cache_read'] ?? 0);
  }

  // Agents
  const agentBreakdown: Record<string, number> = {};
  for (const s of spans) {
    if (s.name === 'hook:agent-post-tool') {
      // OBP7b: dual-read — prefer canonical integritystudio.* key, fall back to legacy
      const type = String(s.attributes['integritystudio.agent.type'] ?? s.attributes['agent.type'] ?? 'unknown');
      agentBreakdown[type] = (agentBreakdown[type] ?? 0) + 1;
    }
  }

  const hooks = [...new Set(spans.map(s => s.name))].sort();
  const sid = String(spans[0]?.attributes['session.id'] ?? 'unknown');

  return {
    sessionId: sid,
    totalSpans: spans.length,
    toolSpans: toolSpans.length,
    toolSuccess,
    toolFailure,
    toolCorrectness: toolSpans.length > 0 ? toolSuccess / toolSpans.length : null,
    evaluationLatencyMedian: medianLatency,
    taskCreates,
    taskCompletes,
    taskCompletion: taskCreates > 0 ? taskCompletes / taskCreates : null,
    tokenInput,
    tokenOutput,
    tokenCacheRead,
    tokenTotal: tokenInput + tokenOutput,
    hooksUsed: hooks,
    toolBreakdown,
    agentBreakdown,
    spanDurations: durations,
  };
}

// --- Query evaluations via compiled backend ---
interface EvalAgg {
  name: string;
  displayName: string;
  avg: number | null;
  p50: number | null;
  p95: number | null;
  count: number;
  status: string;
  alerts: Array<{ severity: string; message: string }>;
}

async function computeQualityScorecard(
  startDate: string,
  endDate: string,
): Promise<{ dashboard: any; evalAggs: EvalAgg[] }> {
  const backend = new _MultiDirectoryBackend(undefined, true);
  const evals = await backend.queryEvaluations({ startDate, endDate, limit: 10000 });

  // Group by evaluation name
  const grouped = new Map<string, any[]>();
  for (const ev of evals) {
    const name = ev.evaluationName;
    if (!grouped.has(name)) grouped.set(name, []);
    grouped.get(name)!.push(ev);
  }

  const dashboard = _computeDashboardSummary(grouped);

  const evalAggs: EvalAgg[] = dashboard.metrics.map((m: any) => ({
    name: m.name,
    displayName: m.displayName,
    avg: m.values.avg ?? null,
    p50: m.values.p50 ?? null,
    p95: m.values.p95 ?? null,
    count: m.sampleCount,
    status: m.status,
    alerts: m.alerts.map((a: any) => ({ severity: a.severity, message: a.message })),
  }));

  return { dashboard, evalAggs };
}

// --- Load optional overlay data ---
interface Finding {
  id: string;
  severity: string;
  title: string;
  description: string;
  file?: string;
  status?: string;
}

interface Commit {
  hash: string;
  message: string;
  tag?: string;
  review?: string;
}

function loadJson<T>(path: string | undefined): T | null {
  if (!path || !existsSync(path)) return null;
  return JSON.parse(readFileSync(path, 'utf-8'));
}

// --- HTML template generation ---
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

function statusColor(status: string): string {
  switch (status) {
    case 'healthy': return 'var(--success)';
    case 'warning': return 'var(--high)';
    case 'critical': return 'var(--critical)';
    default: return 'var(--text-muted)';
  }
}

function statusBg(status: string): string {
  switch (status) {
    case 'healthy': return 'var(--success-bg)';
    case 'warning': return 'var(--high-bg)';
    case 'critical': return 'var(--critical-bg)';
    default: return 'var(--surface-3)';
  }
}

function statusBorder(status: string): string {
  switch (status) {
    case 'healthy': return 'var(--success-border)';
    case 'warning': return 'var(--high-border)';
    case 'critical': return 'var(--critical-border)';
    default: return 'var(--border)';
  }
}

function fmtScore(val: number | null, unit?: string): string {
  if (val === null) return '--';
  if (unit === 'seconds') return `${val.toFixed(3)}s`;
  if (val <= 1.0) return (val * 100).toFixed(1) + '%';
  return val.toFixed(2);
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function generateScorecardRows(evalAggs: EvalAgg[]): string {
  const metricUnits: Record<string, string> = {
    evaluation_latency: 'seconds',
    hallucination: 'rate',
  };

  return evalAggs.map(m => {
    const unit = metricUnits[m.name];
    const barWidth = m.avg !== null ? Math.min(Math.round(m.avg * 100), 100) : 0;
    const isInverse = m.name === 'hallucination';
    const effectiveWidth = isInverse && m.avg !== null ? Math.min(Math.round((1 - m.avg) * 100), 100) : barWidth;

    return `
      <div class="scorecard-row">
        <div class="scorecard-name">${escapeHtml(m.displayName)}</div>
        <div class="scorecard-bar-track">
          <div class="scorecard-bar-fill" data-width="${unit === 'seconds' ? 50 : effectiveWidth}"
               style="background:${statusColor(m.status)}"></div>
        </div>
        <div class="scorecard-value" style="color:${statusColor(m.status)}">${fmtScore(m.avg, unit)}</div>
        <div class="scorecard-count">${m.count}</div>
        <span class="scorecard-status" style="color:${statusColor(m.status)};background:${statusBg(m.status)};border:1px solid ${statusBorder(m.status)}">${escapeHtml(m.status)}</span>
      </div>`;
  }).join('\n');
}

function generateToolBreakdown(breakdown: Record<string, { success: number; failure: number }>): string {
  const sorted = Object.entries(breakdown).sort((a, b) => (b[1].success + b[1].failure) - (a[1].success + a[1].failure));
  return sorted.slice(0, 15).map(([tool, counts]) => {
    const total = counts.success + counts.failure;
    const pct = total > 0 ? Math.round(counts.success / total * 100) : 0;
    return `
      <div class="tool-row">
        <span class="tool-name">${escapeHtml(tool)}</span>
        <span class="tool-bar-track">
          <span class="tool-bar-fill" data-width="${pct}"></span>
        </span>
        <span class="tool-count">${counts.success}/${total}</span>
      </div>`;
  }).join('\n');
}

function generateAlerts(dashboard: any): string {
  if (!dashboard.alerts || dashboard.alerts.length === 0) {
    return '<div class="no-alerts">No active alerts</div>';
  }
  return dashboard.alerts.map((a: any) => {
    const sev = a.severity;
    const color = sev === 'critical' ? 'var(--critical)' : sev === 'warning' ? 'var(--high)' : 'var(--text-dim)';
    const bg = sev === 'critical' ? 'var(--critical-bg)' : sev === 'warning' ? 'var(--high-bg)' : 'var(--surface-2)';
    return `
      <div class="alert-item" style="border-left:3px solid ${color};background:${bg}">
        <span class="alert-sev" style="color:${color}">${escapeHtml(sev.toUpperCase())}</span>
        <span class="alert-metric">${escapeHtml(a.metricName)}</span>
        <span class="alert-msg">${escapeHtml(a.message)}</span>
      </div>`;
  }).join('\n');
}

function generateFindingsTable(findings: Finding[]): string {
  if (findings.length === 0) return '';
  const sevColor = (s: string) => {
    const lc = s.toLowerCase();
    if (lc === 'critical') return { fg: 'var(--critical)', bg: 'var(--critical-bg)', bd: 'var(--critical-border)' };
    if (lc === 'high') return { fg: 'var(--high)', bg: 'var(--high-bg)', bd: 'var(--high-border)' };
    return { fg: 'var(--text-dim)', bg: 'var(--surface-2)', bd: 'var(--border)' };
  };

  const rows = findings.map(f => {
    const c = sevColor(f.severity);
    const statusHtml = f.status === 'Fixed'
      ? '<span class="status-fixed">Fixed</span>'
      : `<span style="color:var(--text-muted)">${escapeHtml(f.status ?? 'Open')}</span>`;
    return `
        <tr>
          <td><span class="finding-id">${escapeHtml(f.id)}</span></td>
          <td><span class="severity" style="color:${c.fg};background:${c.bg};border:1px solid ${c.bd}">${escapeHtml(f.severity)}</span></td>
          <td class="finding-desc">${escapeHtml(f.title)}${f.description ? ' &mdash; ' + escapeHtml(f.description) : ''}</td>
          <td><span class="file-path">${escapeHtml(f.file ?? '')}</span></td>
          <td>${statusHtml}</td>
        </tr>`;
  }).join('\n');

  return `
    <div class="section animate delay-3">
      <div class="section-header">
        <h2>Findings</h2>
        <span class="count">${findings.length} items</span>
      </div>
      <table class="findings-table">
        <thead><tr><th>ID</th><th>Severity</th><th>Finding</th><th>File</th><th>Status</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function generateCommitTimeline(commits: Commit[]): string {
  if (commits.length === 0) return '';
  const items = commits.map(c => `
      <div class="commit">
        <span class="commit-hash">${escapeHtml(c.hash.slice(0, 7))}</span>
        <span class="commit-msg">${escapeHtml(c.message)}</span>
        ${c.tag ? `<span class="commit-tag">${escapeHtml(c.tag)}</span>` : '<span></span>'}
        ${c.review ? `<span class="review-pass">${escapeHtml(c.review)}</span>` : '<span></span>'}
      </div>`).join('\n');

  return `
    <div class="section animate delay-4">
      <div class="section-header">
        <h2>Commit Timeline</h2>
        <span class="count">${commits.length} commits</span>
      </div>
      <div class="timeline">${items}</div>
    </div>`;
}

function generateHtml(
  metrics: SessionMetrics,
  evalAggs: EvalAgg[],
  dashboard: any,
  findings: Finding[],
  commits: Commit[],
  title: string,
  date: string,
): string {
  const overallScore = dashboard.summary && dashboard.summary.totalMetrics > 0
    ? Math.round(10 * dashboard.summary.healthyMetrics / dashboard.summary.totalMetrics)
    : 0;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)} — ${date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface-2: #1a1a26;
    --surface-3: #22222f;
    --border: #2a2a3a;
    --border-bright: #3a3a50;
    --text: #e4e4ef;
    --text-dim: #8888a0;
    --text-muted: #555570;
    --accent: #7b61ff;
    --accent-glow: rgba(123, 97, 255, 0.15);
    --critical: #ff3b5c;
    --critical-bg: rgba(255, 59, 92, 0.08);
    --critical-border: rgba(255, 59, 92, 0.25);
    --high: #ff9f1c;
    --high-bg: rgba(255, 159, 28, 0.08);
    --high-border: rgba(255, 159, 28, 0.25);
    --success: #22d97f;
    --success-bg: rgba(34, 217, 127, 0.08);
    --success-border: rgba(34, 217, 127, 0.25);
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Space Grotesk', sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text); font-family: var(--sans);
    min-height: 100vh; overflow-x: hidden;
  }
  body::before {
    content: ''; position: fixed; top: -200px; left: 50%; transform: translateX(-50%);
    width: 800px; height: 500px;
    background: radial-gradient(ellipse, rgba(123, 97, 255, 0.06) 0%, transparent 70%);
    pointer-events: none; z-index: 0;
  }
  .container { max-width: 1320px; margin: 0 auto; padding: 40px 32px; position: relative; z-index: 1; }

  /* Header */
  .header { display: flex; align-items: flex-end; justify-content: space-between;
    margin-bottom: 40px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
  .header-left h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 4px; }
  .header-left .subtitle { font-family: var(--mono); font-size: 13px; color: var(--text-dim); }
  .score-badge { display: flex; align-items: center; gap: 16px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px; padding: 16px 24px; }
  .score-ring { width: 64px; height: 64px; position: relative; }
  .score-ring svg { transform: rotate(-90deg); width: 64px; height: 64px; }
  .score-ring .track { fill: none; stroke: var(--surface-3); stroke-width: 5; }
  .score-ring .fill { fill: none; stroke: var(--accent); stroke-width: 5; stroke-linecap: round;
    stroke-dasharray: 163.36; stroke-dashoffset: 163.36;
    transition: stroke-dashoffset 1.5s cubic-bezier(0.4, 0, 0.2, 1); }
  .score-ring .value { position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; font-family: var(--mono); font-size: 20px; font-weight: 700; }
  .score-meta { display: flex; flex-direction: column; gap: 2px; }
  .score-meta .label { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: var(--text-muted); }
  .score-meta .detail { font-size: 14px; color: var(--text-dim); }

  /* Metrics strip */
  .metrics { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 32px; }
  .metric-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px; position: relative; overflow: hidden; }
  .metric-card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; }
  .metric-card.critical::after { background: var(--critical); }
  .metric-card.high::after { background: var(--high); }
  .metric-card.success::after { background: var(--success); }
  .metric-card.accent::after { background: var(--accent); }
  .metric-card .number { font-family: var(--mono); font-size: 28px; font-weight: 700; line-height: 1; margin-bottom: 4px; }
  .metric-card.critical .number { color: var(--critical); }
  .metric-card.high .number { color: var(--high); }
  .metric-card.success .number { color: var(--success); }
  .metric-card.accent .number { color: var(--accent); }
  .metric-card .label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); }

  /* Section */
  .section { margin-bottom: 32px; }
  .section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
  .section-header h2 { font-size: 16px; font-weight: 600; letter-spacing: -0.2px; }
  .section-header .count { font-family: var(--mono); font-size: 12px; color: var(--text-muted);
    background: var(--surface-2); padding: 2px 8px; border-radius: 4px; }

  /* Two-column layout */
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 32px; }

  /* Quality Scorecard */
  .scorecard { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
  .scorecard-row { display: grid; grid-template-columns: 140px 1fr 60px 40px 70px; align-items: center;
    gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); }
  .scorecard-row:last-child { border-bottom: none; }
  .scorecard-name { font-size: 13px; color: var(--text); }
  .scorecard-bar-track { height: 5px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
  .scorecard-bar-fill { height: 100%; border-radius: 3px; transition: width 1s cubic-bezier(0.4, 0, 0.2, 1); width: 0; }
  .scorecard-value { font-family: var(--mono); font-size: 13px; font-weight: 600; text-align: right; }
  .scorecard-count { font-family: var(--mono); font-size: 11px; color: var(--text-muted); text-align: center; }
  .scorecard-status { font-family: var(--mono); font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.5px; padding: 2px 6px; border-radius: 3px; text-align: center; }

  /* Token usage */
  .token-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .token-card { background: var(--surface-2); border-radius: 8px; padding: 14px; }
  .token-card .token-val { font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--accent); }
  .token-card .token-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--text-muted); margin-top: 2px; }

  /* Tool breakdown */
  .tool-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
  .tool-row { display: grid; grid-template-columns: 180px 1fr 50px; align-items: center; gap: 8px;
    padding: 5px 0; border-bottom: 1px solid var(--border); }
  .tool-row:last-child { border-bottom: none; }
  .tool-name { font-family: var(--mono); font-size: 12px; color: var(--text-dim);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tool-bar-track { height: 4px; background: var(--surface-3); border-radius: 2px; overflow: hidden; }
  .tool-bar-fill { display: block; height: 100%; border-radius: 2px; background: var(--success);
    transition: width 1s ease; width: 0; }
  .tool-count { font-family: var(--mono); font-size: 11px; color: var(--text-muted); text-align: right; }

  /* Alerts */
  .alerts-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
  .alert-item { padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;
    display: grid; grid-template-columns: 60px 120px 1fr; align-items: center; gap: 8px; }
  .alert-item:last-child { margin-bottom: 0; }
  .alert-sev { font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
  .alert-metric { font-family: var(--mono); font-size: 12px; color: var(--text-dim); }
  .alert-msg { font-size: 13px; color: var(--text); }
  .no-alerts { font-size: 13px; color: var(--text-muted); font-style: italic; padding: 12px 0; }

  /* Findings table */
  .findings-table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .findings-table th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--text-muted); padding: 12px 18px; background: var(--surface-2); border-bottom: 1px solid var(--border); }
  .findings-table td { padding: 14px 18px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: top; }
  .findings-table tr:last-child td { border-bottom: none; }
  .findings-table tr:hover td { background: var(--surface-2); }
  .finding-id { font-family: var(--mono); font-weight: 600; font-size: 13px; white-space: nowrap; }
  .severity { display: inline-flex; align-items: center; font-family: var(--mono); font-size: 10px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; padding: 3px 8px; border-radius: 4px; }
  .status-fixed { display: inline-flex; font-family: var(--mono); font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.8px; padding: 3px 8px; border-radius: 4px;
    color: var(--success); background: var(--success-bg); border: 1px solid var(--success-border); }
  .file-path { font-family: var(--mono); font-size: 11px; color: var(--text-dim); }
  .finding-desc { color: var(--text); line-height: 1.5; }

  /* Timeline */
  .timeline { position: relative; padding-left: 28px; }
  .timeline::before { content: ''; position: absolute; left: 7px; top: 8px; bottom: 8px;
    width: 1px; background: var(--border); }
  .commit { position: relative; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 18px; margin-bottom: 8px;
    display: grid; grid-template-columns: 72px 1fr auto auto; align-items: center; gap: 14px;
    transition: border-color 0.2s; }
  .commit:hover { border-color: var(--border-bright); }
  .commit::before { content: ''; position: absolute; left: -24px; top: 50%; transform: translateY(-50%);
    width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
    border: 2px solid var(--bg); box-shadow: 0 0 0 1px var(--accent); }
  .commit-hash { font-family: var(--mono); font-size: 13px; font-weight: 500; color: var(--accent); }
  .commit-msg { font-size: 13px; color: var(--text); }
  .commit-tag { font-family: var(--mono); font-size: 11px; padding: 3px 8px; border-radius: 4px;
    background: var(--surface-3); color: var(--text-dim); white-space: nowrap; }
  .review-pass { font-family: var(--mono); font-size: 11px; padding: 3px 8px; border-radius: 4px;
    color: var(--success); background: var(--success-bg); border: 1px solid var(--success-border); white-space: nowrap; }

  /* Footer */
  .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center; }
  .footer-left { font-family: var(--mono); font-size: 12px; color: var(--text-muted); }
  .footer-right { font-size: 12px; color: var(--text-muted); }

  /* Animations */
  @keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
  .animate { opacity: 0; animation: fadeUp 0.5s ease forwards; }
  .delay-1 { animation-delay: 0.1s; } .delay-2 { animation-delay: 0.2s; }
  .delay-3 { animation-delay: 0.3s; } .delay-4 { animation-delay: 0.4s; }
  .delay-5 { animation-delay: 0.5s; } .delay-6 { animation-delay: 0.6s; }

  @media (max-width: 960px) {
    .metrics { grid-template-columns: repeat(3, 1fr); }
    .two-col { grid-template-columns: 1fr; }
    .commit { grid-template-columns: 1fr; gap: 6px; }
    .header { flex-direction: column; align-items: flex-start; gap: 16px; }
  }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header animate">
    <div class="header-left">
      <h1>${escapeHtml(title)}</h1>
      <div class="subtitle">session ${escapeHtml(metrics.sessionId.slice(0, 8))} &mdash; ${date} &mdash; ${metrics.totalSpans} spans</div>
    </div>
    <div class="score-badge">
      <div class="score-ring">
        <svg viewBox="0 0 64 64">
          <circle class="track" cx="32" cy="32" r="26"/>
          <circle class="fill" id="scoreArc" cx="32" cy="32" r="26"/>
        </svg>
        <div class="value">${overallScore}<span style="font-size:12px;color:var(--text-muted)">/10</span></div>
      </div>
      <div class="score-meta">
        <div class="label">Quality Score</div>
        <div class="detail">${escapeHtml(dashboard.overallStatus ?? 'no_data')}</div>
      </div>
    </div>
  </div>

  <!-- Metrics strip -->
  <div class="metrics animate delay-1">
    <div class="metric-card accent">
      <div class="number">${metrics.totalSpans}</div>
      <div class="label">Spans</div>
    </div>
    <div class="metric-card success">
      <div class="number">${metrics.toolSuccess}/${metrics.toolSpans}</div>
      <div class="label">Tool Calls</div>
    </div>
    <div class="metric-card ${metrics.toolCorrectness !== null && metrics.toolCorrectness >= 0.95 ? 'success' : 'high'}">
      <div class="number">${metrics.toolCorrectness !== null ? (metrics.toolCorrectness * 100).toFixed(1) + '%' : '--'}</div>
      <div class="label">Tool Accuracy</div>
    </div>
    <div class="metric-card accent">
      <div class="number">${fmtTokens(metrics.tokenTotal)}</div>
      <div class="label">Tokens</div>
    </div>
    <div class="metric-card ${metrics.taskCompletion !== null && metrics.taskCompletion >= 0.8 ? 'success' : 'high'}">
      <div class="number">${metrics.taskCompletion !== null ? (metrics.taskCompletion * 100).toFixed(0) + '%' : '--'}</div>
      <div class="label">Task Compl.</div>
    </div>
    <div class="metric-card accent">
      <div class="number">${Object.keys(metrics.agentBreakdown).length}</div>
      <div class="label">Agents</div>
    </div>
  </div>

  <!-- Quality Scorecard + Token Usage (two columns) -->
  <div class="two-col animate delay-2">
    <div>
      <div class="section-header">
        <h2>Quality Scorecard</h2>
        <span class="count">OTEL evaluations</span>
      </div>
      <div class="scorecard">
        <div class="scorecard-row" style="border-bottom:1px solid var(--border-bright)">
          <div class="scorecard-name" style="font-weight:600;color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:1px">Metric</div>
          <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px"></div>
          <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;text-align:right;font-family:var(--mono)">Avg</div>
          <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;text-align:center;font-family:var(--mono)">N</div>
          <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;text-align:center;font-family:var(--mono)">Status</div>
        </div>
        ${generateScorecardRows(evalAggs)}
      </div>
    </div>
    <div>
      <div class="section-header">
        <h2>Token Usage</h2>
        <span class="count">${fmtTokens(metrics.tokenTotal)} total</span>
      </div>
      <div class="scorecard" style="margin-bottom:16px">
        <div class="token-grid">
          <div class="token-card">
            <div class="token-val">${fmtTokens(metrics.tokenInput)}</div>
            <div class="token-label">Input</div>
          </div>
          <div class="token-card">
            <div class="token-val">${fmtTokens(metrics.tokenOutput)}</div>
            <div class="token-label">Output</div>
          </div>
          <div class="token-card">
            <div class="token-val">${fmtTokens(metrics.tokenCacheRead)}</div>
            <div class="token-label">Cache Read</div>
          </div>
          <div class="token-card">
            <div class="token-val">${metrics.evaluationLatencyMedian !== null ? metrics.evaluationLatencyMedian.toFixed(3) + 's' : '--'}</div>
            <div class="token-label">Median Latency</div>
          </div>
        </div>
      </div>

      <div class="section-header">
        <h2>Alerts</h2>
        <span class="count">${dashboard.alerts?.length ?? 0}</span>
      </div>
      <div class="alerts-panel">
        ${generateAlerts(dashboard)}
      </div>
    </div>
  </div>

  <!-- Tool Breakdown -->
  <div class="two-col animate delay-3">
    <div>
      <div class="section-header">
        <h2>Tool Breakdown</h2>
        <span class="count">${Object.keys(metrics.toolBreakdown).length} tools</span>
      </div>
      <div class="tool-panel">
        ${generateToolBreakdown(metrics.toolBreakdown)}
      </div>
    </div>
    <div>
      <div class="section-header">
        <h2>Hooks &amp; Agents</h2>
        <span class="count">${metrics.hooksUsed.length} hooks</span>
      </div>
      <div class="tool-panel">
        ${metrics.hooksUsed.map(h => `<div class="tool-row" style="grid-template-columns:1fr"><span class="tool-name">${escapeHtml(h)}</span></div>`).join('\n')}
        ${Object.entries(metrics.agentBreakdown).length > 0 ? '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">' +
          Object.entries(metrics.agentBreakdown).map(([type, count]) =>
            `<div class="tool-row" style="grid-template-columns:1fr 50px"><span class="tool-name">agent: ${escapeHtml(type)}</span><span class="tool-count">${count}</span></div>`
          ).join('\n') + '</div>' : ''}
      </div>
    </div>
  </div>

  <!-- Findings (if provided) -->
  ${generateFindingsTable(findings)}

  <!-- Commits (if provided) -->
  ${generateCommitTimeline(commits)}

  <!-- Footer -->
  <div class="footer animate delay-6">
    <div class="footer-left">session ${escapeHtml(metrics.sessionId.slice(0, 8))} &mdash; ${metrics.totalSpans} spans &mdash; ${metrics.toolSpans} tool calls</div>
    <div class="footer-right">Generated ${new Date().toISOString().slice(0, 19)} &mdash; observability-toolkit</div>
  </div>

</div>

<script>
  requestAnimationFrame(() => {
    setTimeout(() => {
      const arc = document.getElementById('scoreArc');
      const circumference = 2 * Math.PI * 26;
      arc.style.strokeDashoffset = circumference * (1 - ${overallScore} / 10);
    }, 400);
    setTimeout(() => {
      document.querySelectorAll('.scorecard-bar-fill, .tool-bar-fill').forEach(bar => {
        bar.style.width = bar.dataset.width + '%';
      });
    }, 600);
  });
</script>
</body>
</html>`;
}

// --- Main ---
async function main(): Promise<void> {
  await loadObsToolkit();
  console.log(`[generate-review-dashboard] Date: ${dateFilter}`);

  // Resolve session
  const sid = sessionId ?? findLatestSessionId();
  if (!sid) {
    console.error('[generate-review-dashboard] No session found in telemetry');
    process.exit(1);
  }
  console.log(`[generate-review-dashboard] Session: ${sid.slice(0, 12)}...`);

  // Load traces
  const spans = loadTraces(sid);
  console.log(`[generate-review-dashboard] Loaded ${spans.length} spans`);

  if (spans.length === 0) {
    console.error('[generate-review-dashboard] No spans found for session');
    process.exit(1);
  }

  // Compute session metrics
  const metrics = computeSessionMetrics(spans);
  console.log(`[generate-review-dashboard] Tool calls: ${metrics.toolSpans} (${metrics.toolSuccess} ok, ${metrics.toolFailure} fail)`);
  console.log(`[generate-review-dashboard] Tokens: ${fmtTokens(metrics.tokenTotal)} (in:${fmtTokens(metrics.tokenInput)} out:${fmtTokens(metrics.tokenOutput)} cache:${fmtTokens(metrics.tokenCacheRead)})`);

  // Compute quality scorecard from evaluations
  const startDate = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const endDate = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const { dashboard, evalAggs } = await computeQualityScorecard(startDate, endDate);
  console.log(`[generate-review-dashboard] Quality metrics: ${evalAggs.length} (${evalAggs.map(e => e.name).join(', ')})`);
  console.log(`[generate-review-dashboard] Overall status: ${dashboard.overallStatus}`);

  // Load optional overlay data
  const findings: Finding[] = loadJson<Finding[]>(findingsPath) ?? [];
  const commits: Commit[] = loadJson<Commit[]>(commitsPath) ?? [];

  // Generate HTML
  const html = generateHtml(metrics, evalAggs, dashboard, findings, commits, dashTitle, dateFilter);
  writeFileSync(outputPath, html);
  console.log(`[generate-review-dashboard] Written: ${outputPath} (${(html.length / 1024).toFixed(1)} KB)`);
}

main().catch(err => {
  console.error('[generate-review-dashboard] Fatal:', err);
  process.exit(1);
});
