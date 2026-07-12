import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import {
  fmtTokens,
  statusBadge,
  bar,
  parseSpanTs,
  getToolSpans,
  loadTracesLocal,
  findLatestSessionId,
  extractMetrics,
} from './summarize_session.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SESSION_A = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const SESSION_B = '11111111-2222-3333-4444-555555555555';

type SpanAttrs = Record<string, unknown>;

function makeSpan(name: string, attrs: SpanAttrs = {}, extra: Record<string, unknown> = {}) {
  return { name, attributes: { 'session.id': SESSION_A, ...attrs }, ...extra };
}

function writeJsonl(dir: string, filename: string, spans: unknown[]): void {
  writeFileSync(join(dir, filename), spans.map(s => JSON.stringify(s)).join('\n') + '\n');
}

function makeTelemetryDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'otel-test-'));
  return dir;
}

// ---------------------------------------------------------------------------
// fmtTokens
// ---------------------------------------------------------------------------

describe('fmtTokens', () => {
  it('formats millions', () => expect(fmtTokens(1_500_000)).toBe('1.5M'));
  it('formats exactly 1M', () => expect(fmtTokens(1_000_000)).toBe('1.0M'));
  it('formats thousands', () => expect(fmtTokens(12_500)).toBe('12.5k'));
  it('formats exactly 1k', () => expect(fmtTokens(1_000)).toBe('1.0k'));
  it('formats small numbers', () => expect(fmtTokens(500)).toBe('500'));
  it('formats zero', () => expect(fmtTokens(0)).toBe('0'));
  it('formats 999', () => expect(fmtTokens(999)).toBe('999'));
});

// ---------------------------------------------------------------------------
// statusBadge
// ---------------------------------------------------------------------------

describe('statusBadge', () => {
  it('returns n/a for null value', () => expect(statusBadge('tool_correctness', null)).toBe('n/a'));
  it('returns n/a for unknown metric', () => expect(statusBadge('unknown', 0.5)).toBe('n/a'));

  describe('tool_correctness', () => {
    it('healthy at >= 0.95', () => expect(statusBadge('tool_correctness', 0.95)).toBe('healthy'));
    it('healthy above threshold', () => expect(statusBadge('tool_correctness', 1.0)).toBe('healthy'));
    it('warning at 0.90-0.95', () => expect(statusBadge('tool_correctness', 0.92)).toBe('warning'));
    it('warning at exactly 0.90', () => expect(statusBadge('tool_correctness', 0.90)).toBe('warning'));
    it('critical below 0.90', () => expect(statusBadge('tool_correctness', 0.85)).toBe('critical'));
  });

  describe('eval_latency', () => {
    it('healthy at <= 1.0s', () => expect(statusBadge('eval_latency', 1.0)).toBe('healthy'));
    it('healthy below 1s', () => expect(statusBadge('eval_latency', 0.5)).toBe('healthy'));
    it('warning at 1s-5s', () => expect(statusBadge('eval_latency', 3.0)).toBe('warning'));
    it('warning at exactly 5s', () => expect(statusBadge('eval_latency', 5.0)).toBe('warning'));
    it('critical above 5s', () => expect(statusBadge('eval_latency', 6.0)).toBe('critical'));
  });

  describe('task_completion', () => {
    it('healthy at >= 0.9', () => expect(statusBadge('task_completion', 0.9)).toBe('healthy'));
    it('healthy above threshold', () => expect(statusBadge('task_completion', 1.0)).toBe('healthy'));
    it('warning at 0.7-0.9', () => expect(statusBadge('task_completion', 0.75)).toBe('warning'));
    it('warning at exactly 0.7', () => expect(statusBadge('task_completion', 0.7)).toBe('warning'));
    it('critical below 0.7', () => expect(statusBadge('task_completion', 0.5)).toBe('critical'));
  });
});

// ---------------------------------------------------------------------------
// bar
// ---------------------------------------------------------------------------

describe('bar', () => {
  it('returns question marks for null', () => expect(bar(null)).toBe('?'.repeat(20)));
  it('full bar at 1.0', () => expect(bar(1.0)).toBe('\u2588'.repeat(20)));
  it('empty bar at 0.0', () => expect(bar(0.0)).toBe('\u2591'.repeat(20)));
  it('half filled at 0.5', () => {
    const result = bar(0.5);
    expect(result).toHaveLength(20);
    expect(result.split('\u2588').length - 1).toBe(10);
  });
  it('clamps values above 1.0', () => expect(bar(2.0)).toBe('\u2588'.repeat(20)));
  it('clamps values below 0.0', () => expect(bar(-0.5)).toBe('\u2591'.repeat(20)));
  it('respects custom width', () => expect(bar(0.5, 10)).toHaveLength(10));
  it('always returns exactly width characters', () => {
    for (const v of [0, 0.1, 0.33, 0.5, 0.75, 1.0]) {
      expect(bar(v, 20)).toHaveLength(20);
    }
  });
});

