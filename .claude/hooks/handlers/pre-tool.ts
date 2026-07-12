/**
 * Pre-Tool Handler
 * Unified handler for MCP, Plugin, and Agent pre-tool hooks
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import { otelApi } from '../lib/otel.js';
import { BUILTIN_TOOLS, GENAI_AGENT_ATTRIBUTES, THRESHOLDS, SPAN_ID_BYTES, TRACE_ID_BYTES, getAgentSourceType, getSkillSourceType } from '../lib/constants.js';
import { loadPromptContext } from '../lib/trace-context.js';
import { categorizeSkill, categorizeAgent, categorizeBuiltinTool } from '../lib/categorizers.js';
import { parseSkillName, parseMcpToolName, getInputSummary } from '../lib/parsers.js';
import { trackInvocation } from '../lib/cache-tracker.js';
import { savePendingAgent, markFirstSeen, generateHex, setToolStartTime } from '../lib/agent-context.js';

interface HookInput {
  session_id?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
}

// ==================== MCP Pre-Tool ====================

async function handleMcpPreTool(input: HookInput): Promise<void> {
  const mcpInfo = parseMcpToolName(input.tool_name || '');
  if (!mcpInfo) return;

  await instrumentHook('mcp-pre-tool', async (ctx) => {
    const toolInput = (input.tool_input || {}) as Record<string, unknown>;

    ctx.addAttributes({
      'mcp.server': mcpInfo.server,
      'mcp.tool': mcpInfo.tool,
      'mcp.full_name': mcpInfo.fullName,
      'mcp.input_params': Object.keys(toolInput).join(','),
      'mcp.input_count': Object.keys(toolInput).length,
      'session.id': input.session_id || '',
      ...getPromptLink(input.session_id),
    });

    ctx.logger.info('MCP tool invoked', {
      'mcp.server': mcpInfo.server,
      'mcp.tool': mcpInfo.tool,
      'mcp.params': getInputSummary(toolInput),
    });

    ctx.recordMetric('mcp.invocations', 1, {
      server: mcpInfo.server,
      tool: mcpInfo.tool,
    });

    trackInvocation('mcp', input.session_id || 'default', `${mcpInfo.server}\t${mcpInfo.tool}`, 'STARTED');

    console.error(`[MCP] ${mcpInfo.server}/${mcpInfo.tool}`);
  }, { 'hook.trigger': 'PreToolUse', 'hook.type': 'mcp' });
}

// ==================== Plugin Pre-Tool ====================

async function handlePluginPreTool(input: HookInput): Promise<void> {
  if (input.tool_name !== 'Skill') return;

  const toolInput = input.tool_input as { skill?: string; args?: string } | undefined;
  const skillName = toolInput?.skill;
  if (!skillName) return;

  await instrumentHook('plugin-pre-tool', async (ctx) => {
    const skillInfo = parseSkillName(skillName);
    const category = categorizeSkill(skillName);
    const sourceType = getSkillSourceType(skillInfo.name);

    ctx.addAttributes({
      'plugin.name': skillInfo.name,
      'plugin.full_name': skillInfo.fullName,
      'plugin.category': category,
      'plugin.source_type': sourceType,
      'plugin.has_args': !!toolInput?.args,
      'session.id': input.session_id || '',
      ...getPromptLink(input.session_id),
    });

    if (skillInfo.namespace) {
      ctx.addAttribute('plugin.namespace', skillInfo.namespace);
    }

    ctx.logger.info('Plugin invoked', {
      'plugin.name': skillInfo.name,
      'plugin.namespace': skillInfo.namespace || 'default',
      'plugin.category': category,
      'plugin.source_type': sourceType,
    });

    ctx.recordMetric('plugin.invocations', 1, {
      name: skillInfo.name,
      category: category,
      namespace: skillInfo.namespace || 'default',
      source_type: sourceType,
    });

    trackInvocation('plugin', input.session_id || 'default', `${skillInfo.fullName}\t${category}\t${sourceType}`, 'STARTED');

    const namespacePrefix = skillInfo.namespace ? `${skillInfo.namespace}:` : '';
    console.error(`[Plugin] ${namespacePrefix}${skillInfo.name} [${category}] (${sourceType})`);
  }, { 'hook.trigger': 'PreToolUse', 'hook.type': 'plugin' });
}

// ==================== Built-in Tool Pre-Tool ====================

function getBuiltinToolContext(toolName: string, toolInput: Record<string, unknown>): Record<string, unknown> {
  const context: Record<string, unknown> = {};

  switch (toolName) {
    case 'Read':
    case 'Write':
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
      if (toolInput.file_path) {
        const filePath = String(toolInput.file_path);
        context['file.path'] = filePath;
        context['file.extension'] = filePath.split('.').pop() || '';
      }
      if (toolInput.notebook_path) {
        context['file.path'] = String(toolInput.notebook_path);
        context['file.extension'] = 'ipynb';
      }
      if (toolInput.old_string) context['edit.old_string_length'] = String(toolInput.old_string).length;
      if (toolInput.new_string) context['edit.new_string_length'] = String(toolInput.new_string).length;
      if (toolInput.replace_all) context['edit.replace_all'] = true;
      break;
    case 'Bash':
      if (toolInput.command) {
        const cmd = String(toolInput.command);
        context['bash.command_length'] = cmd.length;
        const firstWord = cmd.trim().split(/\s+/)[0];
        context['bash.command_type'] = firstWord;
      }
      if (toolInput.timeout) context['bash.timeout'] = toolInput.timeout;
      if (toolInput.run_in_background) context['bash.background'] = true;
      if (toolInput.dangerouslyDisableSandbox) context['bash.sandbox_disabled'] = true;
      break;
    case 'Glob':
      if (toolInput.pattern) context['glob.pattern'] = String(toolInput.pattern);
      if (toolInput.path) context['glob.path'] = String(toolInput.path);
      break;
    case 'Grep':
      if (toolInput.pattern) context['grep.pattern'] = String(toolInput.pattern);
      if (toolInput.glob) context['grep.glob'] = String(toolInput.glob);
      if (toolInput.type) context['grep.type'] = String(toolInput.type);
      if (toolInput.multiline) context['grep.multiline'] = true;
      if (toolInput['-i']) context['grep.case_insensitive'] = true;
      if (toolInput.output_mode) context['grep.output_mode'] = String(toolInput.output_mode);
      break;
    case 'WebFetch':
    case 'WebSearch':
      if (toolInput.url) {
        const url = String(toolInput.url);
        try {
          const parsed = new URL(url);
          context['web.host'] = parsed.hostname;
        } catch {
          context['web.host'] = 'invalid';
        }
      }
      if (toolInput.query) context['web.query_length'] = String(toolInput.query).length;
      if (toolInput.prompt) context['web.prompt_preview'] = String(toolInput.prompt).slice(0, 200);
      break;
    case 'TodoWrite':
      if (Array.isArray(toolInput.todos)) {
        context['todo.count'] = toolInput.todos.length;
      }
      break;
  }

  return context;
}

async function handleBuiltinPreTool(input: HookInput): Promise<void> {
  const toolName = input.tool_name || '';
  if (!BUILTIN_TOOLS.has(toolName)) return;

  setToolStartTime(Date.now());

  await instrumentHook('builtin-pre-tool', async (ctx) => {
    const toolInput = (input.tool_input || {}) as Record<string, unknown>;
    const category = categorizeBuiltinTool(toolName);
    const toolContext = getBuiltinToolContext(toolName, toolInput);

    ctx.addAttributes({
      'builtin.tool': toolName,
      'builtin.category': category,
      'session.id': input.session_id || '',
      ...toolContext,
      ...getPromptLink(input.session_id),
    });

    ctx.logger.info('Built-in tool invoked', {
      'builtin.tool': toolName,
      'builtin.category': category,
    });

    ctx.recordMetric('builtin.invocations', 1, {
      tool: toolName,
      category: category,
    });
  }, { 'hook.trigger': 'PreToolUse', 'hook.type': 'builtin' });
}

// ==================== Agent Pre-Tool ====================

async function handleAgentPreTool(input: HookInput): Promise<void> {
  if (input.tool_name !== 'Agent' && input.tool_name !== 'Task') return;

  const toolInput = input.tool_input as {
    subagent_type?: string;
    prompt?: string;
    description?: string;
    model?: string;
    run_in_background?: boolean;
    resume?: string;
  } | undefined;

  const agentType = toolInput?.subagent_type;
  if (!agentType) return;

  const hookStartMs = Date.now();

  await instrumentHook('agent-pre-tool', async (ctx) => {
    const category = categorizeAgent(agentType);
    const agentInfo = getAgentSourceType(agentType);
    const sourceType = agentInfo.sourceType;
    const isResume = !!toolInput?.resume;
    const isBackground = !!toolInput?.run_in_background;
    const model = toolInput?.model || 'default';

    ctx.addAttributes({
      'integritystudio.agent.type': agentType,
      'integritystudio.agent.category': category,
      'integritystudio.agent.source_type': sourceType,
      'integritystudio.agent.is_resume': isResume,
      'integritystudio.agent.is_background': isBackground,
      'gen_ai.request.model': model,
      'integritystudio.agent.has_prompt': !!toolInput?.prompt,
      'integritystudio.agent.prompt_length': toolInput?.prompt?.length || 0,
      'session.id': input.session_id || '',
      ...getPromptLink(input.session_id),
    });

    if (agentInfo.parentSkill) {
      ctx.addAttribute('integritystudio.agent.parent_skill', agentInfo.parentSkill);
    }

    // A2: GenAI semantic convention attributes
    ctx.addAttributes({
      [GENAI_AGENT_ATTRIBUTES.AGENT_NAME]: agentType,
      [GENAI_AGENT_ATTRIBUTES.AGENT_ID]: agentInfo.parentSkill
        ? `${sourceType}:${agentInfo.parentSkill}:${agentType}`
        : `${sourceType}:${agentType}`,
      'gen_ai.operation.name': 'invoke_agent',
    });

    if (toolInput?.description) {
      ctx.addAttribute(GENAI_AGENT_ATTRIBUTES.AGENT_DESCRIPTION, toolInput.description);
    }

    ctx.logger.info('Agent invoked', {
      'integritystudio.agent.type': agentType,
      'integritystudio.agent.category': category,
      'integritystudio.agent.source_type': sourceType,
      'integritystudio.agent.is_resume': isResume,
      'integritystudio.agent.is_background': isBackground,
      'gen_ai.request.model': model,
    });

    ctx.recordMetric('integritystudio.agent.invocations', 1, {
      type: agentType,
      category: category,
      source_type: sourceType,
      model: model,
      is_resume: String(isResume),
      is_background: String(isBackground),
    });

    // A4: Estimated input tokens metric (4 chars/token approximation)
    const estimatedInputTokens = Math.ceil((toolInput?.prompt?.length || 0) / 4);
    ctx.recordMetric('gen_ai.usage.input_tokens', estimatedInputTokens, { type: agentType });

    // Save pending agent context for consolidated invoke_agent span
    const sessionId = input.session_id || '';
    const agentId = agentInfo.parentSkill
      ? `${sourceType}:${agentInfo.parentSkill}:${agentType}`
      : `${sourceType}:${agentType}`;
    const createSpanId = generateHex(SPAN_ID_BYTES);
    // Capture the dispatching span's SpanContext so the synthesized invoke_agent
    // span (in its own trace) can link back to it at creation (OBP6). Only carry
    // it when valid — when OTel is inactive spanContext() is the all-zero invalid
    // context, which must not become a link target.
    const triggerCtx = ctx.span.spanContext();
    const trigger = otelApi.trace.isSpanContextValid(triggerCtx)
      ? { triggerTraceId: triggerCtx.traceId, triggerSpanId: triggerCtx.spanId, triggerTraceFlags: triggerCtx.traceFlags }
      : {};
    savePendingAgent({
      sessionId,
      agentName: agentType,
      agentId,
      startTimeMs: hookStartMs,
      traceId: generateHex(TRACE_ID_BYTES),
      invokeSpanId: generateHex(SPAN_ID_BYTES),
      createSpanId,
      isFirstSeen: markFirstSeen(sessionId, agentType, createSpanId),
      isBackground,
      ...trigger,
      preToolAttrs: {
        'gen_ai.operation.name': 'invoke_agent',
        'gen_ai.agent.name': agentType,
        'gen_ai.agent.id': agentId,
        'session.id': sessionId,
        'integritystudio.agent.source_type': sourceType,
        'integritystudio.agent.is_resume': isResume,
        'integritystudio.agent.is_background': isBackground,
        'gen_ai.request.model': model,
        ...(agentInfo.parentSkill ? { 'integritystudio.agent.parent_skill': agentInfo.parentSkill } : {}),
        ...(toolInput?.description ? { 'gen_ai.agent.description': toolInput.description } : {}),
      },
      pendingToolSpans: [],
    });

    const flags = [
      isResume ? 'RESUME' : 'NEW',
      isBackground ? 'BG' : 'FG',
      model !== 'default' ? model.toUpperCase() : '',
    ].filter(Boolean).join(',');
    trackInvocation('agent', input.session_id || 'default', `${agentType}\t${category}\t${sourceType}`, 'STARTED', flags);

    const bgIndicator = isBackground ? ' (background)' : '';
    const resumeIndicator = isResume ? ' [resume]' : '';
    const modelIndicator = model !== 'default' ? ` @${model}` : '';
    console.error(`[Agent] ${agentType}${modelIndicator}${bgIndicator}${resumeIndicator} [${category}] (${sourceType})`);

    if (toolInput?.description) {
      const desc = toolInput.description.length > THRESHOLDS.ERROR_MESSAGE_TRUNCATE
        ? `${toolInput.description.slice(0, THRESHOLDS.ERROR_MESSAGE_TRUNCATE)}…`
        : toolInput.description;
      console.error(`   ${desc}`);
    }
  }, { 'hook.trigger': 'PreToolUse', 'hook.type': 'agent' });
}

// ==================== Prompt Link Helper ====================

function getPromptLink(sessionId?: string): Record<string, string> {
  if (!sessionId) return {};
  const promptCtx = loadPromptContext(sessionId);
  if (!promptCtx) return {};
  return {
    'prompt.trace_id': promptCtx.traceId,
    'prompt.span_id': promptCtx.spanId,
  };
}

// ==================== Main Handler ====================

export async function handlePreTool(input: HookInput, subType?: string): Promise<void> {
  const toolName = input.tool_name || '';

  if (subType === 'mcp' || toolName.startsWith('mcp__')) {
    await handleMcpPreTool(input);
  } else if (subType === 'plugin' || toolName === 'Skill') {
    await handlePluginPreTool(input);
  } else if (subType === 'agent' || toolName === 'Agent' || toolName === 'Task') {
    await handleAgentPreTool(input);
  } else if (subType === 'builtin' || BUILTIN_TOOLS.has(toolName)) {
    await handleBuiltinPreTool(input);
  }
}
