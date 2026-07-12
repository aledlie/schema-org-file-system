/**
 * Post-Tool Handler
 * Unified handler for MCP, Plugin, Agent post-tool hooks and TSC check
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import { readFileSync, existsSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

import { BUILTIN_TOOLS, MCP_RESOURCE_TOOLS, THRESHOLDS, SPAN_ID_BYTES, getAgentSourceType, AGENT_LINK_ATTRIBUTES, AGENT_LINK_KIND_DISPATCH } from '../lib/constants.js';
import { loadJsonSafe, ensureDirExists, writeJson } from '../lib/file-utils.js';
import { categorizeBuiltinTool } from '../lib/categorizers.js';
import { parseMcpToolName } from '../lib/parsers.js';
import { analyzeOutput, analyzeBuiltinOutput } from '../lib/output-analyzer.js';
import { trackInvocation } from '../lib/cache-tracker.js';
import { findTsRepoRoot, findPyRepoRoot, findProjectRoot, getTscCommand, getPyCheckCommand } from '../lib/repo-utils.js';
import { getMcpScope } from '../lib/mcp-config.js';
import { TypeCheckCacheManager } from '../lib/type-check-cache.js';
import { handleMcpStatus } from './mcp-status.js';
import { handleChangelogVersionBump } from './post-tool-changelog-sync.js';
import { upsertTask, generateTaskId, loadTaskState, type TaskStatus } from '../lib/task-tracker.js';
import { isRateLimitError } from '../lib/exponential-backoff.js';
import { recordMcpInvocation } from '../lib/mcp-completeness.js';
import { recordMetric } from '../lib/otel.js';
import { emitToolCorrectness, emitCoherenceHeuristic, appendEvaluation } from '../lib/quality-signals.js';
import { popPendingAgent, getActiveAgentContext, addToolSpan, generateHex, getCreateAgentSpanId, consumeToolStartTime, type SynthSpan } from '../lib/agent-context.js';
import { submitSynthSpans } from '../lib/synth-spans.js';

/** Duration for synthetic instant-duration spans (e.g. create_agent) */
const SYNTH_INSTANT_SPAN_DURATION_MS = 1;

// Matches real agent error signals while excluding audit-report phrases like
// "Error rate", "error count", "has_error", "no error found/occurred".
// Arms: "error:", named exception types (TypeError:), runtime error verbs,
// and tsc parenthetical output (error TS\d+:).
const AGENT_ERROR_PATTERN =
  /(?:\berror:|\b[A-Za-z]+Error:|(?<!no )\berror\s+(?:occurred|detected|found|raised|thrown)\b|\berror\s+TS\d+:)/i;


export interface HandlerResult {
  failures: number;
  total: number;
  errors: Array<{ index: number; error: string }>;
}

// ER21: Per-group cascade failure tracking
const HANDLER_CASCADE_THRESHOLD = 3;
const handlerFailureCounts = new Map<string, number>();

// M5: module-scope constant — avoids recreating Set on every TaskCreate/TaskUpdate invocation
const VALID_TASK_STATUSES = new Set(['pending', 'in_progress', 'completed', 'deleted']);

/** Reset handler failure tracking (call at session boundaries) */
export function resetHandlerFailureCounts(): void {
  handlerFailureCounts.clear();
}

export async function runHandlers(label: string, ...handlers: Promise<void>[]): Promise<HandlerResult> {
  // ER21: Skip handler group if cascade threshold exceeded
  const priorFailures = handlerFailureCounts.get(label) || 0;
  if (priorFailures >= HANDLER_CASCADE_THRESHOLD) {
    console.error(`[post-tool] Skipping "${label}" group — ${priorFailures} consecutive failures (circuit open)`);
    recordMetric('post_tool.handler_circuit_open', 1, { group: label });
    return { failures: 0, total: handlers.length, errors: [] };
  }

  const results = await Promise.allSettled(handlers);
  const errors: HandlerResult['errors'] = [];
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    if (r.status === 'rejected') {
      const errorMsg = r.reason instanceof Error ? r.reason.message : String(r.reason);
      console.error(
        `[post-tool] Handler ${i} in "${label}" group rejected:`,
        errorMsg,
      );
      recordMetric('post_tool.handler_rejections', 1, {
        group: label,
        handler_index: String(i),
        error_type: r.reason instanceof Error ? r.reason.name : typeof r.reason,
      });
      errors.push({ index: i, error: errorMsg });
    }
  }

  // ER21: Track consecutive total-group failures (all handlers must fail to increment)
  const allFailed = errors.length === handlers.length && handlers.length > 0;
  if (allFailed) {
    handlerFailureCounts.set(label, priorFailures + 1);
  } else {
    handlerFailureCounts.delete(label);
  }

  return { failures: errors.length, total: handlers.length, errors };
}

interface HookInput {
  session_id?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_output?: string;
  tool_response?: unknown;
  cwd?: string;
  is_error?: boolean;
}

const ESTIMATE_SAMPLE_SIZE = 10;
const AGENT_SCAN_CHUNK_BYTES = 5000;
const NON_STRING_VALUE_BYTES = 32;
const KEY_OVERHEAD_BYTES = 4; // quotes + colon + comma
const STRING_VALUE_OVERHEAD_BYTES = 2; // quotes
const ARRAY_ELEMENT_BYTES = 64; // conservative per-element estimate

function estimateEntryBytes(key: string, val: unknown): number {
  let bytes = key.length + KEY_OVERHEAD_BYTES;
  if (typeof val === 'string') bytes += val.length + STRING_VALUE_OVERHEAD_BYTES;
  else if (Array.isArray(val)) bytes += val.length * ARRAY_ELEMENT_BYTES;
  else bytes += NON_STRING_VALUE_BYTES;
  return bytes;
}

/**
 * Rough size estimate of an object. Samples the first ESTIMATE_SAMPLE_SIZE entries
 * and extrapolates; only falls through to a full scan when the projection is under
 * the threshold (where precision matters for the accept/reject decision).
 */
