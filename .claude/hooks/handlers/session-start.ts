/**
 * Session Start Handler
 * Runs at the start of each Claude Code session
 */

import { instrumentHook, getTraceId } from '../lib/otel-monitor.js';
import { saveSessionContext, saveLastSessionId, loadLastSessionId } from '../lib/trace-context.js';
import { THRESHOLDS, SESSION_ATTRIBUTES } from '../lib/constants.js';
import { trackSessionContext } from '../lib/context-tracker.js';
import { loadTaskState, calculateTaskCompletion, getActiveTasks, cleanupOldTaskState } from '../lib/task-tracker.js';
import { resetFailureTracking } from './mcp-status.js';
import { resetAgentCache, resetHandlerFailureCounts } from './post-tool.js';
import { clearSession as clearAgentContext } from '../lib/agent-context.js';
import { loadJson } from '../lib/file-utils.js';
import { shouldSampleSession, cleanupOldFlags } from '../lib/quality-sampler.js';
import { execFile } from 'child_process';
import { promisify } from 'util';

// execFile (not exec) invokes git directly without a `/bin/sh -c` wrapper:
// removes 3 shell forks per session-start and the shell-injection surface.
const execFileAsync = promisify(execFile);
const GIT_EXEC_OPTS = { timeout: 15000, encoding: 'utf8', windowsHide: true } as const;
import * as fs from 'fs';
import * as path from 'path';

// 5s TTL cache for git status (keyed on cwd)
const GIT_CACHE_TTL_MS = 5000;
let gitCache: { cwd: string; ts: number; value: GitResult | null } | null = null;
type GitResult = { branch: string; uncommitted: number; repository?: string };

/** @internal Exported for testing only. */
export function resetGitCache(): void {
  gitCache = null;
}

interface HookInput {
  session_id?: string;
  transcript_path?: string;
  resume?: boolean;
}

