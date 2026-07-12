#!/usr/bin/env node
/**
 * Unified Hook Runner
 * Single entry point for all Claude Code hooks to avoid tsx startup overhead.
 *
 * Usage: node dist/hook-runner.js <hook-type>
 *
 * Hook types:
 *   - session-start: Run at session start
 *   - pre-tool: PreToolUse (mcp, plugin, agent)
 *   - post-tool: PostToolUse (mcp, plugin, agent, tsc-check)
 *   - stop: Stop event (build-check, error-reminder)
 *   - user-prompt: UserPromptSubmit (skill activation)
 *   - notification: Notification events
 *
 * Output convention:
 *   - console.log  → stdout → visible to Claude (user-facing messages)
 *   - console.error → stderr → diagnostics only (prefixed [MCP], [Agent], etc.)
 */

import { readFileSync } from 'fs';
import { handleSessionStart } from './handlers/session-start.js';
import { handlePreTool } from './handlers/pre-tool.js';
import { handlePostTool } from './handlers/post-tool.js';
import { handleStop } from './handlers/stop.js';
import { handleUserPrompt } from './handlers/user-prompt.js';
import { handleNotification } from './handlers/notification.js';
import { setSessionId } from './lib/otel-monitor.js';

type HookType = 'session-start' | 'pre-tool' | 'post-tool' | 'stop' | 'user-prompt' | 'notification';

interface HookInput {
  session_id?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_output?: string;
  transcript_path?: string;
  cwd?: string;
  permission_mode?: string;
  hook_event_name?: string;
}

// L1: exit 0 so non-critical hook failures (e.g. OTEL SDK issues) do not block Claude.
// Errors are logged to stderr for diagnostics but must not interrupt the session.
process.on('unhandledRejection', (reason) => {
  console.error('[hook-runner] Unhandled rejection:', reason instanceof Error ? reason.message : reason);
  process.exit(0);
});

const VALID_HOOK_TYPES = new Set<HookType>(['session-start', 'pre-tool', 'post-tool', 'stop', 'user-prompt', 'notification']);

async function main(): Promise<void> {
  const hookTypeArg = process.argv[2];
  const subType = process.argv[3]; // Optional sub-type for routing

  if (!hookTypeArg || !VALID_HOOK_TYPES.has(hookTypeArg as HookType)) {
    console.error(`Usage: hook-runner <hook-type> [sub-type]`);
    console.error(`Valid types: ${[...VALID_HOOK_TYPES].join(', ')}`);
    process.exit(1);
  }
  const hookType = hookTypeArg as HookType;

  // Read stdin
  let input = '';
  try {
    input = readFileSync(0, 'utf-8');
  } catch {
    // No stdin is OK for some hooks
  }

  let hookInput: HookInput = {};
  try {
    if (input.trim()) {
      hookInput = JSON.parse(input);
    }
  } catch (error) {
    const preview = input.slice(0, 200);
    console.error(
      `[hook-runner] Failed to parse stdin JSON: ${error instanceof Error ? error.message : String(error)}` +
      ` | input preview: ${JSON.stringify(preview)}`
    );
    process.exit(0);
  }

  // Auto-inject session.id into all spans.
  // Fallback: extract UUID from transcript_path when session_id is absent
  // (Claude Code encodes session ID as the filename: ~/.claude/projects/{slug}/{uuid}.jsonl)
  if (!hookInput.session_id && hookInput.transcript_path) {
    const match = hookInput.transcript_path.match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.jsonl$/i);
    if (match) {
      hookInput.session_id = match[1];
    }
  }
  if (hookInput.session_id) {
    setSessionId(hookInput.session_id);
  }

  try {
    switch (hookType) {
      case 'session-start':
        await handleSessionStart(hookInput);
        break;

      case 'pre-tool':
        await handlePreTool(hookInput, subType);
        break;

      case 'post-tool':
        await handlePostTool(hookInput, subType);
        break;

      case 'stop':
        await handleStop(hookInput, subType);
        break;

      case 'user-prompt':
        await handleUserPrompt(hookInput);
        break;

      case 'notification':
        await handleNotification(hookInput);
        break;

      default:
        console.error(`Unknown hook type: ${hookType}`);
        process.exit(1);
    }
  } catch (error) {
    // Log error but don't fail the hook
    console.error(`Hook error (${hookType}):`, error instanceof Error ? error.message : error);
    process.exit(0);
  }
}

main();