function roughEstimateSize(obj: unknown): number {
  if (typeof obj === 'string') return obj.length;
  if (typeof obj !== 'object' || obj === null) return NON_STRING_VALUE_BYTES;

  const entries = Object.entries(obj as Record<string, unknown>);
  if (entries.length === 0) return 0;

  const sampleCount = Math.min(entries.length, ESTIMATE_SAMPLE_SIZE);
  let sampleBytes = 0;
  for (let i = 0; i < sampleCount; i++) {
    const [key, val] = entries[i];
    sampleBytes += estimateEntryBytes(key, val);
  }

  if (entries.length > sampleCount) {
    const projected = Math.ceil((sampleBytes / sampleCount) * entries.length);
    if (projected > THRESHOLDS.MAX_JSON_SIZE_BYTES) return projected;
  }

  let size = sampleBytes;
  for (let i = sampleCount; i < entries.length; i++) {
    const [key, val] = entries[i];
    size += estimateEntryBytes(key, val);
    if (size > THRESHOLDS.MAX_JSON_SIZE_BYTES) return size;
  }
  return size;
}

/** Resolve tool output text from tool_response (preferred) or tool_output (legacy fallback). */
function resolveOutputText(input: HookInput): string {
  // Claude Code provides tool_response (object or string) in PostToolUse hooks
  if (input.tool_response != null) {
    if (typeof input.tool_response === 'string') {
      return input.tool_response.length > THRESHOLDS.MAX_JSON_SIZE_BYTES
        ? input.tool_response.slice(0, THRESHOLDS.MAX_JSON_SIZE_BYTES)
        : input.tool_response;
    }
    // ER4: Pre-flight size check to avoid OOM on very large payloads
    if (roughEstimateSize(input.tool_response) > THRESHOLDS.MAX_JSON_SIZE_BYTES) {
      return '[response too large to serialize]';
    }
    try {
      const json = JSON.stringify(input.tool_response);
      if (json.length > THRESHOLDS.MAX_JSON_SIZE_BYTES) {
        // Return valid sentinel instead of truncated (malformed) JSON
        return `[response truncated: ${json.length} chars]`;
      }
      return json;
    } catch {
      return '[unserializable response]';
    }
  }
  return input.tool_output || '';
}

// ==================== MCP Post-Tool ====================

/** Detect if error is due to project context mismatch (wrong project activated) */
function detectProjectContextMismatch(output: string): { mismatch: boolean; suggestion?: string } {
  // Check for file-not-found errors with project path patterns
  if (!output.includes('not found') && !output.includes('FileNotFoundError')) {
    return { mismatch: false };
  }

  const telemetryDir = process.env.TELEMETRY_DIR || '~/.claude-history/telemetry';
  const claudeHome = telemetryDir.replace(/\/telemetry\/?$/, '').replace('telemetry', '.claude');

  const patterns = [
    { path: '/mcp-servers/observability-toolkit', project: 'observability-toolkit' },
    { path: '/mcp-servers', project: '.claude (or specific MCP project)' },
    { path: '/hooks', project: '.claude' },
    { path: '/skills', project: '.claude' },
    { path: claudeHome, project: '.claude' },
  ];

  for (const { path, project } of patterns) {
    if (output.includes(path) && output.includes('not found')) {
      return {
        mismatch: true,
        suggestion: `Activate project '${project}' before reading files from ${path.split('/').pop()}`,
      };
    }
  }

  return { mismatch: false };
}

function extractInputSummary(toolInput: Record<string, unknown> | undefined): string | undefined {
  if (!toolInput) return undefined;
  const candidates = ['url', 'path', 'query', 'account', 'handle', 'repo'];
  for (const key of candidates) {
    const value = toolInput[key];
    if (typeof value === 'string' && value.length > 0) {
      return value.slice(0, 200);
    }
  }
  return undefined;
}

async function handleMcpPostTool(input: HookInput, cwd?: string): Promise<void> {
  const mcpInfo = parseMcpToolName(input.tool_name || '');
  if (!mcpInfo) return;

  const scope = getMcpScope(mcpInfo.server, cwd);

  await instrumentHook('mcp-post-tool', async (ctx) => {
    const resolvedOutput = resolveOutputText(input);
    const analysis = analyzeOutput(resolvedOutput);

    // Detect project context mismatches (wrong project activated)
    const contextMismatch = detectProjectContextMismatch(resolvedOutput);

    ctx.addAttributes({
      'mcp.server': mcpInfo.server,
      'mcp.tool': mcpInfo.tool,
      'mcp.full_name': mcpInfo.fullName,
      'mcp.scope': scope,
      'mcp.success': analysis.success,
      'mcp.output_size': analysis.outputSize,
      'mcp.has_error': analysis.hasError,
      'session.id': input.session_id || '',
      ...(analysis.errorType ? { 'mcp.error_type': analysis.errorType } : {}),
      ...(analysis.errorCategory ? { 'mcp.error_category': analysis.errorCategory } : {}),
      ...(contextMismatch.mismatch ? { 'mcp.context_mismatch': true, 'mcp.suggestion': contextMismatch.suggestion } : {}),
    });

    // T1: Emit tool correctness quality metric for MCP tools
    emitToolCorrectness(analysis.success, mcpInfo.fullName, input.session_id || '');

    if (analysis.success) {
      ctx.logger.info('MCP tool completed', {
        'mcp.server': mcpInfo.server,
        'mcp.tool': mcpInfo.tool,
        'mcp.scope': scope,
        'mcp.output_size': analysis.outputSize,
      });
    } else {
      const errorMsg = `${mcpInfo.fullName}: ${analysis.errorType || 'unknown'}`;
      const suggestion = contextMismatch.suggestion ? ` — Try: ${contextMismatch.suggestion}` : '';

      ctx.logger.warn('MCP tool returned error', {
        'mcp.server': mcpInfo.server,
        'mcp.tool': mcpInfo.tool,
        'mcp.scope': scope,
        'mcp.error_type': analysis.errorType || 'unknown',
        ...(suggestion ? { suggestion: contextMismatch.suggestion } : {}),
      });
      ctx.span.recordException(new Error(errorMsg + suggestion));
    }

    ctx.recordMetric('mcp.completions', 1, {
      server: mcpInfo.server,
      tool: mcpInfo.tool,
      scope: scope,
      success: String(analysis.success),
    });

    ctx.recordMetric('mcp.output_size', analysis.outputSize, {
      server: mcpInfo.server,
      tool: mcpInfo.tool,
      scope: scope,
    });

    const status = analysis.success ? 'SUCCESS' : `ERROR:${analysis.errorType || 'unknown'}`;
    trackInvocation('mcp', input.session_id || 'default', `${mcpInfo.server}\t${mcpInfo.tool}`, status, `${analysis.outputSize}bytes`);

    // Track MCP invocation for completeness validation
    const sessionId = input.session_id || '';
    if (sessionId) {
      const inputSummary = extractInputSummary(input.tool_input);
      const recorded = recordMcpInvocation(sessionId, {
        server: mcpInfo.server,
        tool: mcpInfo.tool,
        success: analysis.success,
        timestamp: new Date().toISOString(),
        params: inputSummary,
      });
      if (!recorded) {
        ctx.logger.error('Failed to record MCP invocation', {
          'mcp.server': mcpInfo.server,
          'mcp.tool': mcpInfo.tool,
        });
      }
    }

    const sizeKb = (analysis.outputSize / 1024).toFixed(1);
    if (analysis.success) {
      console.error(`[MCP] ${mcpInfo.server}/${mcpInfo.tool} (${sizeKb}KB)`);
    } else {
      console.error(`[MCP ERROR] ${mcpInfo.server}/${mcpInfo.tool} - ${analysis.errorType || 'error'}`);
    }

    if (analysis.outputSize > THRESHOLDS.LARGE_OUTPUT_BYTES) {
      ctx.logger.warn('Large MCP output', {
        'mcp.server': mcpInfo.server,
        'mcp.tool': mcpInfo.tool,
        'mcp.output_size': analysis.outputSize,
      });
    }

    // Track MCP server failures (e.g., "Server X not found")
    // Fire-and-fence: do not let handleMcpStatus rejection propagate and corrupt outer metrics
    if (analysis.hasError) {
      handleMcpStatus({
        session_id: input.session_id,
        tool_name: input.tool_name,
        tool_output: resolvedOutput,
        is_error: true,
      }).catch((err: unknown) => {
        console.error('[post-tool] handleMcpStatus error:', err instanceof Error ? err.message : err);
      });
    }
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'mcp' });
}