export async function handleSessionStart(input: HookInput): Promise<void> {
  await instrumentHook('session-start', async (ctx) => {
    // Add session.id to span attributes for trace correlation
    if (input.session_id) {
      ctx.addAttribute(SESSION_ATTRIBUTES.SESSION_ID, input.session_id);
    }

    // Persist this span's context so all subsequent hooks in this session
    // can create child spans under the same traceId (W3C distributed tracing).
    if (input.session_id) {
      const traceId = getTraceId();
      const spanId = ctx.span.spanContext().spanId;
      if (traceId) saveSessionContext(input.session_id, traceId, spanId);
    }

    // OTEL5a — emit session-grouping attributes on the session-start span.
    //
    // integritystudio.project.slug is a vendor-prefixed grouping key derived
    // from the transcript path: a project contains MANY conversations, so the
    // slug groups sessions by project — it is NOT a conversation id, so it must
    // not occupy the standardized gen_ai.conversation.id name.
    const explicitConversationId = process.env['CLAUDE_CONVERSATION_ID'];
    const projectSlug = deriveProjectSlug(input.transcript_path);
    if (projectSlug) {
      ctx.addAttribute(SESSION_ATTRIBUTES.PROJECT_SLUG, projectSlug);
    }

    // gen_ai.conversation.id carries a GENUINE thread id only: an explicit
    // CLAUDE_CONVERSATION_ID override, else the provider-supplied session id.
    // It is never synthesized from a path, per the GenAI semantic conventions.
    const conversationId = explicitConversationId || input.session_id;
    if (conversationId) {
      ctx.addAttribute(SESSION_ATTRIBUTES.CONVERSATION_ID, conversationId);
    }

    // OTEL5b / OBP3 — emit the cross-session predecessor edge on the
    // session-start span. Standardized session.previous_id is dual-written with
    // the legacy preceded_by_session.id; both carry the prior session's id and
    // are only emitted when a prior session exists AND differs (spec MUST).
    const groupingKey = explicitConversationId || projectSlug;
    if (input.session_id && groupingKey) {
      const priorSessionId = loadLastSessionId(groupingKey);
      for (const [attrKey, attrValue] of predecessorSessionAttributes(priorSessionId, input.session_id)) {
        ctx.addAttribute(attrKey, attrValue);
      }
      saveLastSessionId(groupingKey, input.session_id);
    }

    ctx.logger.info('Session starting', { cwd: process.cwd(), [SESSION_ATTRIBUTES.SESSION_ID]: input.session_id });

    // Reset module-level state from prior sessions
    resetFailureTracking();
    resetAgentCache();
    resetHandlerFailureCounts();
    if (input.session_id) clearAgentContext(input.session_id);

    // T2: Quality evaluation sampling decision
    if (input.session_id) {
      const sampled = shouldSampleSession(input.session_id);
      ctx.addAttribute('quality.eval_sampled', sampled);
      // Defer cleanup off critical path — directory iteration + stat + rmSync is unbounded
      setImmediate(() => cleanupOldFlags(7));
    }

    console.log('Claude Code Session Starting');
    console.log('======================================');

    let checksPerformed = 0;

    // Track context at session start
    const contextData = trackSessionContext({
      sessionId: input.session_id || 'unknown',
      transcriptPath: input.transcript_path,
      isResume: input.resume || false,
      attributes: {
        'working.directory': process.cwd(),
      },
    });

    if (contextData) {
      ctx.addAttributes({
        'context.estimated_tokens': contextData.estimatedTokens,
        'context.utilization_percent': contextData.utilizationPercent,
        'context.free_space': contextData.freeSpace,
        'context.transcript_size': contextData.transcriptSize,
        'context.message_count': contextData.messageCount,
        'context.is_resume': contextData.isResume,
      });

      ctx.recordMetric('session.context_tokens', contextData.estimatedTokens);
      ctx.recordMetric('session.context_utilization', contextData.utilizationPercent);
      ctx.recordMetric('session.free_space', contextData.freeSpace);

      // Detect context overflow
      if (contextData.utilizationPercent > 100) {
        ctx.recordEvent('context.overflow', {
          'context.utilization_percent': contextData.utilizationPercent,
          'context.estimated_tokens': contextData.estimatedTokens,
        });
      }

      // Display context info if resuming or significant context
      if (contextData.isResume || contextData.estimatedTokens > 10000) {
        const utilBar = getUtilizationBar(contextData.utilizationPercent);
        console.log(`Context: ${formatTokens(contextData.estimatedTokens)} tokens (${contextData.utilizationPercent.toFixed(1)}%)`);
        console.log(`   Free: ${formatTokens(contextData.freeSpace)} tokens`);
        console.log(`   ${utilBar}`);
        checksPerformed++;
      }

      ctx.logger.debug('Context tracked', {
        'context.tokens': contextData.estimatedTokens,
        'context.utilization': contextData.utilizationPercent,
        'context.free_space': contextData.freeSpace,
      });
    }

    // Restore task state on resume (survives context compaction)
    if (input.resume && input.session_id) {
      const taskState = loadTaskState(input.session_id);
      if (taskState) {
        const active = getActiveTasks(taskState.tasks);
        if (active.length > 0) {
          const ratio = calculateTaskCompletion(taskState.tasks);
          ctx.addAttributes({
            'task.restored_count': active.length,
            'task.completion_ratio': ratio,
          });
          ctx.recordMetric('session.task_completion', ratio);
          console.log(`Tasks: ${active.length} restored (${(ratio * 100).toFixed(0)}% complete)`);
          if (ratio < THRESHOLDS.TASK_COMPLETION_RATIO) {
            console.log(`   [!] Low completion ratio: ${ratio.toFixed(2)}`);
          }
          checksPerformed++;
        }
      }

      // Garbage-collect state files older than 30 days
      cleanupOldTaskState(30);
    }

    // Parallelize slow I/O: node/npm and git run genuinely concurrently
    const checkNodeEnv = async () => {
      return { nodeVersion: process.version };
    };

    const checkGitStatus = async (): Promise<GitResult | null> => {
      const cwd = process.cwd();

      // Return cached result if fresh
      if (gitCache && gitCache.cwd === cwd && Date.now() - gitCache.ts < GIT_CACHE_TTL_MS) {
        return gitCache.value;
      }

      // Run all 3 git commands concurrently. A rejected promise (non-zero exit,
      // e.g. not a git repo or no `origin` remote) is handled via allSettled —
      // matching the prior `2>/dev/null` shell behavior of silently ignoring failures.
      const [branchResult, statusResult, remoteResult] = await Promise.allSettled([
        execFileAsync('git', ['branch', '--show-current'], GIT_EXEC_OPTS),
        execFileAsync('git', ['status', '--porcelain'], GIT_EXEC_OPTS),
        execFileAsync('git', ['remote', 'get-url', 'origin'], GIT_EXEC_OPTS),
      ]);

      const branch = branchResult.status === 'fulfilled'
        ? branchResult.value.stdout.trim() || undefined
        : undefined;
      if (!branch) {
        gitCache = { cwd, ts: Date.now(), value: null };
        return null;
      }

      let uncommitted = 0;
      if (statusResult.status === 'fulfilled') {
        uncommitted = statusResult.value.stdout.split('\n').filter((l) => l.trim()).length;
      }

      let repository: string | undefined;
      if (remoteResult.status === 'fulfilled') {
        const match = remoteResult.value.stdout.trim().match(/[/:]([\w.-]+\/[\w.-]+?)(?:\.git)?$/);
        if (match) repository = match[1];
      }

      const value = { branch, uncommitted, repository };
      gitCache = { cwd, ts: Date.now(), value };
      return value;
    };

    const [envResult, gitResult] = await Promise.allSettled([checkNodeEnv(), checkGitStatus()]);

    // Process node/npm result
    if (envResult.status === 'fulfilled') {
      const { nodeVersion } = envResult.value;
      console.log(`Node: ${nodeVersion}`);
      ctx.addAttribute('node.version', nodeVersion);
      ctx.logger.debug('Environment check passed', { 'node.version': nodeVersion });
      checksPerformed++;
    } else {
      ctx.logger.error('Node.js environment check failed', {
        error: envResult.reason instanceof Error ? envResult.reason.message : String(envResult.reason),
      });
    }

    // Current directory context
    const cwd = process.cwd();
    ctx.addAttribute('working.directory', cwd);

    const packageJsonPath = path.join(cwd, 'package.json');
    const pkg = loadJson<{ name?: string }>(packageJsonPath);
    if (pkg) {
      console.log(`Project: ${pkg.name || 'unknown'}`);
      ctx.addAttribute('project.name', pkg.name || 'unknown');
      checksPerformed++;
    }

    // Active tasks count
    const homeDir = process.env.HOME || process.env.USERPROFILE;
    const activeDir = process.env.ACTIVE_TASKS_DIR || (homeDir ? path.join(homeDir, 'dev', 'active') : null);
    if (activeDir && fs.existsSync(activeDir)) {
      const tasks = fs.readdirSync(activeDir);
      console.log(`Active tasks: ${tasks.length}`);
      ctx.addAttribute('tasks.active', tasks.length);
      ctx.recordMetric('session.active_tasks', tasks.length);

      if (tasks.length > 0) {
        console.log('   Tasks:');
        tasks.forEach((task) => console.log(`   - ${task}`));
      }
      checksPerformed++;
    }

    // Process git result
    if (gitResult.status === 'fulfilled' && gitResult.value) {
      const { branch, uncommitted, repository } = gitResult.value;
      ctx.addAttribute('vcs.ref.head.name', branch);
      ctx.addAttribute('integritystudio.git.uncommitted', uncommitted);
      if (repository) ctx.addAttribute('vcs.repository.name', repository);

      if (uncommitted > 0) {
        console.log(`Git: ${branch} (${uncommitted} uncommitted changes)`);
      } else {
        console.log(`Git: ${branch} (clean)`);
      }
      checksPerformed++;
    }
    // gitResult rejected = not in a git repo, silently ignore

    ctx.addAttribute('checks.performed', checksPerformed);
    ctx.recordMetric('session.checks', checksPerformed);

    console.log('');
    console.log('======================================');
    console.log('Ready to work!');
    console.log('');
  });
}