// ---------------------------------------------------------------------------
// parseSpanTs
// ---------------------------------------------------------------------------

describe('parseSpanTs', () => {
  it('reads startTimeUnixNano integer', () => {
    expect(parseSpanTs({ startTimeUnixNano: 1_700_000_000_000_000_000 })).toBe(1_700_000_000_000_000_000);
  });

  it('reads start_time_unix_nano integer', () => {
    expect(parseSpanTs({ start_time_unix_nano: 1_600_000_000_000_000_000 })).toBe(1_600_000_000_000_000_000);
  });

  it('prefers startTimeUnixNano over start_time_unix_nano', () => {
    expect(parseSpanTs({ startTimeUnixNano: 999, start_time_unix_nano: 111 })).toBe(999);
  });

  it('reads startTime [secs, nanos] array', () => {
    expect(parseSpanTs({ startTime: [1_700_000_000, 500_000_000] })).toBe(1_700_000_000_500_000_000);
  });

  it('reads startTime [secs] array (no nanos)', () => {
    expect(parseSpanTs({ startTime: [1_700_000_000] })).toBe(1_700_000_000_000_000_000);
  });

  it('returns 0 when no timestamp fields present', () => {
    expect(parseSpanTs({ name: 'hook:x', attributes: {} })).toBe(0);
  });

  it('returns 0 for empty object', () => {
    expect(parseSpanTs({})).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// getToolSpans
// ---------------------------------------------------------------------------

describe('getToolSpans', () => {
  it('includes hook:builtin-post-tool spans', () => {
    const spans = [makeSpan('hook:builtin-post-tool'), makeSpan('hook:session-start')];
    expect(getToolSpans(spans)).toHaveLength(1);
  });

  it('includes hook:mcp-post-tool spans', () => {
    const spans = [makeSpan('hook:mcp-post-tool'), makeSpan('hook:pre-tool')];
    expect(getToolSpans(spans)).toHaveLength(1);
  });

  it('excludes all other span types', () => {
    const spans = [
      makeSpan('hook:session-start'),
      makeSpan('hook:token-metrics-extraction'),
      makeSpan('hook:code-structure'),
    ];
    expect(getToolSpans(spans)).toHaveLength(0);
  });

  it('returns empty array for empty input', () => {
    expect(getToolSpans([])).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// loadTraces (file I/O)
// ---------------------------------------------------------------------------

describe('loadTracesLocal', () => {
  let dir: string;

  beforeEach(() => { dir = makeTelemetryDir(); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it('loads spans matching session ID', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      makeSpan('hook:session-start'),
      makeSpan('hook:builtin-post-tool'),
    ]);
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(2);
  });

  it('excludes spans from other sessions', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      makeSpan('hook:session-start'),
      { name: 'hook:session-start', attributes: { 'session.id': SESSION_B } },
    ]);
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(1);
  });

  it('handles corrupt JSON lines gracefully', () => {
    writeFileSync(join(dir, 'traces-2026-01-01.jsonl'), 'not json\n{bad\n');
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(0);
  });

  it('returns empty array for missing directory', () => {
    expect(loadTracesLocal(SESSION_A, '/nonexistent/path/xyz')).toHaveLength(0);
  });

  it('returns empty array for empty directory', () => {
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(0);
  });

  it('aggregates spans across multiple files', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [makeSpan('hook:session-start')]);
    writeJsonl(dir, 'traces-2026-01-02.jsonl', [makeSpan('hook:builtin-post-tool')]);
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(2);
  });

  it('only reads files matching traces-*.jsonl pattern', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [makeSpan('hook:session-start')]);
    writeJsonl(dir, 'other-file.jsonl', [makeSpan('hook:session-start')]);
    expect(loadTracesLocal(SESSION_A, dir)).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// findLatestSessionId
// ---------------------------------------------------------------------------

describe('findLatestSessionId', () => {
  let dir: string;

  beforeEach(() => { dir = makeTelemetryDir(); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it('returns null for empty directory', () => {
    expect(findLatestSessionId(dir)).toBeNull();
  });

  it('finds session ID from valid spans', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      makeSpan('hook:session-start', {}, { startTime: [1_700_000_000, 0] }),
    ]);
    expect(findLatestSessionId(dir)).toBe(SESSION_A);
  });

  it('rejects session.id = "default"', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      { name: 'hook:stop', attributes: { 'session.id': 'default' }, startTime: [1_700_000_000, 0] },
    ]);
    expect(findLatestSessionId(dir)).toBeNull();
  });

  it('rejects empty session.id', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      { name: 'hook:stop', attributes: { 'session.id': '' }, startTime: [1_700_000_000, 0] },
    ]);
    expect(findLatestSessionId(dir)).toBeNull();
  });

  it('picks the session with the highest timestamp', () => {
    // Two sessions in one file; SESSION_B has a later timestamp
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      makeSpan('hook:session-start', {}, { startTime: [1_000, 0] }),
      { name: 'hook:session-start', attributes: { 'session.id': SESSION_B }, startTime: [2_000, 0] },
    ]);
    expect(findLatestSessionId(dir)).toBe(SESSION_B);
  });

  it('searches all span types, not just session-start', () => {
    writeJsonl(dir, 'traces-2026-01-01.jsonl', [
      makeSpan('hook:builtin-post-tool', {}, { startTime: [1_700_000_000, 0] }),
    ]);
    expect(findLatestSessionId(dir)).toBe(SESSION_A);
  });

  it('handles corrupt JSON lines without crashing', () => {
    writeFileSync(join(dir, 'traces-2026-01-01.jsonl'), 'not json\n' + JSON.stringify(makeSpan('hook:x', {}, { startTime: [1_700_000_000, 0] })) + '\n');
    expect(findLatestSessionId(dir)).toBe(SESSION_A);
  });
});

