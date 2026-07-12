/**
 * Stop Handler
 * Unified handler for stop event hooks (build check + error handling reminder + token metrics)
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import { THRESHOLDS, getTypeCheckCacheDir } from '../lib/constants.js';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
import { readFileSync, existsSync, rmSync, writeFileSync, appendFileSync, copyFileSync, statSync, readdirSync } from 'fs';
import { ensureDirExists } from '../lib/file-utils.js';
import { join } from 'path';
import { countTscErrors, countPyErrors } from '../lib/output-analyzer.js';
import { TypeCheckCacheManager } from '../lib/type-check-cache.js';
import { loadJson } from '../lib/file-utils.js';
import { getFileCategory } from '../lib/categorizers.js';
import { recordTokenUsage } from '../lib/token-metrics.js';
import { getSessionMcpSummary, getFailedInvocations, cleanupOldMcpState } from '../lib/mcp-completeness.js';
import { evaluateTaskAlerts, evaluateScrapingAlerts, type AlertRule } from '../lib/telemetry-alerts.js';
import { loadTaskState, calculateTaskCompletion, getActiveTasks } from '../lib/task-tracker.js';
import { emitTaskCompletion, emitEvaluationLatency, appendEvaluation, QUALITY_METRIC_NAMES, LLM_EVALUATOR_TYPE } from '../lib/quality-signals.js';
import { getSessionSamplingInfo, SAMPLING_CONFIG } from '../lib/quality-sampler.js';
import { hasBudget, getBudgetUsage, tryReserveBudget, COST_PER_METRIC_CENTS } from '../lib/quality-budget.js';
import { extractTurns, sampleTurns } from '../lib/transcript-parser.js';
import { recordMetric } from '../lib/otel.js';

interface HookInput {
  session_id?: string;
  transcript_path?: string;
  cwd?: string;
  permission_mode?: string;
  hook_event_name?: string;
}

interface RepoResult {
  repo: string;
  errorCount: number;
  output: string;
  duration: number;
  command: string;
}

// ==================== LLM Judge Types & Constants ====================

interface JudgeResult {
  score: number;
  reason: string;
}

/** Sample rate for meta-evaluation — mirrors META_EVAL_SAMPLE_RATE in toolkit llm-judge-config.ts */
const META_EVAL_SAMPLE_RATE = 0.1;

/** Evaluation name — must match EXPLANATION_QUALITY_CRITERIA.name in toolkit */
const META_EVAL_METRIC_NAME = 'explanation_quality';

/** Max tokens for judge responses (raised from 256 to accommodate explanation line) */
const JUDGE_MAX_TOKENS = 384;

/** Meta-eval judge model — defaults to same as primary judge, overridable */
const META_EVAL_JUDGE_MODEL = process.env.META_EVAL_JUDGE_MODEL || SAMPLING_CONFIG.JUDGE_MODEL;

/** Input length caps for judge prompts (prevents context window overflow + limits injection surface) */
const MAX_USER_TEXT_LEN = 500;
const MAX_ASSISTANT_TEXT_LEN = 2000;
const MAX_REASON_LEN = 400;
const MAX_TOOL_RESULT_LEN = 500;

function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...[truncated]' : text;
}

// ==================== Type Check Common ====================

type TypeCheckKind = 'tsc' | 'py';

/**
 * Filter tsc/py output to only include error lines from files edited in this session.
 * Non-error lines (headers, blank lines) are always retained to preserve context.
 */
function filterOutputToEditedFiles(output: string, editedFiles: Set<string>): string {
  // Build set of relative paths and basenames for matching
  const editedBasenames = new Set<string>();
  const editedRelPaths = new Set<string>();
  for (const fp of editedFiles) {
    const parts = fp.split('/');
    editedBasenames.add(parts[parts.length - 1]);
    // Also store partial paths for relative matching (e.g., "api/routes/scans.ts")
    for (let i = Math.max(0, parts.length - 4); i < parts.length; i++) {
      editedRelPaths.add(parts.slice(i).join('/'));
    }
  }

  const lines = output.split('\n');
  const filtered: string[] = [];

  for (const line of lines) {
    // Match tsc error format: "path/file.ts(line,col): error TS..."
    // Match py error format: "path/file.py:line: error:..."
    const tscMatch = line.match(/^(\S+?)\(\d+,\d+\):\s*error\s/);
    const pyMatch = line.match(/^(\S+?):\d+:.*error:/i);
    const errorFile = tscMatch?.[1] || pyMatch?.[1];

    if (errorFile) {
      // Only keep if this error file was edited in the session
      const isEdited = editedFiles.has(errorFile)
        || editedBasenames.has(errorFile.split('/').pop() || '')
        || Array.from(editedRelPaths).some((rp) => errorFile.endsWith(rp));
      if (isEdited) {
        filtered.push(line);
      }
    } else {
      // Keep non-error lines (headers, blank lines) unconditionally for context
      filtered.push(line);
    }
  }

  return filtered.join('\n');
}

