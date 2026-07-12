/**
 * User Prompt Handler
 * Handles UserPromptSubmit events (skill activation)
 */

import { instrumentHook, getTraceId } from '../lib/otel-monitor.js';
import { THRESHOLDS, TRUNCATION_SUFFIX } from '../lib/constants.js';
import { getSessionUsage } from '../lib/context-tracker.js';
import { savePromptContext } from '../lib/trace-context.js';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

interface HookInput {
  session_id?: string;
  transcript_path?: string;
  cwd?: string;
  permission_mode?: string;
  prompt?: string;
}

interface PromptTriggers {
  keywords?: string[];
  intentPatterns?: string[];
}

interface SkillRule {
  type: 'guardrail' | 'domain';
  enforcement: 'block' | 'suggest' | 'warn';
  priority: 'critical' | 'high' | 'medium' | 'low';
  promptTriggers?: PromptTriggers;
}

interface SkillRules {
  version: string;
  skills: Record<string, SkillRule>;
}

interface MatchedSkill {
  name: string;
  matchType: 'keyword' | 'intent';
  config: SkillRule;
}

export async function handleUserPrompt(input: HookInput): Promise<void> {
  await instrumentHook('skill-activation-prompt', async (ctx) => {
    ctx.logger.debug('Skill activation check starting');

    const prompt = (input.prompt || '').toLowerCase();

    ctx.addAttribute('session.id', input.session_id || '');
    ctx.addAttribute('prompt.length', prompt.length);
    if (prompt.length > 0) {
      const preview = prompt.length > THRESHOLDS.PROMPT_PREVIEW_LENGTH
        ? prompt.slice(0, THRESHOLDS.PROMPT_PREVIEW_LENGTH) + TRUNCATION_SUFFIX
        : prompt;
      ctx.addAttribute('prompt.preview', preview);
    }

    // Track context usage from API data
    if (input.session_id) {
      const usage = getSessionUsage(input.session_id, input.cwd);
      if (usage) {
        ctx.addAttributes({
          'context.total_tokens': usage.totalContextTokens,
          'context.utilization_percent': usage.utilizationPercent,
          'context.free_space': usage.freeSpace,
          'context.input_tokens': usage.inputTokens,
          'context.cache_read_tokens': usage.cacheReadTokens,
          'context.message_count': usage.messageCount,
          // Breakdown by type
          'context.breakdown.system_prompt': usage.breakdown.system_prompt,
          'context.breakdown.system_tools': usage.breakdown.system_tools,
          'context.breakdown.memory_files': usage.breakdown.memory_files,
          'context.breakdown.mcp': usage.breakdown.mcp,
          'context.breakdown.skills': usage.breakdown.skills,
          'context.breakdown.agents': usage.breakdown.agents,
          'context.breakdown.messages': usage.breakdown.messages,
        });

        ctx.recordMetric('session.context_tokens', usage.totalContextTokens);
        ctx.recordMetric('session.context_utilization', usage.utilizationPercent);
        ctx.recordMetric('session.free_space', usage.freeSpace);

        // Cache effectiveness metrics
        const hitDenom = usage.inputTokens + usage.cacheReadTokens;
        if (hitDenom > 0) {
          const cacheHitRate = usage.cacheReadTokens / hitDenom;
          ctx.addAttribute('context.cache_hit_rate', Math.round(cacheHitRate * 1000) / 1000);
          ctx.recordMetric('session.cache_hit_rate', cacheHitRate);
        }
        if (usage.totalContextTokens > 0) {
          const cacheEfficiency = usage.cacheReadTokens / usage.totalContextTokens;
          ctx.addAttribute('context.cache_efficiency', Math.round(cacheEfficiency * 1000) / 1000);
          ctx.recordMetric('session.cache_efficiency', cacheEfficiency);
        }

        ctx.logger.debug('Context usage tracked', {
          'context.total': usage.totalContextTokens,
          'context.utilization': usage.utilizationPercent,
          'context.free': usage.freeSpace,
          'breakdown.system_prompt': usage.breakdown.system_prompt,
          'breakdown.system_tools': usage.breakdown.system_tools,
          'breakdown.memory_files': usage.breakdown.memory_files,
          'breakdown.messages': usage.breakdown.messages,
        });
      }
    }

    // Save trace context for downstream tool hooks to link back to this prompt
    if (input.session_id) {
      const traceId = getTraceId();
      const spanId = ctx.span.spanContext().spanId;
      if (traceId) {
        savePromptContext(input.session_id, traceId, spanId);
      }
    }

    if (!prompt) {
      ctx.logger.debug('No prompt provided');
      return;
    }

    // Load skill rules from multiple locations
    const locations = [
      join(process.env.CLAUDE_PROJECT_DIR || `${process.env.HOME}/project`, '.claude', 'skills', 'skill-rules.json'),
      join(process.env.HOME || '', '.claude', 'skills', 'skill-rules.json'),
    ];

    let rulesPath: string | undefined;
    for (const loc of locations) {
      if (existsSync(loc)) {
        rulesPath = loc;
        break;
      }
    }

    if (!rulesPath) {
      ctx.logger.debug('No skill-rules.json found');
      ctx.addAttribute('rules.found', false);
      return;
    }

    ctx.addAttribute('rules.found', true);
    ctx.addAttribute('rules.path', rulesPath);

    let rules: SkillRules;
    try {
      rules = JSON.parse(readFileSync(rulesPath, 'utf-8'));
      ctx.addAttribute('rules.version', rules.version);
      ctx.addAttribute('rules.skill_count', Object.keys(rules.skills).length);
    } catch (error) {
      ctx.logger.error('Failed to parse skill-rules.json', {
        error: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    const matchedSkills: MatchedSkill[] = [];

    // Check each skill for matches
    for (const [skillName, config] of Object.entries(rules.skills)) {
      const triggers = config.promptTriggers;
      if (!triggers) continue;

      // Keyword matching
      if (triggers.keywords) {
        const keywordMatch = triggers.keywords.some((kw) => prompt.includes(kw.toLowerCase()));
        if (keywordMatch) {
          matchedSkills.push({ name: skillName, matchType: 'keyword', config });
          ctx.recordEvent('skill-keyword-match', { skill: skillName, type: config.type });
          continue;
        }
      }

      // Intent pattern matching (with ReDoS protection)
      if (triggers.intentPatterns) {
        const testPrompt = prompt.slice(0, THRESHOLDS.MAX_PROMPT_TEST_LENGTH);

        const intentMatch = triggers.intentPatterns.some((pattern) => {
          if (pattern.length > THRESHOLDS.MAX_PATTERN_LENGTH) {
            ctx.logger.warn('Skipping oversized intent pattern', { skill: skillName, len: pattern.length });
            return false;
          }
          // Reject patterns with nested quantifiers (ReDoS vectors)
          if (/(\+|\*|\{)\)(\+|\*|\{|\?)/.test(pattern)) {
            ctx.logger.warn('Skipping unsafe regex pattern (ReDoS risk)', { skill: skillName, pattern });
            return false;
          }
          // Reject quantified alternation groups (overlapping alternatives cause exponential backtracking)
          if (/\([^)]*\|[^)]*\)[+*?]/.test(pattern)) {
            ctx.logger.warn('Skipping unsafe regex pattern (quantified alternation)', { skill: skillName, pattern });
            return false;
          }
          // Reject nested capturing groups with quantifiers: (...(...)...)+ or similar
          if (/\((?:[^()]*\([^()]*\)[^()]*)+\)[+*?]/.test(pattern)) {
            ctx.logger.warn('Skipping unsafe regex pattern (nested group quantifier)', { skill: skillName, pattern });
            return false;
          }
          // Reject {n,m} quantifiers on groups (bounded but still exponential in some engines)
          if (/\([^)]*\)\{\d+,\d*\}/.test(pattern)) {
            ctx.logger.warn('Skipping unsafe regex pattern (quantified group with repetition)', { skill: skillName, pattern });
            return false;
          }
          try {
            const regex = new RegExp(pattern, 'i');
            return regex.test(testPrompt);
          } catch {
            return false;
          }
        });
        if (intentMatch) {
          matchedSkills.push({ name: skillName, matchType: 'intent', config });
          ctx.recordEvent('skill-intent-match', { skill: skillName, type: config.type });
        }
      }
    }

    // Record metrics
    ctx.addAttribute('matches.total', matchedSkills.length);
    ctx.recordMetric('skill_activation.matches', matchedSkills.length);

    // Count by priority
    const byPriority = {
      critical: matchedSkills.filter((s) => s.config.priority === 'critical').length,
      high: matchedSkills.filter((s) => s.config.priority === 'high').length,
      medium: matchedSkills.filter((s) => s.config.priority === 'medium').length,
      low: matchedSkills.filter((s) => s.config.priority === 'low').length,
    };

    ctx.addAttributes({
      'matches.critical': byPriority.critical,
      'matches.high': byPriority.high,
      'matches.medium': byPriority.medium,
      'matches.low': byPriority.low,
    });

    // Count by match type
    const byType = {
      keyword: matchedSkills.filter((s) => s.matchType === 'keyword').length,
      intent: matchedSkills.filter((s) => s.matchType === 'intent').length,
    };

    ctx.recordMetric('skill_activation.keyword_matches', byType.keyword);
    ctx.recordMetric('skill_activation.intent_matches', byType.intent);

    // Generate output if matches found
    if (matchedSkills.length > 0) {
      ctx.logger.info('Skills matched for prompt', {
        'matches.total': matchedSkills.length,
        'skills.names': matchedSkills.map((s) => s.name).join(', '),
      });

      let output = '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';
      output += 'SKILL ACTIVATION CHECK\n';
      output += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';

      // Group by priority
      const critical = matchedSkills.filter((s) => s.config.priority === 'critical');
      const high = matchedSkills.filter((s) => s.config.priority === 'high');
      const medium = matchedSkills.filter((s) => s.config.priority === 'medium');
      const low = matchedSkills.filter((s) => s.config.priority === 'low');

      if (critical.length > 0) {
        output += 'CRITICAL SKILLS (REQUIRED):\n';
        critical.forEach((s) => (output += `  → ${s.name}\n`));
        output += '\n';
      }

      if (high.length > 0) {
        output += 'RECOMMENDED SKILLS:\n';
        high.forEach((s) => (output += `  → ${s.name}\n`));
        output += '\n';
      }

      if (medium.length > 0) {
        output += 'SUGGESTED SKILLS:\n';
        medium.forEach((s) => (output += `  → ${s.name}\n`));
        output += '\n';
      }

      if (low.length > 0) {
        output += 'OPTIONAL SKILLS:\n';
        low.forEach((s) => (output += `  → ${s.name}\n`));
        output += '\n';
      }

      output += 'ACTION: Use Skill tool BEFORE responding\n';
      output += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';

      console.log(output);
    } else {
      ctx.logger.debug('No skill matches for prompt');
    }
  });
}