// ==================== Plugin Post-Tool ====================

async function handlePluginPostTool(input: HookInput): Promise<void> {
  if (input.tool_name !== 'Skill') return;

  const skillName = input.tool_input && typeof input.tool_input === 'object' && 'skill' in input.tool_input
    ? String(input.tool_input.skill) : undefined;
  if (!skillName) return;

  await instrumentHook('plugin-post-tool', async (ctx) => {
    const outputSize = resolveOutputText(input).length;

    ctx.addAttributes({
      'plugin.name': skillName,
      'plugin.output_size': outputSize,
      'session.id': input.session_id || '',
    });

    ctx.logger.info('Plugin completed', {
      'plugin.name': skillName,
      'plugin.output_size': outputSize,
    });

    ctx.recordMetric('plugin.completions', 1, { name: skillName });
    ctx.recordMetric('plugin.output_size', outputSize, { name: skillName });

    trackInvocation('plugin', input.session_id || 'default', skillName, 'COMPLETED', `${outputSize}bytes`);

    console.error(`[Plugin] ${skillName} completed`);
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'plugin' });
}

// ==================== Built-in Tool Post-Tool ====================

async function handleBuiltinPostTool(input: HookInput): Promise<void> {
  const toolName = input.tool_name || '';
  if (!BUILTIN_TOOLS.has(toolName)) return;

  const toolEndMs = Date.now();

  await instrumentHook('builtin-post-tool', async (ctx) => {
    const category = categorizeBuiltinTool(toolName);
    const analysis = analyzeBuiltinOutput(toolName, resolveOutputText(input));

    // Extract file_path from tool input (Write, Edit, MultiEdit, Read all use file_path)
    const filePath = input.tool_input && typeof input.tool_input === 'object' && 'file_path' in input.tool_input
      ? String(input.tool_input.file_path) : undefined;

    ctx.addAttributes({
      'builtin.tool': toolName,
      'builtin.category': category,
      'builtin.success': analysis.success,
      'builtin.output_size': analysis.outputSize,
      'builtin.has_error': analysis.hasError,
      'session.id': input.session_id || '',
      ...(filePath ? { 'builtin.file_path': filePath } : {}),
      ...(analysis.errorType ? { 'builtin.error_type': analysis.errorType } : {}),
      ...(analysis.errorCategory ? { 'builtin.error_category': analysis.errorCategory } : {}),
      ...(analysis.resultCount !== undefined ? { 'builtin.result_count': analysis.resultCount } : {}),
    });

    // T1: Emit tool correctness quality metric
    emitToolCorrectness(analysis.success, toolName, input.session_id || '');

    // Capture task-specific attributes for status transition tracking
    if (toolName === 'TaskCreate' || toolName === 'TaskUpdate') {
      const toolInput = input.tool_input;
      const status = toolInput && typeof toolInput === 'object' && 'status' in toolInput
        ? toolInput.status : undefined;
      const taskId = toolInput && typeof toolInput === 'object' && 'taskId' in toolInput
        ? toolInput.taskId : undefined;

      if (toolName === 'TaskCreate') {
        const explicitStatus = typeof status === 'string' && VALID_TASK_STATUSES.has(status)
          ? status : 'pending';
        ctx.addAttribute('builtin.task_status', explicitStatus);
      } else if (typeof status === 'string' && VALID_TASK_STATUSES.has(status)) {
        ctx.addAttribute('builtin.task_status', status);
      } else if (toolName === 'TaskUpdate' && typeof taskId === 'string' && taskId.trim()) {
        // Fallback: read current status from persisted state for updates without explicit status
        const sessionId = input.session_id || '';
        if (sessionId) {
          const state = loadTaskState(sessionId);
          const task = state?.tasks?.find(t => t.id === taskId.trim());
          if (task) {
            ctx.addAttribute('builtin.task_status', task.status);
          }
        }
      }
      if (typeof taskId === 'string' && taskId.trim().length > 0) {
        ctx.addAttribute('builtin.task_id', taskId.trim());
      }

      // Persist task state to disk for compaction resilience
      const sessionId = input.session_id || '';
      if (sessionId) {
        const resolvedStatus: TaskStatus | undefined =
          typeof status === 'string' && VALID_TASK_STATUSES.has(status)
            ? (status as TaskStatus)
            : (toolName === 'TaskCreate' ? 'pending' : undefined);
        // For TaskCreate, parse numeric ID from output ("Task #N created successfully")
        // so it matches the ID used by subsequent TaskUpdate calls.
        let resolvedId = typeof taskId === 'string' ? taskId.trim() : '';
        if (!resolvedId && toolName === 'TaskCreate') {
          const outputText = resolveOutputText(input);
          const idMatch = outputText.match(/Task #(\d+)/);
          resolvedId = idMatch ? idMatch[1] : generateTaskId();
        }
        const subject = toolInput && typeof toolInput === 'object' && 'subject' in toolInput
          ? String(toolInput.subject) : '';

        if (resolvedStatus !== undefined && (resolvedId || toolName === 'TaskCreate')) {
          const now = new Date().toISOString();
          const ok = upsertTask(sessionId, {
            id: resolvedId || generateTaskId(),
            name: subject,
            status: resolvedStatus,
            createdAt: now,
            updatedAt: now,
          });
          if (!ok) {
            ctx.logger.error('Failed to persist task state', {
              'session.id': sessionId,
              'builtin.task_id': resolvedId,
            });
            ctx.recordMetric('task.persistence_failures', 1, {
              session_id: sessionId,
              task_id: resolvedId,
            });
          }
        }
      }
    }

    if (analysis.success) {
      ctx.logger.info('Built-in tool completed', {
        'builtin.tool': toolName,
        'builtin.category': category,
        'builtin.output_size': analysis.outputSize,
      });
    } else {
      ctx.logger.warn('Built-in tool returned error', {
        'builtin.tool': toolName,
        'builtin.category': category,
        'builtin.error_type': analysis.errorType || 'unknown',
      });
      ctx.span.recordException(new Error(`${toolName}: ${analysis.errorType || 'unknown'}`));
    }

    ctx.recordMetric('builtin.completions', 1, {
      tool: toolName,
      category: category,
      success: String(analysis.success),
    });

    ctx.recordMetric('builtin.output_size', analysis.outputSize, {
      tool: toolName,
      category: category,
    });

    if (analysis.hasError) {
      ctx.recordMetric('builtin.errors', 1, {
        tool: toolName,
        category: category,
        error_type: analysis.errorType || 'unknown',
      });
    }

    if (analysis.resultCount !== undefined) {
      ctx.recordMetric('builtin.result_count', analysis.resultCount, {
        tool: toolName,
      });
    }

    // Step 2: Accumulate execute_tool span for agent reparenting
    const agentCtx = getActiveAgentContext();
    if (agentCtx) {
      const toolStart = consumeToolStartTime();
      addToolSpan({
        name: 'execute_tool',
        traceId: agentCtx.traceId,
        spanId: generateHex(SPAN_ID_BYTES),
        parentSpanId: agentCtx.invokeSpanId,
        startTimeMs: toolStart.timeMs,
        endTimeMs: toolEndMs,
        attributes: {
          'gen_ai.operation.name': 'execute_tool',
          'gen_ai.tool.name': toolName,
          'gen_ai.tool.type': 'function',
          'builtin.success': analysis.success,
          'session.id': input.session_id || '',
          ...(toolStart.estimated ? { 'execute_tool.start_time_estimated': true } : {}),
        },
      });
    }
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'builtin' });
}

// ==================== Agent Audit Evaluation Injection ====================

/** Map scorecard labels to canonical dimension names */
const AUDIT_LABEL_MAP: Record<string, string> = {
  telemetry: 'telemetry',
  definition: 'definition',
  prompt: 'prompting',
  overlap: 'overlap',
  alignment: 'alignment',
  efficiency: 'efficiency',
};

/** Pattern: "| 1. Telemetry Health | 8.5 | A |" — captures label and score */
const DIMENSION_SCORE_PATTERN = /\|\s*\d+\.\s*([^|]+?)\s*\|\s*([\d.]+)\s*(?:\/\s*10)?\s*\|/g;
const TOTAL_SCORE_PATTERN = /\|\s*\*?\*?Total\*?\*?\s*\|\s*\*?\*?([\d.]+)\s*(?:\/\s*60)?\*?\*?\s*\|/i;
const AGENT_NAME_PATTERN = /## Agent:\s*`([^`]+)`/;

/**
 * Parse agent-auditor scorecard output and inject evaluation records.
 * Fire-and-forget — errors are silently swallowed.
 */
export function injectAuditEvaluations(output: string, sessionId: string): void {
  const agentMatch = output.match(AGENT_NAME_PATTERN);
  if (!agentMatch) return;
  const agentName = agentMatch[1];

  const totalMatch = output.match(TOTAL_SCORE_PATTERN);
  if (!totalMatch) return;
  const totalScore = parseFloat(totalMatch[1]);
  if (Number.isNaN(totalScore)) return;

  const extras = { 'gen_ai.agent.name': agentName };

  // Reset lastIndex to avoid state leak from prior calls (module-scoped regex with /g flag)
  DIMENSION_SCORE_PATTERN.lastIndex = 0;

  // Inject per-dimension scores
  const dimensionScores: Record<string, number> = {};
  let match: RegExpExecArray | null;
  while ((match = DIMENSION_SCORE_PATTERN.exec(output)) !== null) {
    const label = match[1].toLowerCase().trim();
    const score = parseFloat(match[2]);
    if (Number.isNaN(score)) continue;

    // Map label to canonical dimension name via first matching key
    const dim = Object.keys(AUDIT_LABEL_MAP).find(k => label.includes(k));
    const canonical = dim ? AUDIT_LABEL_MAP[dim] : undefined;
    if (canonical && !dimensionScores[canonical]) {
      dimensionScores[canonical] = score;
      appendEvaluation({
        name: `agent.quality.score.${canonical}`,
        score,
        evaluatorType: 'rule',
        evaluator: 'agent-auditor',
        sessionId,
        extraAttributes: extras,
      });
    }
  }

  // Inject total score
  appendEvaluation({
    name: 'agent.quality.score',
    score: totalScore,
    evaluatorType: 'rule',
    evaluator: 'agent-auditor',
    sessionId,
    extraAttributes: extras,
  });
}

// ==================== Agent Post-Tool ====================

async function handleAgentPostTool(input: HookInput): Promise<void> {
  if (input.tool_name !== 'Agent' && input.tool_name !== 'Task') return;

  const toolInput = input.tool_input as { subagent_type?: string } | undefined;
  const agentType = toolInput?.subagent_type;
  if (!agentType) return;

  const agentInfo = getAgentSourceType(agentType);
  const sourceType = agentInfo.sourceType;

  await instrumentHook('agent-post-tool', async (ctx) => {
    const output = resolveOutputText(input);
    const outputSize = output.length;

    // Phase 6: on outputs larger than LARGE_OUTPUT_BYTES, pattern-match against
    // head+tail sample only. Error markers (stack traces, failure lines) cluster
    // at the start/end; scanning the middle is wasted work on large payloads.
    const scanTarget = outputSize > THRESHOLDS.LARGE_OUTPUT_BYTES
      ? output.slice(0, AGENT_SCAN_CHUNK_BYTES) + output.slice(-AGENT_SCAN_CHUNK_BYTES)
      : output;

    // Detect rate limit (word-boundary patterns to avoid false positives)
    const hasRateLimit = isRateLimitError({ message: scanTarget }) ||
      /\b429\b/.test(scanTarget);
    // AQ17: Separate actual tool errors from output that merely discusses errors
    const hasError = !!input.is_error;
    const outputMentionsError = !hasRateLimit && AGENT_ERROR_PATTERN.test(scanTarget);

    ctx.addAttributes({
      'integritystudio.agent.type': agentType,
      'integritystudio.agent.output_size': outputSize,
      'integritystudio.agent.has_rate_limit': hasRateLimit,
      'integritystudio.agent.has_error': hasError,
      'integritystudio.agent.output_mentions_error': outputMentionsError,
      'session.id': input.session_id || '',
    });

    if (agentInfo.parentSkill) {
      ctx.addAttribute('integritystudio.agent.parent_skill', agentInfo.parentSkill);
    }

    // A1: Output quality heuristics (rule-based, no LLM judge)
    const coherenceSignals = {
      hasStructure: /^#+\s|^\|.*\|/m.test(output),
      hasCode: /```/.test(output),
      hasActions: /\b(TODO|FIXME|Action|Recommend)\b/i.test(output),
      truncated: output.endsWith('...') || outputSize >= 50000,
      empty: outputSize < 50,
    };

    ctx.addAttributes({
      'integritystudio.agent.output.has_structure': coherenceSignals.hasStructure,
      'integritystudio.agent.output.has_code': coherenceSignals.hasCode,
      'integritystudio.agent.output.has_actions': coherenceSignals.hasActions,
      'integritystudio.agent.output.truncated': coherenceSignals.truncated,
      'integritystudio.agent.output.empty': coherenceSignals.empty,
    });

    // T1: Emit coherence heuristic quality metric
    emitCoherenceHeuristic({
      ...coherenceSignals,
      outputSize,
    }, agentType, input.session_id || '');

    // A2: GenAI semantic convention attributes
    ctx.addAttributes({
      'gen_ai.agent.name': agentType,
      'gen_ai.agent.id': agentInfo.parentSkill
        ? `${sourceType}:${agentInfo.parentSkill}:${agentType}`
        : `${sourceType}:${agentType}`,
      'gen_ai.operation.name': 'invoke_agent',
    });

    if (hasRateLimit) {
      ctx.recordEvent('agent.rate_limit', { 'integritystudio.agent.type': agentType });
      ctx.logger.warn('Agent hit rate limit', { 'integritystudio.agent.type': agentType });
      console.error(`[Agent] ${agentType} hit rate limit — consider retry with backoff`);
    } else if (hasError) {
      ctx.logger.warn('Agent completed with errors', {
        'integritystudio.agent.type': agentType,
        'integritystudio.agent.output_size': outputSize,
      });
      console.error(`[Agent] ${agentType} completed with errors`);
    } else {
      ctx.logger.info('Agent completed', {
        'integritystudio.agent.type': agentType,
        'integritystudio.agent.output_size': outputSize,
        ...(outputMentionsError ? { 'integritystudio.agent.output_mentions_error': true } : {}),
      });
      console.error(`[Agent] ${agentType} completed`);
    }

    ctx.recordMetric('integritystudio.agent.completions', 1, {
      type: agentType,
      source_type: sourceType,
      rate_limited: hasRateLimit,
      has_error: String(hasError),
      output_mentions_error: String(outputMentionsError),
    });
    ctx.recordMetric('integritystudio.agent.output_size', outputSize, { type: agentType });

    // A3: Estimated output tokens metric (4 chars/token approximation)
    const estimatedOutputTokens = Math.ceil(outputSize / 4);
    ctx.recordMetric('gen_ai.usage.output_tokens', estimatedOutputTokens, { type: agentType });

    trackInvocation('agent', input.session_id || 'default', agentType,
      hasRateLimit ? 'RATE_LIMITED' : hasError ? 'ERROR' : outputMentionsError ? 'COMPLETED_WITH_ERROR_MENTIONS' : 'COMPLETED',
      `${outputSize}bytes`);

    // Inject evaluation records from agent-auditor scorecard output
    if (agentType === 'agent-auditor' && !hasError && !hasRateLimit) {
      try {
        injectAuditEvaluations(output, input.session_id || '');
      } catch {
        // Best-effort — don't fail the hook
      }
    }

    // Steps 1-4: Build and submit consolidated OTel GenAI agent spans
    const pending = popPendingAgent(input.session_id || '', agentType);
    if (pending) {
      const endTimeMs = Date.now();
      const synthSpans: SynthSpan[] = [];

      // Step 1: create_agent (first invocation per session per agent)
      // Uses createSpanId pre-generated in pre-tool — same ID stored in seenAgents
      let createAgentSpanId: string | undefined;
      if (pending.isFirstSeen) {
        createAgentSpanId = pending.createSpanId;
        synthSpans.push({
          name: 'create_agent',
          traceId: pending.traceId,
          spanId: createAgentSpanId,
          startTimeMs: pending.startTimeMs,
          endTimeMs: pending.startTimeMs + SYNTH_INSTANT_SPAN_DURATION_MS,
          attributes: {
            'gen_ai.operation.name': 'create_agent',
            'gen_ai.agent.name': pending.agentName,
            'gen_ai.agent.id': pending.agentId,
            'session.id': pending.sessionId,
            ...pending.preToolAttrs,
          },
        });
      }

      // Consolidated invoke_agent span (pre-tool start → post-tool end)
      // Parent is either the just-created create_agent span, or the prior one from seenAgents
      const invokeParentSpanId = createAgentSpanId || getCreateAgentSpanId(pending.sessionId, pending.agentName);
      // OBP6: link the agent's own trace back to the dispatching span (captured in
      // pre-tool). Links express cross-trace causality the way backends understand;
      // parent-child stays within this synthetic agent trace.
      const dispatchLinks =
        pending.triggerTraceId && pending.triggerSpanId
          ? [{
              traceId: pending.triggerTraceId,
              spanId: pending.triggerSpanId,
              traceFlags: pending.triggerTraceFlags,
              attributes: { [AGENT_LINK_ATTRIBUTES.LINK_KIND]: AGENT_LINK_KIND_DISPATCH },
            }]
          : undefined;
      synthSpans.push({
        name: 'invoke_agent',
        traceId: pending.traceId,
        spanId: pending.invokeSpanId,
        parentSpanId: invokeParentSpanId,
        links: dispatchLinks,
        startTimeMs: pending.startTimeMs,
        endTimeMs,
        attributes: {
          ...pending.preToolAttrs,
          'integritystudio.agent.output_size': outputSize,
          'integritystudio.agent.has_error': hasError,
          'integritystudio.agent.has_rate_limit': hasRateLimit,
          'integritystudio.agent.output.has_structure': coherenceSignals.hasStructure,
          'integritystudio.agent.output.has_code': coherenceSignals.hasCode,
          'integritystudio.agent.output.truncated': coherenceSignals.truncated,
          'integritystudio.agent.output.empty': coherenceSignals.empty,
        },
      });

      // Step 2: accumulated execute_tool child spans
      synthSpans.push(...pending.pendingToolSpans);

      // Step 4: Fire-and-forget submit to ingest
      submitSynthSpans(synthSpans).catch(() => {});
    }
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'agent' });
}

// ==================== Type Check Common ====================

interface TypeCheckInput {
  tool_name?: string;
  tool_input?: { file_path?: string };
  session_id?: string;
  cwd?: string;
}

async function handleTscCheck(input: TypeCheckInput): Promise<void> {
  const toolName = input.tool_name || '';
  if (!['Write', 'Edit', 'MultiEdit'].includes(toolName)) return;

  const filePath = input.tool_input?.file_path;
  if (!filePath || !filePath.match(/\.tsx?$/)) return;

  await instrumentHook('tsc-check', async (ctx) => {
    ctx.addAttributes({
      'tsc.file': filePath,
      'tsc.tool': toolName,
      'session.id': input.session_id || '',
    });

    const repoRoot = findTsRepoRoot(filePath);
    if (!repoRoot) {
      ctx.logger.debug('No repo root found for TSC check', { file: filePath });
      return;
    }

    const repoName = repoRoot.split('/').pop() || 'unknown';
    ctx.addAttribute('tsc.repo', repoName);

    const tscCommand = getTscCommand(repoRoot);
    if (!tscCommand) {
      ctx.logger.debug('No TSC command available', { repo: repoName });
      return;
    }

    const cacheManager = TypeCheckCacheManager.for('tsc', input.session_id || 'default');
    cacheManager.queueRepo(repoName, tscCommand);
    cacheManager.logEditedFile(toolName, filePath);
    cacheManager.logFileHash(repoName, filePath);

    ctx.logger.info('TSC check queued', {
      'tsc.repo': repoName,
      'tsc.file': filePath,
    });

    ctx.recordMetric('tsc.files_queued', 1, { repo: repoName });
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'tsc-check' });
}

// ==================== Python Type Check ====================

async function handlePyCheck(input: TypeCheckInput): Promise<void> {
  const toolName = input.tool_name || '';
  if (!['Write', 'Edit', 'MultiEdit'].includes(toolName)) return;

  const filePath = input.tool_input?.file_path;
  if (!filePath || !filePath.match(/\.pyi?$/)) return;

  await instrumentHook('py-check', async (ctx) => {
    ctx.addAttributes({
      'py.file': filePath,
      'py.tool': toolName,
      'session.id': input.session_id || '',
    });

    const repoRoot = findPyRepoRoot(filePath);
    if (!repoRoot) {
      ctx.logger.debug('No repo root found for Python check', { file: filePath });
      return;
    }

    const repoName = repoRoot.split('/').pop() || 'unknown';
    ctx.addAttribute('py.repo', repoName);

    const pyCommand = getPyCheckCommand(repoRoot);
    if (!pyCommand) {
      ctx.logger.debug('No Python type check command available', { repo: repoName });
      return;
    }

    const cacheManager = TypeCheckCacheManager.for('py', input.session_id || 'default');
    cacheManager.queueRepo(repoName, pyCommand);
    cacheManager.logEditedFile(toolName, filePath);
    cacheManager.logFileHash(repoName, filePath);

    ctx.logger.info('Python check queued', {
      'py.repo': repoName,
      'py.file': filePath,
    });

    ctx.recordMetric('py.files_queued', 1, { repo: repoName });
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'py-check' });
}

// ==================== Code Structure Signals ====================

export interface StructureSignals {
  lines: number;
  exports: number;
  functions: number;
  imports: number;
  maxNesting: number;
  hasTypes: boolean;
  isPartial: boolean;
  score: number;
}

export function computeStructureSignals(content: string, isPartial: boolean): StructureSignals {
  const lines = content.split('\n').length;
  const exports = (content.match(/\bexport\s/g) || []).length;
  const functions = (content.match(/\bfunction\b/g) || []).length +
    (content.match(/=>/g) || []).length;
  const imports = (content.match(/\bimport\s/g) || []).length;

  // Max brace nesting depth
  let maxNesting = 0;
  let current = 0;
  for (const ch of content) {
    if (ch === '{') { current++; if (current > maxNesting) maxNesting = current; }
    else if (ch === '}') { current = Math.max(0, current - 1); }
  }

  const hasTypes = /:\s*(string|number|boolean|void|any|unknown|never|Record|Array|Promise|null|undefined)\b/.test(content) ||
    /\binterface\s/.test(content) ||
    /\btype\s+\w+\s*=/.test(content);

  let score: number;
  if (isPartial) {
    const nestingScore = maxNesting <= 3 ? 1.0 : maxNesting <= 5 ? 0.7 : maxNesting <= 8 ? 0.4 : 0.2;
    const typeScore = hasTypes ? 1.0 : 0.0;
    score = (nestingScore + typeScore) / 2;
  } else {
    const modRatio = functions > 0 ? Math.min(exports / functions, 1.0) : (exports > 0 ? 1.0 : 0.0);
    const modularity = modRatio * 0.25;
    const nestingScore = maxNesting <= 3 ? 1.0 : maxNesting <= 5 ? 0.7 : maxNesting <= 8 ? 0.4 : 0.2;
    const complexity = nestingScore * 0.25;
    const typeSafety = (hasTypes ? 1.0 : 0.0) * 0.20;
    const organization = (imports > 0 ? 1.0 : 0.0) * 0.15;
    const sizeScore = lines < 5 ? 0.3 : lines > 500 ? 0.5 : 1.0;
    const size = sizeScore * 0.15;
    score = modularity + complexity + typeSafety + organization + size;
  }

  score = Math.round(score * 100) / 100;
  return { lines, exports, functions, imports, maxNesting, hasTypes, isPartial, score };
}

interface CodeContent {
  content: string;
  isPartial: boolean;
}

function extractCodeContent(input: HookInput): CodeContent | null {
  const toolName = input.tool_name || '';
  const toolInput = input.tool_input || {};

  if (toolName === 'Write') {
    const content = typeof toolInput.content === 'string' ? toolInput.content : '';
    return content ? { content, isPartial: false } : null;
  }

  if (toolName === 'Edit') {
    const content = typeof toolInput.new_string === 'string' ? toolInput.new_string : '';
    return content ? { content, isPartial: true } : null;
  }

  if (toolName === 'MultiEdit') {
    const edits = Array.isArray(toolInput.edits) ? toolInput.edits : [];
    const combined = edits
      .map((e: unknown) => {
        if (e && typeof e === 'object' && 'new_string' in e) {
          const val = (e as Record<string, unknown>).new_string;
          return typeof val === 'string' ? val : '';
        }
        return '';
      })
      .filter(Boolean)
      .join('\n');
    return combined ? { content: combined, isPartial: true } : null;
  }

  return null;
}

const JS_TS_EXT = /\.(tsx?|jsx?)$/;

async function handleCodeStructure(input: HookInput): Promise<void> {
  const toolName = input.tool_name || '';
  if (!['Write', 'Edit', 'MultiEdit'].includes(toolName)) return;

  const filePath = input.tool_input && typeof input.tool_input === 'object' && 'file_path' in input.tool_input
    ? String(input.tool_input.file_path) : undefined;
  if (!filePath || !JS_TS_EXT.test(filePath)) return;

  const codeContent = extractCodeContent(input);
  if (!codeContent) return;

  const signals = computeStructureSignals(codeContent.content, codeContent.isPartial);

  await instrumentHook('code-structure', async (ctx) => {
    ctx.addAttributes({
      'integritystudio.code.structure.lines': signals.lines,
      'integritystudio.code.structure.exports': signals.exports,
      'integritystudio.code.structure.functions': signals.functions,
      'integritystudio.code.structure.imports': signals.imports,
      'integritystudio.code.structure.max_nesting': signals.maxNesting,
      'integritystudio.code.structure.has_types': signals.hasTypes,
      'integritystudio.code.structure.is_partial': signals.isPartial,
      'integritystudio.code.structure.score': signals.score,
      'integritystudio.code.structure.file': filePath,
      'integritystudio.code.structure.tool': toolName,
      'session.id': input.session_id || '',
    });

    ctx.recordMetric('integritystudio.code.structure.score', signals.score, {
      file: filePath,
      tool: toolName,
      is_partial: String(signals.isPartial),
    });
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'code-structure' });
}

// ==================== TypeScript File Create Handler ====================

// Lazy-loaded agent definition (only loaded when needed)
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const AGENT_FILE_PATH = join(__dirname, 'agents', 'typescript-type-validator.md');

const agentCache = { content: null as string | null };

/**
 * Get TypeScript type validator agent content (lazy-loaded and cached)
 */
function getTypescriptTypeValidatorAgent(): string {
  if (agentCache.content !== null) {
    return agentCache.content;
  }

  // Try to load from file first
  if (existsSync(AGENT_FILE_PATH)) {
    agentCache.content = readFileSync(AGENT_FILE_PATH, 'utf-8');
    return agentCache.content;
  }

  // Fallback to embedded default
  agentCache.content = DEFAULT_TS_AGENT_CONTENT;
  return agentCache.content;
}

/** Reset cached agent content (for testing/session boundaries) */
export function resetAgentCache(): void {
  agentCache.content = null;
}

const DEFAULT_TS_AGENT_CONTENT = `---
name: typescript-type-validator
description: Fix TypeScript type errors and add runtime validation using Zod schemas. Provides patterns for type-safe APIs with clear error messages.
tools: Read, Write, Edit, MultiEdit, Bash
---

You are a TypeScript type validation specialist. Your job is to fix type errors and implement runtime validation using Zod schemas.

## When You're Invoked

This agent is available to help with:
- Fixing TypeScript compilation errors
- Adding runtime validation to API endpoints
- Converting manual validation to Zod schemas
- Ensuring type safety between compile-time and runtime

## Solution Pattern

### Step 1: Create Zod Schema
\`\`\`typescript
import { z } from 'zod';

export const MyRequestSchema = z.object({
  field: z.string().min(1, 'field required').max(255),
  optionalField: z.number().int().positive().optional(),
}).strict();

export type MyRequest = z.infer<typeof MyRequestSchema>;
\`\`\`

### Step 2: Validation Middleware
\`\`\`typescript
import { ZodSchema, ZodError } from 'zod';

export function validateRequest(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      req.body = schema.parse(req.body);
      next();
    } catch (error) {
      if (error instanceof ZodError) {
        return res.status(400).json({
          error: 'Bad Request',
          errors: error.errors.map(err => ({
            field: err.path.join('.'),
            message: err.message
          }))
        });
      }
      next(error);
    }
  };
}
\`\`\`

### Step 3: Apply to Routes
\`\`\`typescript
router.post('/endpoint', validateRequest(MyRequestSchema), async (req, res) => {
  const { field } = req.body; // Validated and typed!
});
\`\`\`

## Common Zod Validations

\`\`\`typescript
z.string().min(1).max(255).email().url().trim()
z.number().int().positive().min(0).max(100)
z.array(z.string()).min(1).max(10)
z.enum(['option1', 'option2'])
z.object({ field: z.string() }).strict()
z.string().optional().nullable()
\`\`\`

## Best Practices

1. **Single Source of Truth** - Derive types from schemas
2. **Clear Error Messages** - Always add custom messages
3. **Strict Mode** - Use \`.strict()\` to reject unknown fields
4. **Validate Early** - Use middleware, not inline checks
`;

interface LocalSettings {
  agents?: Record<string, { type: 'file' | 'inline'; source?: string; content?: string }>;
  [key: string]: unknown;
}

function hasInstalledTsAgent(projectRoot: string): boolean {
  const localSettingsPath = join(projectRoot, '.claude', 'settings.local.json');
  const settings = loadJsonSafe<LocalSettings>(localSettingsPath, {});
  return !!settings.agents?.['typescript-type-validator'];
}

function installTsAgentToProject(projectRoot: string): { success: boolean; message: string } {
  const claudeDir = join(projectRoot, '.claude');
  const localSettingsPath = join(claudeDir, 'settings.local.json');
  const agentFilePath = join(claudeDir, 'agents', 'typescript-type-validator.md');

  try {
    ensureDirExists(join(claudeDir, 'agents'));
    writeFileSync(agentFilePath, getTypescriptTypeValidatorAgent());

    const settings = loadJsonSafe<LocalSettings>(localSettingsPath, {});
    if (!settings.agents) {
      settings.agents = {};
    }
    settings.agents['typescript-type-validator'] = {
      type: 'file',
      source: '.claude/agents/typescript-type-validator.md',
    };

    writeJson(localSettingsPath, settings);

    return { success: true, message: 'Agent installed to project' };
  } catch (error) {
    return {
      success: false,
      message: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

async function handleTsFileCreate(input: HookInput): Promise<void> {
  if (input.tool_name !== 'Write') return;

  const filePath = input.tool_input && typeof input.tool_input === 'object' && 'file_path' in input.tool_input
    ? String(input.tool_input.file_path) : undefined;
  if (!filePath || !filePath.match(/\.tsx?$/)) return;

  const projectRoot = findProjectRoot(filePath);
  if (!projectRoot) return;

  if (hasInstalledTsAgent(projectRoot)) return;

  await instrumentHook('ts-file-create', async (ctx) => {
    ctx.addAttributes({
      'ts.file': filePath,
      'ts.project_root': projectRoot,
      'session.id': input.session_id || '',
    });

    const result = installTsAgentToProject(projectRoot);

    ctx.addAttribute('ts.agent_installed', result.success);
    ctx.recordMetric('ts.agent_installations', result.success ? 1 : 0);

    if (result.success) {
      ctx.logger.info('TypeScript agent installed to project', {
        'ts.project_root': projectRoot,
      });

      const projectName = projectRoot.split('/').pop() || 'project';
      console.error(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
      console.error(`TypeScript file created: ${filePath.split('/').pop()}`);
      console.error(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
      console.error(`Installed agent: typescript-type-validator`);
      console.error(`   Location: ${projectName}/.claude/agents/`);
      console.error(`   Use for: type errors, Zod validation, runtime type safety`);
      console.error(`   Invoke: Task(subagent_type='typescript-type-validator', ...)`);
      console.error(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
    } else {
      ctx.logger.warn('Failed to install TypeScript agent', {
        'ts.error': result.message,
      });
    }
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'ts-create' });
}

// ==================== Post-Commit Code Review ====================

const GIT_COMMIT_PATTERN = /\bgit\s+commit\b/;

export function isGitCommit(input: HookInput): boolean {
  if (input.tool_name !== 'Bash') return false;
  const command = (input.tool_input as { command?: string } | undefined)?.command || '';
  return GIT_COMMIT_PATTERN.test(command);
}

export function commitSucceeded(output: string): boolean {
  // git commit output contains the branch and short hash on success
  return /\[.+\s[a-f0-9]+\]/.test(output) && !output.includes('nothing to commit');
}

/** Max jitter (ms) before triggering post-commit review to prevent thundering herd */
const COMMIT_REVIEW_JITTER_MS = 3000;

async function handlePostCommitReview(input: HookInput): Promise<void> {
  if (!isGitCommit(input)) return;
  if (!commitSucceeded(resolveOutputText(input))) return;

  // Jitter 0-3s to stagger concurrent sessions hitting the API simultaneously
  const jitterMs = Math.floor(Math.random() * COMMIT_REVIEW_JITTER_MS);
  await new Promise(resolve => setTimeout(resolve, jitterMs));

  await instrumentHook('post-commit-review', async (ctx) => {
    const command = (input.tool_input as { command?: string })?.command || '';

    ctx.addAttributes({
      'integritystudio.git.command': command,
      'session.id': input.session_id || '',
      'review.jitter_ms': jitterMs,
    });

    ctx.logger.info('Git commit detected, requesting code review', {
      'integritystudio.git.command': command,
    });

    ctx.recordMetric('integritystudio.git.commits_reviewed', 1);

    // Output instructions for Claude to trigger the code-reviewer agent
    console.log('');
    console.log('## Post-Commit Code Review');
    console.log('');
    console.log('A git commit was just created. Run the **code-reviewer** agent to review the committed changes:');
    console.log('');
    console.log('```');
    console.log('Task(subagent_type="code-reviewer", prompt="Review the latest git commit. Run `git diff HEAD~1` to see the changes. Provide expert error checking and software engineering best practices review. Flag: security issues, error handling gaps, type safety problems, naming concerns, SOLID violations, and performance issues. Be concise.")');
    console.log('```');
    console.log('');
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'post-commit-review' });
}

// ==================== Main Handler ====================

export async function handlePostTool(input: HookInput, subType?: string): Promise<void> {
  const toolName = input.tool_name || '';

  if (subType === 'mcp' || toolName.startsWith('mcp__')) {
    await handleMcpPostTool(input, input.cwd);
  } else if (subType === 'plugin' || toolName === 'Skill') {
    await handlePluginPostTool(input);
  } else if (subType === 'agent' || toolName === 'Agent' || toolName === 'Task') {
    await handleAgentPostTool(input);
  } else if (MCP_RESOURCE_TOOLS.has(toolName)) {
    const output = resolveOutputText(input);
    const hasServerError = output.length < THRESHOLDS.LARGE_OUTPUT_BYTES &&
      /Server "[^"]+" not found/.test(output);
    await runHandlers('McpResource',
      handleBuiltinPostTool(input),
      handleMcpStatus({
        session_id: input.session_id,
        tool_name: toolName,
        tool_output: output,
        is_error: hasServerError,
      }),
    );
  } else if (toolName === 'Write') {
    await runHandlers('Write',
      handleBuiltinPostTool(input),
      handleTscCheck(input as TypeCheckInput),
      handlePyCheck(input as TypeCheckInput),
      handleTsFileCreate(input),
      handleCodeStructure(input),
      handleChangelogVersionBump(input),
    );
  } else if (['Edit', 'MultiEdit'].includes(toolName)) {
    await runHandlers('Edit',
      handleBuiltinPostTool(input),
      handleTscCheck(input as TypeCheckInput),
      handlePyCheck(input as TypeCheckInput),
      handleCodeStructure(input),
    );
  } else if (toolName === 'Bash') {
    await runHandlers('Bash',
      handleBuiltinPostTool(input),
      handlePostCommitReview(input),
      handleChangelogVersionBump(input),
    );
  } else if (subType === 'builtin' || BUILTIN_TOOLS.has(toolName)) {
    await handleBuiltinPostTool(input);
  }
}