async function runTypeCheck(
  input: HookInput,
  kind: TypeCheckKind,
  countErrors: (output: string) => number,
  errorLabel: string
): Promise<{ exitCode: number; totalErrors: number }> {
  const sessionId = input.session_id || 'default';
  const cacheDir = getTypeCheckCacheDir(kind, sessionId);

  if (!existsSync(cacheDir)) return { exitCode: 0, totalErrors: 0 };

  const affectedReposFile = join(cacheDir, 'affected-repos.txt');
  if (!existsSync(affectedReposFile)) return { exitCode: 0, totalErrors: 0 };

  const commandsFile = join(cacheDir, 'commands.txt');
  if (!existsSync(commandsFile)) return { exitCode: 0, totalErrors: 0 };

  // Load edited files to filter output to only session-changed files
  const editedFilesLog = join(cacheDir, 'edited-files.log');
  const editedFilePaths = new Set<string>();
  if (existsSync(editedFilesLog)) {
    readFileSync(editedFilesLog, 'utf-8').trim().split('\n').filter(Boolean).forEach((line) => {
      const parts = line.split('\t');
      if (parts[2]) editedFilePaths.add(parts[2]);
    });
  }

  const affectedRepos = readFileSync(affectedReposFile, 'utf-8').trim().split('\n').filter(Boolean);
  const commandsContent = readFileSync(commandsFile, 'utf-8');

  const repoCommands = new Map<string, string>();
  const commandPattern = new RegExp(`^([^:]+):${kind}:(.+)$`);
  commandsContent.split('\n').forEach((line) => {
    const match = line.match(commandPattern);
    if (match) {
      repoCommands.set(match[1], match[2]);
    }
  });

  if (affectedRepos.length === 0) return { exitCode: 0, totalErrors: 0 };

  let exitCode = 0;
  let totalErrorsFound = 0;

  await instrumentHook(`stop-${kind}-check`, async (ctx) => {
    ctx.addAttributes({
      'session.id': sessionId,
      'typecheck.kind': kind,
      'typecheck.session_id': sessionId,
      'typecheck.repos_affected': affectedRepos.length,
      'typecheck.repos': affectedRepos.join(','),
    });

    ctx.logger.info(`${errorLabel} check starting`, {
      'session.id': sessionId,
      'repos.count': affectedRepos.length,
    });

    const resultsDir = join(cacheDir, 'results');
    ensureDirExists(resultsDir);

    const results: RepoResult[] = [];
    let totalErrors = 0;
    const reposWithErrors: string[] = [];

    // Load per-repo session file hashes for hash-skip checks
    const repoFileHashesMap = new Map<string, Record<string, string>>();
    const fileHashesDir = join(cacheDir, 'file-hashes');
    for (const repo of affectedRepos) {
      const hashFile = join(fileHashesDir, `${repo.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`);
      const hashes = loadJson<Record<string, string>>(hashFile);
      if (hashes) repoFileHashesMap.set(repo, hashes);
    }

    const checkSingleRepo = async (repo: string): Promise<RepoResult | null> => {
      const cmd = repoCommands.get(repo);
      if (!cmd) {
        ctx.logger.warn('Repo skipped - no command', { 'repo.name': repo });
        return null;
      }

      // Phase 2: Content hash skip — if every edited file matches clean state, skip tsc
      const repoHashes = repoFileHashesMap.get(repo);
      if (repoHashes && TypeCheckCacheManager.canSkipCheck(kind, repo, repoHashes)) {
        ctx.logger.info('Hash skip — all files match clean state', { 'repo.name': repo });
        ctx.recordMetric(`${kind}.hash_skip`, 1, { repo });
        return { repo, errorCount: 0, output: '[hash-skip]', duration: 0, command: cmd };
      }

      const childSpan = ctx.startChildSpan(`${kind}:${repo}`, {
        'typecheck.repo': repo,
        'typecheck.command': cmd,
      });

      const startTime = Date.now();
      let output = '';
      let errorCount: number;

      try {
        const result = await execAsync(cmd, {
          encoding: 'utf-8',
          timeout: THRESHOLDS.EXEC_TIMEOUT_MS,
        });
        output = result.stdout + result.stderr;
        childSpan.addAttribute('typecheck.success', true);
        childSpan.end();

        const duration = Date.now() - startTime;
        ctx.logger.info('Repo check passed', {
          'repo.name': repo,
          'duration_ms': duration,
        });

        return { repo, errorCount: 0, output, duration, command: cmd };
      } catch (error: unknown) {
        // M3: detect timeout/killed to avoid reporting 0 errors (indistinguishable from success)
        const isTimeout = error && typeof error === 'object' &&
          ('killed' in error && (error as { killed?: boolean }).killed === true ||
           'code' in error && (error as { code?: string }).code === 'ETIMEDOUT');

        if (error && typeof error === 'object') {
          const execError = error as { stdout?: string; stderr?: string };
          output = (execError.stdout || '') + (execError.stderr || '');
        }

        if (isTimeout) {
          ctx.logger.warn(`${errorLabel} check timed out`, { 'repo.name': repo });
          childSpan.addAttribute('typecheck.timed_out', true);
          childSpan.end();
          return { repo, errorCount: 0, output: '[timed out]', duration: Date.now() - startTime, command: cmd };
        }

        // Filter output to only errors from files edited in this session
        if (editedFilePaths.size > 0) {
          output = filterOutputToEditedFiles(output, editedFilePaths);
        }

        errorCount = countErrors(output);

        const duration = Date.now() - startTime;

        if (errorCount > 0) {
          try {
            writeFileSync(join(resultsDir, `${repo}-errors.txt`), output);
          } catch (writeErr) {
            ctx.logger.warn('Failed to write error file', { repo, error: String(writeErr) });
          }

          ctx.logger.error(`${errorLabel} errors found`, {
            'repo.name': repo,
            'error.count': errorCount,
            'duration_ms': duration,
          });
        }

        childSpan.addAttribute('typecheck.success', false);
        childSpan.addAttribute('typecheck.error_count', errorCount);
        childSpan.endWithError(new Error(`${errorLabel} errors: ${errorCount}`));

        return { repo, errorCount, output, duration, command: cmd };
      }
    };

    const repoResults = await Promise.allSettled(
      affectedRepos.map(repo => checkSingleRepo(repo))
    );

    for (const settled of repoResults) {
      if (settled.status !== 'fulfilled' || !settled.value) continue;
      const r = settled.value;
      results.push(r);
      totalErrors += r.errorCount;
      if (r.errorCount > 0) reposWithErrors.push(r.repo);

      ctx.recordMetric(`${kind}.check.duration`, r.duration, {
        repo: r.repo,
        has_errors: String(r.errorCount > 0),
      });
      ctx.recordMetric(`${kind}.errors`, r.errorCount, { repo: r.repo });
      appendFileSync(join(resultsDir, 'error-summary.txt'), `${r.repo}:${r.errorCount}\n`);
    }

    ctx.addAttributes({
      'typecheck.total_errors': totalErrors,
      'typecheck.repos_with_errors': reposWithErrors.length,
      'typecheck.success': totalErrors === 0,
    });

    ctx.recordMetric(`${kind}.total_errors`, totalErrors);
    totalErrorsFound = totalErrors;

    if (totalErrors > 0) {
      const allErrors = results
        .filter((r) => r.errorCount > 0)
        .map((r) => `=== Errors in ${r.repo} ===\n${r.output}`)
        .join('\n\n');

      try {
        writeFileSync(join(cacheDir, 'last-errors.txt'), allErrors);
      } catch (writeErr) {
        ctx.logger.warn('Failed to write last-errors cache', { error: String(writeErr) });
      }

      if (existsSync(commandsFile)) {
        copyFileSync(commandsFile, join(cacheDir, `${kind}-commands.txt`));
      }

      const isMajor = totalErrors >= THRESHOLDS.MAJOR_ERROR_COUNT;
      ctx.addAttribute('typecheck.severity', isMajor ? 'major' : 'minor');

      console.error('');
      if (isMajor) {
        console.error(`## ${errorLabel} Errors Detected`);
        console.error('');
        console.error(`Found ${totalErrors} ${errorLabel} errors across the following repos:`);
        results
          .filter((r) => r.errorCount > 0)
          .forEach((r) => console.error(`- ${r.repo}: ${r.errorCount} errors`));
        console.error('');
        console.error('Please use the auto-error-resolver agent to fix these errors systematically.');
      } else {
        console.error(`## Minor ${errorLabel} Errors`);
        console.error('');
        console.error(`Found ${totalErrors} ${errorLabel} error(s). Here are the details:`);
        console.error('');
        console.error(allErrors.split('\n').map((l) => `  ${l}`).join('\n'));
        console.error('');
        console.error('Please fix these errors directly in the affected files.');
      }

      ctx.logger.error(`${errorLabel} check failed`, {
        'total.errors': totalErrors,
        'failed.repos': reposWithErrors.join(', '),
        'severity': isMajor ? 'major' : 'minor',
      });

      exitCode = 2;
    } else {
      // Phase 2: Persist clean state so future sessions can hash-skip
      for (const repo of affectedRepos) {
        const hashes = repoFileHashesMap.get(repo);
        if (hashes) {
          TypeCheckCacheManager.saveCleanState(kind, repo, hashes);
        }
      }

      rmSync(cacheDir, { recursive: true, force: true });
      ctx.logger.info(`${errorLabel} check completed`, {
        'repos.checked': affectedRepos.length,
        'total.errors': 0,
        'status': 'success',
      });
    }
  }, { 'hook.trigger': 'Stop', 'hook.type': `${kind}-check` });

  return { exitCode, totalErrors: totalErrorsFound };
}