/**
 * Derive a stable project slug from the transcript path for use as the
 * integritystudio.project.slug grouping attribute.
 *
 * Claude Code stores transcripts at:
 *   ~/.claude/projects/{project-slug}/{session-id}.jsonl
 *
 * The project slug is the directory name immediately above the session JSONL file.
 * Falls back to null if transcript_path is absent or does not match the expected pattern.
 *
 * @internal Exported for testing only.
 */
export function deriveProjectSlug(transcriptPath: string | undefined): string | null {
  if (!transcriptPath) return null;
  // Match /{project-slug}/{uuid}.jsonl at the end of the path
  const match = transcriptPath.match(/\/([^/]+)\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.jsonl$/i);
  return match ? match[1] : null;
}

/**
 * Build predecessor-edge attributes for the session-start span.
 * Standardized `session.previous_id` (OTel, Development) is dual-written
 * alongside the legacy `preceded_by_session.id` during migration (OBP3).
 * Returns [] unless a prior session exists AND differs from the current one
 * (session.previous_id spec MUST: previous != current).
 */
export function predecessorSessionAttributes(
  priorSessionId: string | null,
  currentSessionId: string,
): Array<[string, string]> {
  if (!priorSessionId || priorSessionId === currentSessionId) return [];
  return [
    [SESSION_ATTRIBUTES.PREVIOUS_ID, priorSessionId],
    [SESSION_ATTRIBUTES.PRECEDED_BY_SESSION_ID, priorSessionId],
  ];
}

/**
 * Format token count for display (e.g., 150000 -> "150K")
 */
function formatTokens(tokens: number): string {
  if (tokens >= 1000000) {
    return `${(tokens / 1000000).toFixed(1)}M`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(0)}K`;
  }
  return String(tokens);
}

/**
 * Generate a visual utilization bar.
 * Clamps percent to 0-100 range to prevent RangeError from String.repeat()
 * with negative values (e.g., 172% utilization producing -14 empty chars).
 * @internal Exported for testing only.
 */
export function getUtilizationBar(percent: number): string {
  const width = 20;
  const safePct = Number.isFinite(percent) ? percent : 0;
  const clamped = Math.max(0, Math.min(100, safePct));
  const filled = Math.round((clamped / 100) * width);
  const empty = width - filled;

  let color = 'OK';
  if (safePct > 100) color = 'OVERFLOW';
  else if (safePct >= 70) color = 'HIGH';
  else if (safePct >= 50) color = 'WARN';

  if (safePct > 100) {
    console.error(`[OVERFLOW] Context utilization exceeded 100%: ${safePct.toFixed(1)}%`);
  }

  return `[${'\u2588'.repeat(filled)}${'\u2591'.repeat(empty)}] ${color}`;
}
