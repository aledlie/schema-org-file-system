import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock otel.js before importing the module under test
vi.mock('../../lib/otel.js', () => ({
  recordMetric: vi.fn(),
}));

// Mock heavy dependencies that post-tool.ts imports at module level
vi.mock('../../lib/otel-monitor.js', () => ({
  instrumentHook: vi.fn(),
}));
vi.mock('../../lib/constants.js', () => ({
  BUILTIN_TOOLS: new Set(),
}));
vi.mock('../../lib/file-utils.js', () => ({
  loadJsonSafe: vi.fn(() => ({})),
  ensureDirExists: vi.fn(),
  writeJson: vi.fn(),
}));
vi.mock('../../lib/categorizers.js', () => ({
  categorizeBuiltinTool: vi.fn(),
}));
vi.mock('../../lib/parsers.js', () => ({
  parseMcpToolName: vi.fn(),
}));
vi.mock('../../lib/output-analyzer.js', () => ({
  analyzeOutput: vi.fn(),
  analyzeBuiltinOutput: vi.fn(),
}));
vi.mock('../../lib/cache-tracker.js', () => ({
  trackInvocation: vi.fn(),
  getCacheDir: vi.fn(),
  ensureCacheDir: vi.fn(),
}));
vi.mock('../../lib/repo-utils.js', () => ({
  findTsRepoRoot: vi.fn(),
  findPyRepoRoot: vi.fn(),
  findProjectRoot: vi.fn(),
  getTscCommand: vi.fn(),
  getPyCheckCommand: vi.fn(),
}));
vi.mock('../../lib/mcp-config.js', () => ({
  getMcpScope: vi.fn(),
}));
vi.mock('../../lib/type-check-cache.js', () => ({
  TypeCheckCacheManager: vi.fn(),
}));
vi.mock('../mcp-status.js', () => ({
  handleMcpStatus: vi.fn(),
}));
vi.mock('../../lib/task-tracker.js', () => ({
  upsertTask: vi.fn(),
  generateTaskId: vi.fn(),
  loadTaskState: vi.fn(() => null),
}));
vi.mock('../../lib/exponential-backoff.js', () => ({
  isRateLimitError: vi.fn(),
}));
vi.mock('../../lib/mcp-completeness.js', () => ({
  recordMcpInvocation: vi.fn(),
}));

import { runHandlers, resetHandlerFailureCounts } from '../post-tool.js';
import { recordMetric } from '../../lib/otel.js';

describe('runHandlers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetHandlerFailureCounts();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('resolves when all handlers succeed', async () => {
    const result = await runHandlers('ok', Promise.resolve(), Promise.resolve());
    expect(result).toEqual({ failures: 0, total: 2, errors: [] });
  });

  it('resolves even when a handler rejects', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const result = await runHandlers('fail',
      Promise.resolve(),
      Promise.reject(new Error('boom')),
      Promise.resolve(),
    );
    expect(result.failures).toBe(1);
    expect(result.total).toBe(3);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toEqual({ index: 1, error: 'boom' });
  });

  it('runs all handlers even when one rejects early', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    let ran1 = false;
    let ran2 = false;
    let ran3 = false;

    const h1 = new Promise<void>(r => { ran1 = true; r(); });
    const h2 = new Promise<void>((_, reject) => { ran2 = true; reject(new Error('fail')); });
    const h3 = new Promise<void>(r => { ran3 = true; r(); });

    await runHandlers('test', h1, h2, h3);
    expect(ran1).toBe(true);
    expect(ran2).toBe(true);
    expect(ran3).toBe(true);
  });

  it('logs rejection with label and handler index', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await runHandlers('MyGroup',
      Promise.resolve(),
      Promise.reject(new Error('kaboom')),
    );
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining('Handler 1'),
      'kaboom',
    );
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining('"MyGroup"'),
      'kaboom',
    );
  });

  it('logs non-Error rejections correctly', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await runHandlers('str-reject',
      Promise.reject('string-error'),
    );
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining('Handler 0'),
      'string-error',
    );
  });

  it('records metric for each rejected handler', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    await runHandlers('metrics-group',
      Promise.reject(new Error('fail1')),
      Promise.resolve(),
      Promise.reject(new Error('fail2')),
    );
    expect(recordMetric).toHaveBeenCalledWith(
      'post_tool.handler_rejections', 1,
      expect.objectContaining({ group: 'metrics-group', handler_index: '0', error_type: 'Error' }),
    );
    expect(recordMetric).toHaveBeenCalledWith(
      'post_tool.handler_rejections', 1,
      expect.objectContaining({ group: 'metrics-group', handler_index: '2', error_type: 'Error' }),
    );
    expect(recordMetric).toHaveBeenCalledTimes(2);
  });

  it('handles empty handler list', async () => {
    const result = await runHandlers('empty');
    expect(result).toEqual({ failures: 0, total: 0, errors: [] });
  });

  it('opens circuit after cascade threshold exceeded (all handlers must fail)', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // Trigger 3 consecutive total-group failures (all handlers reject)
    for (let i = 0; i < 3; i++) {
      await runHandlers('cascade', Promise.reject(new Error(`fail${i}`)));
    }
    // 4th call should be skipped (circuit open)
    const result = await runHandlers('cascade', Promise.resolve());
    expect(result.failures).toBe(0);
    expect(recordMetric).toHaveBeenCalledWith(
      'post_tool.handler_circuit_open', 1,
      expect.objectContaining({ group: 'cascade' }),
    );
  });

  it('does not trip circuit on partial failures', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // Partial failures (1 of 2 handlers) should not increment counter
    for (let i = 0; i < 5; i++) {
      await runHandlers('partial', Promise.resolve(), Promise.reject(new Error(`fail${i}`)));
    }
    // Circuit should still be closed — partial failures reset counter
    const result = await runHandlers('partial', Promise.resolve(), Promise.resolve());
    expect(result.failures).toBe(0);
    expect(result.total).toBe(2);
  });

  it('resets circuit after success', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // 2 total failures, then success
    await runHandlers('reset-test', Promise.reject(new Error('fail1')));
    await runHandlers('reset-test', Promise.reject(new Error('fail2')));
    await runHandlers('reset-test', Promise.resolve());
    // Success resets counter, so next failure restarts count
    const result = await runHandlers('reset-test', Promise.reject(new Error('fail3')));
    expect(result.failures).toBe(1);
  });
});