async function handleBuildCheck(input: HookInput): Promise<number> {
  const results = await Promise.allSettled([
    runTypeCheck(input, 'tsc', countTscErrors, 'TypeScript'),
    runTypeCheck(input, 'py', countPyErrors, 'Python'),
  ]);

  let exitCode = 0;

  const tscSettled = results[0];
  if (tscSettled.status === 'fulfilled') {
    exitCode = Math.max(exitCode, tscSettled.value.exitCode);
  } else {
    console.error('[stop] TSC check crashed:', tscSettled.reason);
    exitCode = 2;
  }

  const pySettled = results[1];
  if (pySettled.status === 'fulfilled') {
    exitCode = Math.max(exitCode, pySettled.value.exitCode);
  } else {
    console.error('[stop] Python check crashed:', pySettled.reason);
    exitCode = 2;
  }

  return exitCode;
}

// ==================== Error Handling Reminder ====================

function shouldCheckErrorHandling(filePath: string): boolean {
  if (filePath.match(/\.(test|spec)\.(ts|tsx)$/)) return false;
  if (filePath.match(/\.(config|d)\.(ts|tsx)$/)) return false;
  if (filePath.includes('types/')) return false;
  if (filePath.includes('.styles.ts')) return false;
  return filePath.match(/\.(ts|tsx|js|jsx)$/) !== null;
}

