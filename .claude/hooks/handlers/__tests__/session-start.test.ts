/**
 * Tests for session-start handler helpers.
 */

import { describe, it, expect } from 'vitest';
import { deriveProjectSlug, getUtilizationBar, predecessorSessionAttributes } from '../session-start.js';
import { SESSION_ATTRIBUTES } from '../../lib/constants.js';

describe('deriveProjectSlug', () => {
  it('returns null for undefined input', () => {
    expect(deriveProjectSlug(undefined)).toBeNull();
  });

  it('extracts the project slug from a standard Claude transcript path', () => {
    const path =
      '/Users/alice/.claude/projects/-Users-alice-code-myproject/aabbccdd-1234-1234-1234-aabbccddeeff.jsonl';
    expect(deriveProjectSlug(path)).toBe('-Users-alice-code-myproject');
  });

  it('handles uppercase hex in session UUID', () => {
    const path =
      '/Users/alice/.claude/projects/my-project/AABBCCDD-1234-1234-1234-AABBCCDDEEFF.jsonl';
    expect(deriveProjectSlug(path)).toBe('my-project');
  });

  it('returns null when the path has no UUID segment', () => {
    expect(deriveProjectSlug('/Users/alice/.claude/projects/my-project/session.jsonl')).toBeNull();
  });

  it('returns null for an empty string', () => {
    expect(deriveProjectSlug('')).toBeNull();
  });

  it('returns null when the UUID segment is not at the expected position', () => {
    // UUID is in the middle, not immediately before .jsonl
    const path =
      '/Users/alice/.claude/aabbccdd-1234-1234-1234-aabbccddeeff/projects/other.jsonl';
    expect(deriveProjectSlug(path)).toBeNull();
  });

  it('handles a minimal valid path', () => {
    const path = '/a/project-slug/11111111-2222-3333-4444-555555555555.jsonl';
    expect(deriveProjectSlug(path)).toBe('project-slug');
  });
});

describe('getUtilizationBar', () => {
  it('returns OK label for low utilization', () => {
    expect(getUtilizationBar(30)).toContain('OK');
  });

  it('returns WARN label at 50%', () => {
    expect(getUtilizationBar(50)).toContain('WARN');
  });

  it('returns HIGH label at 70%', () => {
    expect(getUtilizationBar(70)).toContain('HIGH');
  });

  it('returns OVERFLOW label above 100%', () => {
    expect(getUtilizationBar(101)).toContain('OVERFLOW');
  });

  it('handles non-finite input gracefully', () => {
    expect(() => getUtilizationBar(NaN)).not.toThrow();
    expect(() => getUtilizationBar(Infinity)).not.toThrow();
  });
});

describe('predecessorSessionAttributes', () => {
  const current = 'cccccccc-1111-2222-3333-444444444444';

  it('returns [] when there is no prior session', () => {
    expect(predecessorSessionAttributes(null, current)).toEqual([]);
  });

  it('returns [] when prior === current (spec MUST: previous != current)', () => {
    expect(predecessorSessionAttributes(current, current)).toEqual([]);
  });

  it('dual-writes both keys when prior differs from current', () => {
    const prior = 'aaaaaaaa-1111-2222-3333-444444444444';
    const attrs = predecessorSessionAttributes(prior, current);

    expect(attrs).toHaveLength(2);
    expect(attrs).toContainEqual([SESSION_ATTRIBUTES.PREVIOUS_ID, prior]);
    expect(attrs).toContainEqual([SESSION_ATTRIBUTES.PRECEDED_BY_SESSION_ID, prior]);
  });

  it('pins the standardized session.previous_id key string', () => {
    expect(SESSION_ATTRIBUTES.PREVIOUS_ID).toBe('session.previous_id');
  });
});