// ---------------------------------------------------------------------------
// extractMetrics
// ---------------------------------------------------------------------------

describe('extractMetrics', () => {
  it('returns null metrics for empty traces', () => {
    const m = extractMetrics([]);
    expect(m.total_spans).toBe(0);
    expect(m.tool_correctness).toBeNull();
    expect(m.eval_latency).toBeNull();
    expect(m.task_completion).toBeNull();
    expect(m.files_touched).toEqual([]);
    expect(m.avg_code_structure).toBeNull();
  });

  it('counts total spans', () => {
    const traces = [makeSpan('hook:a'), makeSpan('hook:b'), makeSpan('hook:c')];
    expect(extractMetrics(traces).total_spans).toBe(3);
  });

  it('counts unique hooks', () => {
    const traces = [makeSpan('hook:a'), makeSpan('hook:a'), makeSpan('hook:b')];
    expect(extractMetrics(traces).unique_hooks).toBe(2);
  });

  describe('tool_correctness', () => {
    it('is null when no tool spans', () => {
      expect(extractMetrics([makeSpan('hook:session-start')]).tool_correctness).toBeNull();
    });

    it('is 1.0 when all tool spans succeed', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.success': true }),
      ];
      expect(extractMetrics(traces).tool_correctness).toBe(1.0);
    });

    it('is 0.5 when half fail', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.success': false }),
      ];
      expect(extractMetrics(traces).tool_correctness).toBe(0.5);
    });

    it('reads mcp.success for mcp spans', () => {
      const traces = [makeSpan('hook:mcp-post-tool', { 'mcp.success': true })];
      expect(extractMetrics(traces).tool_correctness).toBe(1.0);
    });
  });

  describe('eval_latency', () => {
    it('computes median duration from [secs, nanos] pairs', () => {
      const traces = [
        makeSpan('hook:a', {}, { duration: [2, 0] }),
        makeSpan('hook:b', {}, { duration: [0, 500_000_000] }),
      ];
      // median of [2.0, 0.5] = 1.25
      expect(extractMetrics(traces).eval_latency).toBeCloseTo(1.25);
    });

    it('computes median of odd count', () => {
      const traces = [
        makeSpan('hook:a', {}, { duration: [1, 0] }),
        makeSpan('hook:b', {}, { duration: [3, 0] }),
        makeSpan('hook:c', {}, { duration: [5, 0] }),
      ];
      expect(extractMetrics(traces).eval_latency).toBe(3.0);
    });

    it('skips durations that are not length-2 arrays', () => {
      const traces = [
        makeSpan('hook:a', {}, { duration: [1, 0] }),
        makeSpan('hook:b', {}, { duration: [3] }), // length 1 — skipped
      ];
      expect(extractMetrics(traces).eval_latency).toBe(1.0);
    });

    it('skips durations with non-numeric values', () => {
      const traces = [
        makeSpan('hook:a', {}, { duration: [1, 0] }),
        makeSpan('hook:b', {}, { duration: ['bad', 'data'] }),
      ];
      expect(extractMetrics(traces).eval_latency).toBe(1.0);
    });

    it('is null when no spans have duration', () => {
      expect(extractMetrics([makeSpan('hook:a')]).eval_latency).toBeNull();
    });
  });

  describe('task_completion', () => {
    it('is null when no TaskCreate spans', () => {
      expect(extractMetrics([makeSpan('hook:session-start')]).task_completion).toBeNull();
    });

    it('is 1.0 when all tasks completed', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'TaskCreate', 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'TaskUpdate', 'builtin.task_status': 'completed', 'builtin.success': true }),
      ];
      expect(extractMetrics(traces).task_completion).toBe(1.0);
    });

    it('is 0.0 when no tasks completed', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'TaskCreate', 'builtin.success': true }),
      ];
      expect(extractMetrics(traces).task_completion).toBe(0.0);
    });
  });

  describe('tokens', () => {
    it('aggregates token fields across token-metrics-extraction spans', () => {
      const traces = [
        makeSpan('hook:token-metrics-extraction', { 'tokens.input': 1000, 'tokens.output': 200, 'tokens.cache_read': 500, 'tokens.cache_creation': 100 }),
        makeSpan('hook:token-metrics-extraction', { 'tokens.input': 500, 'tokens.output': 100, 'tokens.cache_read': 250, 'tokens.cache_creation': 50 }),
      ];
      const { tokens } = extractMetrics(traces);
      expect(tokens.input).toBe(1500);
      expect(tokens.output).toBe(300);
      expect(tokens.cache_read).toBe(750);
      expect(tokens.cache_create).toBe(150);
      expect(tokens.total).toBe(1800); // input + output only
    });

    it('is all zeros with no token spans', () => {
      const { tokens } = extractMetrics([makeSpan('hook:session-start')]);
      expect(tokens.input).toBe(0);
      expect(tokens.output).toBe(0);
      expect(tokens.total).toBe(0);
    });
  });

  describe('files_touched', () => {
    it('collects file paths from Write spans', () => {
      const traces = [makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Write', 'builtin.file_path': '/tmp/a.ts', 'builtin.success': true })];
      expect(extractMetrics(traces).files_touched).toContain('/tmp/a.ts');
    });

    it('collects file paths from Edit spans', () => {
      const traces = [makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Edit', 'builtin.file_path': '/tmp/b.ts', 'builtin.success': true })];
      expect(extractMetrics(traces).files_touched).toContain('/tmp/b.ts');
    });

    it('collects file paths from MultiEdit spans', () => {
      const traces = [makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'MultiEdit', 'builtin.file_path': '/tmp/c.ts', 'builtin.success': true })];
      expect(extractMetrics(traces).files_touched).toContain('/tmp/c.ts');
    });

    it('deduplicates the same file edited multiple times', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Write', 'builtin.file_path': '/tmp/x.ts', 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Edit', 'builtin.file_path': '/tmp/x.ts', 'builtin.success': true }),
      ];
      expect(extractMetrics(traces).files_touched).toHaveLength(1);
    });

    it('returns files sorted alphabetically', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Write', 'builtin.file_path': '/tmp/z.ts', 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Write', 'builtin.file_path': '/tmp/a.ts', 'builtin.success': true }),
      ];
      const files = extractMetrics(traces).files_touched;
      expect(files[0]).toBe('/tmp/a.ts');
      expect(files[1]).toBe('/tmp/z.ts');
    });

    it('excludes Read/Bash spans from files_touched', () => {
      const traces = [
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Read', 'builtin.file_path': '/tmp/r.ts', 'builtin.success': true }),
        makeSpan('hook:builtin-post-tool', { 'builtin.tool': 'Bash', 'builtin.file_path': '/tmp/b.ts', 'builtin.success': true }),
      ];
      expect(extractMetrics(traces).files_touched).toHaveLength(0);
    });
  });

  describe('avg_code_structure', () => {
    it('averages code.structure.score across spans that have it', () => {
      const traces = [
        makeSpan('hook:code-structure', { 'code.structure.score': 0.8 }),
        makeSpan('hook:code-structure', { 'code.structure.score': 0.6 }),
      ];
      expect(extractMetrics(traces).avg_code_structure).toBeCloseTo(0.7);
    });

    it('is null when no spans have code.structure.score', () => {
      expect(extractMetrics([makeSpan('hook:session-start')]).avg_code_structure).toBeNull();
    });
  });

  describe('hook_counts', () => {
    it('sorted by most common first', () => {
      const traces = [
        makeSpan('hook:rare'),
        makeSpan('hook:common'),
        makeSpan('hook:common'),
        makeSpan('hook:common'),
      ];
      const keys = Object.keys(extractMetrics(traces).hook_counts);
      expect(keys[0]).toBe('hook:common');
      expect(keys[1]).toBe('hook:rare');
    });
  });
});