function analyzeFileContent(filePath: string): {
  hasTryCatch: boolean;
  hasAsync: boolean;
  hasPrisma: boolean;
  hasController: boolean;
  hasApiCall: boolean;
} {
  if (!existsSync(filePath)) {
    return { hasTryCatch: false, hasAsync: false, hasPrisma: false, hasController: false, hasApiCall: false };
  }

  const content = readFileSync(filePath, 'utf-8');

  return {
    hasTryCatch: /try\s*\{/.test(content),
    hasAsync: /async\s+/.test(content),
    hasPrisma: /prisma\.|PrismaService|findMany|findUnique|create\(|update\(|delete\(/i.test(content),
    hasController: /export class.*Controller|router\.|app\.(get|post|put|delete|patch)/.test(content),
    hasApiCall: /fetch\(|axios\.|apiClient\./i.test(content),
  };
}

async function handleErrorReminder(input: HookInput): Promise<void> {
  if (process.env.SKIP_ERROR_REMINDER === '1') return;

  await instrumentHook('error-handling-reminder', async (ctx) => {
    ctx.logger.debug('Error handling reminder starting');

    const sessionId = input.session_id || 'default';
    ctx.addAttribute('session.id', sessionId);

    const cacheDir = getTypeCheckCacheDir('tsc', sessionId);
    const trackingFile = join(cacheDir, 'edited-files.log');

    if (!existsSync(trackingFile)) {
      ctx.logger.debug('No files edited this session');
      ctx.addAttribute('files.edited', 0);
      return;
    }

    const trackingContent = readFileSync(trackingFile, 'utf-8');
    const editedFiles = trackingContent
      .trim()
      .split('\n')
      .filter((line) => line.length > 0)
      .map((line) => {
        const [timestamp, tool, path] = line.split('\t');
        return { timestamp, tool, path };
      });

    ctx.addAttribute('files.edited', editedFiles.length);

    if (editedFiles.length === 0) return;

    const categories = {
      backend: [] as string[],
      frontend: [] as string[],
      database: [] as string[],
      other: [] as string[],
    };

    const analysisResults: Array<{
      path: string;
      category: string;
      analysis: ReturnType<typeof analyzeFileContent>;
    }> = [];

    for (const file of editedFiles) {
      if (!shouldCheckErrorHandling(file.path)) continue;
      const category = getFileCategory(file.path);
      categories[category].push(file.path);
      const analysis = analyzeFileContent(file.path);
      analysisResults.push({ path: file.path, category, analysis });
    }

    ctx.addAttributes({
      'files.backend': categories.backend.length,
      'files.frontend': categories.frontend.length,
      'files.database': categories.database.length,
    });

    const needsAttention = analysisResults.some(
      ({ analysis }) =>
        analysis.hasTryCatch || analysis.hasAsync || analysis.hasPrisma || analysis.hasController || analysis.hasApiCall
    );

    ctx.addAttribute('needs_attention', needsAttention);

    if (!needsAttention) {
      ctx.logger.debug('No risky code patterns detected');
      return;
    }

    ctx.logger.info('Error handling patterns detected', {
      'files.total': editedFiles.length,
      'files.analyzed': analysisResults.length,
    });

    console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('ERROR HANDLING SELF-CHECK');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

    if (categories.backend.length > 0) {
      const backendFiles = analysisResults.filter((f) => f.category === 'backend');
      const hasTryCatch = backendFiles.some((f) => f.analysis.hasTryCatch);
      const hasPrisma = backendFiles.some((f) => f.analysis.hasPrisma);
      const hasController = backendFiles.some((f) => f.analysis.hasController);

      console.log('Backend Changes Detected');
      console.log(`   ${categories.backend.length} file(s) edited\n`);

      if (hasTryCatch) console.log('   - Did you add Sentry.captureException() in catch blocks?');
      if (hasPrisma) console.log('   - Are Prisma operations wrapped in error handling?');
      if (hasController) console.log('   - Do controllers use BaseController.handleError()?');

      console.log('\n   Backend Best Practice:');
      console.log('      - All errors should be captured to Sentry');
      console.log('      - Use appropriate error helpers for context');
      console.log('      - Controllers should extend BaseController\n');
    }

    if (categories.frontend.length > 0) {
      const frontendFiles = analysisResults.filter((f) => f.category === 'frontend');
      const hasApiCall = frontendFiles.some((f) => f.analysis.hasApiCall);
      const hasTryCatch = frontendFiles.some((f) => f.analysis.hasTryCatch);

      console.log('Frontend Changes Detected');
      console.log(`   ${categories.frontend.length} file(s) edited\n`);

      if (hasApiCall) console.log('   - Do API calls show user-friendly error messages?');
      if (hasTryCatch) console.log('   - Are errors displayed to the user?');

      console.log('\n   Frontend Best Practice:');
      console.log('      - Use your notification system for user feedback');
      console.log('      - Error boundaries for component errors\n');
    }

    if (categories.database.length > 0) {
      console.log('Database Changes Detected');
      console.log(`   ${categories.database.length} file(s) edited\n`);
      console.log('   - Did you verify column names against schema?');
      console.log('   - Are migrations tested?\n');
    }

    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('TIP: Disable with SKIP_ERROR_REMINDER=1');
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
  });
}

// ==================== Token Metrics Extraction ====================

interface TranscriptEntry {
  type: string;
  message?: {
    model?: string;
    usage?: {
      input_tokens?: number;
      output_tokens?: number;
      cache_read_input_tokens?: number;
      cache_creation_input_tokens?: number;
    };
  };
  timestamp?: string;
}

interface SessionTokenStats {
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCacheReadTokens: number;
  totalCacheCreationTokens: number;
  messageCount: number;
  model: string;
}

function parseTranscriptForTokens(transcriptPath: string): SessionTokenStats | null {
  if (!existsSync(transcriptPath)) return null;

  try {
    const content = readFileSync(transcriptPath, 'utf-8');
    const lines = content.trim().split('\n').filter(Boolean);

    const stats: SessionTokenStats = {
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalCacheReadTokens: 0,
      totalCacheCreationTokens: 0,
      messageCount: 0,
      model: 'unknown',
    };

    for (const line of lines) {
      try {
        const entry: TranscriptEntry = JSON.parse(line);

        // Only process assistant messages with usage data
        if (entry.type === 'assistant' && entry.message?.usage) {
          const usage = entry.message.usage;

          stats.totalInputTokens += usage.input_tokens || 0;
          stats.totalOutputTokens += usage.output_tokens || 0;
          stats.totalCacheReadTokens += usage.cache_read_input_tokens || 0;
          stats.totalCacheCreationTokens += usage.cache_creation_input_tokens || 0;
          stats.messageCount++;

          // Capture the model from the message
          if (entry.message.model) {
            stats.model = entry.message.model;
          }
        }
      } catch {
        // Skip malformed lines
      }
    }

    return stats.messageCount > 0 ? stats : null;
  } catch {
    return null;
  }
}

/**
 * Discover transcript path from session_id when not provided in hook input.
 * Claude Code stores transcripts at ~/.claude/projects/<project-hash>/<session-id>.jsonl
 */
function discoverTranscriptPath(sessionId: string): string | undefined {
  // Validate session ID format (UUID) to prevent path traversal
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId)) {
    return undefined;
  }

  const projectsDir = join(process.env.HOME || '', '.claude', 'projects');
  if (!existsSync(projectsDir)) return undefined;

  try {
    const projectDirs = readdirSync(projectsDir);
    for (const dir of projectDirs) {
      const candidate = join(projectsDir, dir, `${sessionId}.jsonl`);
      if (existsSync(candidate)) return candidate;
    }
  } catch {
    // Filesystem errors — don't block hook execution
  }
  return undefined;
}

// Dedup cache: session_id -> last-seen transcript file size
const _tokenMetricsCache = new Map<string, number>();

async function handleTokenMetrics(input: HookInput): Promise<void> {
  const transcriptPath = input.transcript_path
    || (input.session_id ? discoverTranscriptPath(input.session_id) : undefined);
  if (!transcriptPath) return;

  // Skip if transcript hasn't changed since last extraction
  const cacheKey = input.session_id || 'default';
  try {
    const currentSize = statSync(transcriptPath).size;
    if (_tokenMetricsCache.get(cacheKey) === currentSize) return;
    _tokenMetricsCache.set(cacheKey, currentSize);
  } catch {
    // If stat fails, proceed with extraction anyway
  }

  await instrumentHook('token-metrics-extraction', async (ctx) => {
    ctx.addAttribute('session.id', input.session_id || '');
    ctx.logger.debug('Extracting token metrics from transcript', {
      'transcript.path': transcriptPath,
    });

    const stats = parseTranscriptForTokens(transcriptPath);

    if (!stats) {
      ctx.logger.debug('No token data found in transcript');
      ctx.addAttribute('tokens.found', false);
      return;
    }

    ctx.addAttributes({
      'tokens.found': true,
      'tokens.input': stats.totalInputTokens,
      'tokens.output': stats.totalOutputTokens,
      'tokens.cache_read': stats.totalCacheReadTokens,
      'tokens.cache_creation': stats.totalCacheCreationTokens,
      'tokens.messages': stats.messageCount,
      'tokens.model': stats.model,
    });

    // Record token usage metrics using GenAI semantic conventions
    // Total effective input = input + cache_creation (cache_read doesn't count toward billing input)
    const effectiveInputTokens = stats.totalInputTokens + stats.totalCacheCreationTokens;

    recordTokenUsage({
      inputTokens: effectiveInputTokens,
      outputTokens: stats.totalOutputTokens,
      model: stats.model,
      operation: 'session',
      attributes: {
        'session.id': input.session_id || 'unknown',
        'session.messages': stats.messageCount,
        'cache.read_tokens': stats.totalCacheReadTokens,
        'cache.creation_tokens': stats.totalCacheCreationTokens,
      },
    });

    ctx.logger.info('Token metrics recorded', {
      'input_tokens': effectiveInputTokens,
      'output_tokens': stats.totalOutputTokens,
      'cache_read_tokens': stats.totalCacheReadTokens,
      'model': stats.model,
      'messages': stats.messageCount,
    });

    // Log summary for user visibility (only if significant usage)
    if (stats.totalInputTokens + stats.totalOutputTokens > 1000) {
      const totalTokens = effectiveInputTokens + stats.totalOutputTokens;
      const cacheHitRate = stats.totalCacheReadTokens > 0
        ? ((stats.totalCacheReadTokens / (stats.totalCacheReadTokens + stats.totalInputTokens)) * 100).toFixed(1)
        : '0';

      ctx.recordMetric('session.total_tokens', totalTokens, { model: stats.model });
      ctx.recordMetric('session.cache_hit_rate', parseFloat(cacheHitRate), { model: stats.model });
    }
  }, { 'hook.trigger': 'Stop', 'hook.type': 'token-metrics' });
}

// ==================== Main Handler ====================

// --- T2: Sampled LLM judge at session end ---

async function handleQualityEvaluation(input: HookInput): Promise<void> {
  const sessionId = input.session_id;
  if (!sessionId) return;

  // Check sampling decision (single flag read for both sampled + canary)
  const samplingInfo = getSessionSamplingInfo(sessionId);
  if (!samplingInfo.sampled) return;

  // Check budget
  if (!hasBudget()) {
    console.error('[Quality] Daily evaluation budget exhausted');
    return;
  }

  // Build auth headers early; apiKey remains reachable via closure but is only sent in request headers
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return;
  const judgeHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'x-api-key': apiKey,
    'anthropic-version': '2023-06-01',
  };

  // Extract transcript turns (use discoverTranscriptPath fallback like handleTokenMetrics)
  const transcriptPath = input.transcript_path
    || discoverTranscriptPath(sessionId);
  if (!transcriptPath) return;

  await instrumentHook('quality-evaluation-t2', async (ctx) => {
    const startMs = Date.now();
    const canary = samplingInfo.canary;

    ctx.addAttributes({
      'session.id': sessionId,
      'quality.eval_type': 'llm',
      'quality.canary': canary,
    });

    try {
      const allTurns = extractTurns(transcriptPath);
      if (allTurns.length === 0) {
        ctx.addAttribute('quality.eval_skipped', 'no_turns');
        return;
      }

      const turns = sampleTurns(allTurns, SAMPLING_CONFIG.MAX_TURNS_PER_SESSION);
      ctx.addAttribute('quality.turns_sampled', turns.length);
      ctx.addAttribute('quality.turns_total', allTurns.length);

      // Run LLM judge on each turn
      let metaEvalsCount = 0;

      for (const turn of turns) {
        // Budget checked atomically via tryReserveBudget per metric below
        if (!hasBudget()) break;

        let relevanceResult: JudgeResult | null = null;
        let coherenceResult: JudgeResult | null = null;

        try {
          relevanceResult = await callLlmJudge(judgeHeaders, 'relevance', turn, canary);
        } catch {
          recordMetric('quality.llm_judge_failures', 1, { 'session.id': sessionId, metric: 'relevance' });
        }

        try {
          coherenceResult = await callLlmJudge(judgeHeaders, 'coherence', turn, canary);
        } catch {
          recordMetric('quality.llm_judge_failures', 1, { 'session.id': sessionId, metric: 'coherence' });
        }

        // Base eval reservation guards meta-eval: meta-eval only runs if
        // base eval successfully reserved budget (R6.2-H1)
        if (relevanceResult !== null && tryReserveBudget(COST_PER_METRIC_CENTS)) {
          recordMetric(QUALITY_METRIC_NAMES.LLM_RELEVANCE, relevanceResult.score, {
            evaluator_type: LLM_EVALUATOR_TYPE,
            'session.id': sessionId,
          });
          appendEvaluation({
            name: 'relevance',
            score: relevanceResult.score,
            evaluatorType: LLM_EVALUATOR_TYPE,
            evaluator: SAMPLING_CONFIG.JUDGE_MODEL,
            sessionId,
            explanation: relevanceResult.reason,
          });

          const ran = await maybeMetaEvaluate(judgeHeaders, 'relevance', relevanceResult, turn.userText, sessionId, canary);
          if (ran) metaEvalsCount++;
        }

        if (coherenceResult !== null && tryReserveBudget(COST_PER_METRIC_CENTS)) {
          recordMetric(QUALITY_METRIC_NAMES.LLM_COHERENCE, coherenceResult.score, {
            evaluator_type: LLM_EVALUATOR_TYPE,
            'session.id': sessionId,
          });
          appendEvaluation({
            name: 'coherence',
            score: coherenceResult.score,
            evaluatorType: LLM_EVALUATOR_TYPE,
            evaluator: SAMPLING_CONFIG.JUDGE_MODEL,
            sessionId,
            explanation: coherenceResult.reason,
          });

          const ran = await maybeMetaEvaluate(judgeHeaders, 'coherence', coherenceResult, turn.userText, sessionId, canary);
          if (ran) metaEvalsCount++;
        }
      }

      ctx.addAttribute('quality.meta_evals_run', metaEvalsCount);
    } finally {
      const durationMs = Date.now() - startMs;
      emitEvaluationLatency(durationMs, 'quality-evaluation-t2');
      ctx.addAttribute('quality.eval_duration_ms', durationMs);

      const budget = getBudgetUsage();
      ctx.addAttribute('quality.budget_used_cents', budget.estimatedCostCents);
      ctx.addAttribute('quality.budget_remaining_cents', budget.remaining);
    }
  }, { 'hook.trigger': 'Stop', 'hook.type': 'quality-evaluation' });
}

async function callAnthropicJudge(
  headers: Record<string, string>,
  prompt: string,
  canary: boolean,
  model?: string,
): Promise<JudgeResult> {
  // Canary: return intentionally low scores for validation
  if (canary) return { score: 0.2 + Math.random() * 0.3, reason: 'canary' };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SAMPLING_CONFIG.EVAL_TIMEOUT_MS);

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        model: model ?? SAMPLING_CONFIG.JUDGE_MODEL,
        max_tokens: JUDGE_MAX_TOKENS,
        temperature: 0.0,
        messages: [{ role: 'user', content: prompt }],
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Anthropic API error: ${response.status}`);
    }

    const data = await response.json() as {
      content?: Array<{ type: string; text?: string }>;
    };
    const text = data.content?.[0]?.text ?? '';

    // Extract score from response (expect "Score: X.XX" format)
    const scoreMatch = text.match(/Score:\s*(\d+(?:\.\d+)?)/i);
    if (!scoreMatch?.[1]) {
      throw new Error('llm_judge_score_parse_failed');
    }

    const rawScore = parseFloat(scoreMatch[1]);
    if (isNaN(rawScore)) throw new Error('llm_judge_score_parse_failed');
    const score = Math.max(0, Math.min(1, rawScore));

    // Extract explanation from the line after score; fallback to full text
    const explanationMatch = text.match(/Explanation:\s*(.+)/i);
    const reason = explanationMatch?.[1]?.trim() || text.trim();

    return { score, reason };
  } finally {
    clearTimeout(timer);
  }
}

async function callLlmJudge(
  headers: Record<string, string>,
  metricName: 'relevance' | 'coherence',
  turn: { userText: string; assistantText: string; toolResults: string[] },
  canary: boolean,
): Promise<JudgeResult> {
  const prompt = metricName === 'relevance'
    ? buildRelevancePrompt(turn)
    : buildCoherencePrompt(turn);
  return callAnthropicJudge(headers, prompt, canary);
}

function shouldMetaEvaluate(evaluationName: string, canary: boolean): boolean {
  if (canary) return false;
  if (evaluationName === META_EVAL_METRIC_NAME) return false;
  return Math.random() < META_EVAL_SAMPLE_RATE;
}

function buildExplanationQualityPrompt(
  evaluationName: string,
  score: number,
  reason: string,
  userText: string,
): string {
  const safeUser = truncate(userText, MAX_USER_TEXT_LEN);
  const safeReason = truncate(reason, MAX_REASON_LEN);

  return `You are evaluating the quality of a judge's explanation for an evaluation score.

The judge evaluated "${evaluationName}" and gave a score of ${score.toFixed(2)}.

Original user request:
${safeUser}

Judge's explanation:
${safeReason}

Rate the explanation quality on a scale from 0.0 to 1.0 based on:
1. Specificity: Does it reference concrete details from the evaluated output?
2. Evidence citation: Does it quote or paraphrase specific passages as evidence?
3. Actionability: Does it suggest what could be improved?

- 1.0: Highly specific, cites evidence, actionable
- 0.7: Specific with some evidence, partially actionable
- 0.5: General but relevant reasoning
- 0.3: Vague or generic explanation
- 0.0: No meaningful reasoning provided

A concise but specific explanation can score highly.

Respond in exactly this format:
Score: X.XX
Explanation: [1-2 sentences about the quality of the explanation]`;
}

async function maybeMetaEvaluate(
  judgeHeaders: Record<string, string>,
  evaluationName: string,
  result: JudgeResult,
  userText: string,
  sessionId: string,
  canary: boolean,
): Promise<boolean> {
  if (!shouldMetaEvaluate(evaluationName, canary)) return false;
  if (!tryReserveBudget(COST_PER_METRIC_CENTS)) return false;

  try {
    const metaPrompt = buildExplanationQualityPrompt(
      evaluationName, result.score, result.reason, userText
    );
    const metaResult = await callAnthropicJudge(
      judgeHeaders, metaPrompt, false, META_EVAL_JUDGE_MODEL
    );
    recordMetric(QUALITY_METRIC_NAMES.LLM_EXPLANATION_QUALITY, metaResult.score, {
      evaluator_type: LLM_EVALUATOR_TYPE,
      'session.id': sessionId,
      'meta.original_evaluation': evaluationName,
    });
    appendEvaluation({
      name: META_EVAL_METRIC_NAME,
      score: metaResult.score,
      evaluatorType: LLM_EVALUATOR_TYPE,
      evaluator: META_EVAL_JUDGE_MODEL,
      sessionId,
      explanation: metaResult.reason,
      extraAttributes: { 'meta.original_evaluation': evaluationName },
    });
    return true;
  } catch {
    recordMetric('quality.llm_judge_failures', 1, {
      'session.id': sessionId,
      metric: META_EVAL_METRIC_NAME,
    });
    return false;
  }
}

function buildRelevancePrompt(turn: { userText: string; assistantText: string; toolResults: string[] }): string {
  const safeUser = truncate(turn.userText, MAX_USER_TEXT_LEN);
  const safeAssistant = truncate(turn.assistantText, MAX_ASSISTANT_TEXT_LEN);
  const toolContext = turn.toolResults.length > 0
    ? `\nTool results used:\n${turn.toolResults.slice(0, 3).map(r => truncate(r, MAX_TOOL_RESULT_LEN)).join('\n---\n')}`
    : '';

  return `You are evaluating the relevance of an AI assistant's response to a user's request.

User request:
${safeUser}

Assistant response:
${safeAssistant}${toolContext}

Rate the relevance of the response on a scale from 0.0 to 1.0:
- 1.0: Perfectly relevant, directly addresses the user's request
- 0.7: Mostly relevant with minor tangents
- 0.5: Partially relevant
- 0.3: Mostly irrelevant
- 0.0: Completely irrelevant

Respond in exactly this format:
Score: X.XX
Explanation: [1-2 sentences citing specific evidence from the response]`;
}

function buildCoherencePrompt(turn: { userText: string; assistantText: string }): string {
  const safeAssistant = truncate(turn.assistantText, MAX_ASSISTANT_TEXT_LEN);

  return `You are evaluating the coherence of an AI assistant's response.

Assistant response:
${safeAssistant}

Rate the coherence on a scale from 0.0 to 1.0:
- 1.0: Well-structured, clear, logically organized
- 0.7: Mostly coherent with minor issues
- 0.5: Somewhat coherent but hard to follow
- 0.3: Mostly incoherent
- 0.0: Completely incoherent

Respond in exactly this format:
Score: X.XX
Explanation: [1-2 sentences citing specific evidence from the response]`;
}

export async function handleStop(input: HookInput, subType?: string): Promise<void> {
  let exitCode = 0;

  // Always extract token metrics at session end
  await handleTokenMetrics(input);

  // T2: Start LLM quality evaluation concurrently — don't block build check
  const t2Promise = handleQualityEvaluation(input).catch((e) => {
    console.error(`[Quality] T2 evaluation error: ${e instanceof Error ? e.message : 'Unknown'}`);
  });

  if (!subType || subType === 'build') {
    exitCode = await handleBuildCheck(input);
  }

  // Await T2 after build check completes
  await t2Promise;

  if ((!subType || subType === 'error') && exitCode === 0) {
    await handleErrorReminder(input);
  }

  // Log MCP completeness summary if any invocations tracked
  if (input.session_id) {
    const sessionIdForMcp = input.session_id;
    const mcpSummary = getSessionMcpSummary(sessionIdForMcp);
    const entries = Object.entries(mcpSummary);
    if (entries.length > 0) {
      const failedEntries = entries.filter(([, s]) => s.failed > 0);
      if (failedEntries.length > 0) {
        const totalFailed = failedEntries.reduce((sum, [, s]) => sum + s.failed, 0);
        const totalAll = entries.reduce((sum, [, s]) => sum + s.total, 0);
        const failedServers = failedEntries.map(([key]) => key).join(',');

        await instrumentHook('mcp-session-failure-summary', async (ctx) => {
          ctx.addAttributes({
            'session.id': sessionIdForMcp,
            'mcp.session_failed_count': totalFailed,
            'mcp.session_total_count': totalAll,
            'mcp.session_failed_servers': failedServers,
          });
          recordMetric('mcp.session_failures', totalFailed, {
            'session.id': sessionIdForMcp,
          });

          const failures = getFailedInvocations(sessionIdForMcp);
          for (const [key, s] of failedEntries) {
            console.error(`[MCP] ${key}: ${s.failed}/${s.total} failed`);
          }
          for (const inv of failures) {
            const params = inv.params ? ` (${inv.params})` : '';
            console.error(`  [FAIL] ${inv.server}/${inv.tool}${params} at ${inv.timestamp}`);
          }
        }, { 'hook.trigger': 'Stop', 'hook.type': 'mcp-session-failure-summary' });
      }
    }
    cleanupOldMcpState(7);
  }

  // Evaluate telemetry alerts at session end
  if (input.session_id) {
    const triggered: AlertRule[] = [];

    // Task completion alert + T1 quality metric (only if active tasks exist)
    const taskState = loadTaskState(input.session_id);
    if (taskState) {
      const active = getActiveTasks(taskState.tasks);
      if (active.length > 0) {
        const ratio = calculateTaskCompletion(taskState.tasks);
        triggered.push(...evaluateTaskAlerts(ratio));

        // T1: Emit task completion quality metric + evaluation record
        emitTaskCompletion(ratio, input.session_id);
        appendEvaluation({
          name: 'task_completion',
          score: ratio,
          evaluatorType: 'rule',
          evaluator: 'hook:stop',
          sessionId: input.session_id,
          explanation: `${active.length} active tasks, completion ratio: ${(ratio * 100).toFixed(0)}%`,
        });
      }
    }

    // MCP scraping alert
    const mcpSum = getSessionMcpSummary(input.session_id);
    const mcpEntries = Object.values(mcpSum);
    if (mcpEntries.length > 0) {
      const totalFailed = mcpEntries.reduce((sum, s) => sum + s.failed, 0);
      const totalAll = mcpEntries.reduce((sum, s) => sum + s.total, 0);
      triggered.push(...evaluateScrapingAlerts(totalFailed, totalAll));
    }

    if (triggered.length > 0) {
      await instrumentHook('telemetry-alert-evaluation', async (ctx) => {
        ctx.addAttribute('session.id', input.session_id || '');
        ctx.addAttribute('alerts.triggered_count', triggered.length);
        for (const alert of triggered) {
          if (alert.channels.includes('console')) {
            const prefix = alert.severity === 'critical' ? '[CRITICAL]' : '[WARN]';
            console.error(`${prefix} ${alert.message}`);
          }
          if (alert.channels.includes('telemetry')) {
            ctx.recordEvent(`alert.${alert.severity}`, {
              'alert.name': alert.name,
              'alert.message': alert.message,
            });
            ctx.recordMetric(`alerts.${alert.severity}`, 1, { alert_name: alert.name });
          }
        }
      }, { 'hook.trigger': 'Stop', 'hook.type': 'alert-evaluation' });
    }
  }

  if (exitCode !== 0) {
    process.exit(exitCode);
  }
}

// Exported for testing — not part of public API
export const _test = process.env.NODE_ENV === 'test' ? {
  shouldMetaEvaluate,
  buildExplanationQualityPrompt,
  callAnthropicJudge,
  maybeMetaEvaluate,
  META_EVAL_SAMPLE_RATE,
  META_EVAL_METRIC_NAME,
  JUDGE_MAX_TOKENS,
} as const : undefined;
