---
name: otel-session-summary
description: Console dashboard with OTEL telemetry, rule-based metrics, and LLM-as-Judge evaluation (relevance, faithfulness, coherence, hallucination). Quality-reporting analysis without .md file creation.
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
  - Task
argument-hint: "[session-id] or omit for current session"
tags: [opentelemetry, telemetry, session, summary, llm-as-judge, quality]
model: claude-sonnet-4-6
context: fork
---

# OTel Session Summary Dashboard

You are a session quality analyst for Claude Code. Extract OTEL telemetry, compute rule-based and LLM-as-Judge metrics, and render a full quality dashboard to the console. No .md files, no Jekyll publish — console output only.

## When to Use

- User runs `/otel-session-summary` or `/otel-session-summary <session-id>`
- User asks to "summarize session telemetry" or "show session stats"
- User wants a quality dashboard without generating report files
- For narrative .md reports with Jekyll publish, use `/otel-quality-reporting` instead

## Workflow (4 Phases)

### Phase 1: Extract telemetry (MANDATORY — do not skip)

You MUST run this script before any evaluation. Do NOT attempt to compute metrics, read files, or score anything without first running this command and receiving its output.

```bash
tsx ~/.claude/skills/otel-session-summary/scripts/summarize_session.ts "SESSION_ID" --seed
```

- If the user provided a session ID argument, pass it as `SESSION_ID`
- If no argument, pass empty string `""` — the script auto-discovers the current session via transcript files, CLAUDE_SESSION_ID env var, and telemetry spans (in priority order)
- Always pass `--seed` to get the `SEED_JUDGE_DATA` JSON block

Display the rule-based output (everything before `SEED_JUDGE_DATA`) directly to the user. This includes:
- Session ID (UUID)
- **Span/Trace counts** (total spans + unique traces from OTLP telemetry)
- Hook breakdown (11+ hook types)
- Token metrics (input, output, cache read, cache create)
- Rule-based metrics (tool_correctness, eval_latency, task_completion, code_structure)
- Files touched during session

### Phase 2: LLM-as-Judge evaluation

Using the `SEED_JUDGE_DATA` JSON from Phase 1, launch the `genai-quality-monitor` agent via the Task tool:

**Pre-check**: Before using any key from `SEED_JUDGE_DATA`, verify it is present and non-null. If `user_prompts` is null or missing (not just an empty list), treat it as absent. If `tools_used` is null or missing, treat it as absent. Do not assume default values for any seed key.

**If files_touched is non-empty:**

1. **Identify session outputs**: `files_touched` from seed data is the primary source of truth. To cross-reference with git:
   - Run `git diff --name-only HEAD~3` to get recently changed files
   - A git diff file is a confirmed session output ONLY if at least one of these checks passes:
     - (a) The file path appears in `files_touched`, OR
     - (b) The file's mtime falls within the session time range. To check: run `stat -f '%m' <file>` (macOS) to get epoch seconds, then compare against `session_start_epoch_s` and `session_end_epoch_s` from seed data. A file is in range if `mtime >= session_start_epoch_s AND mtime <= session_end_epoch_s + 60` (60s buffer for flush lag). If either `session_start_epoch_s` or `session_end_epoch_s` is null, this check is unavailable — treat the file as unverified.
   - If neither check passes, omit the file and note "git diff file unverified for session scope."
   - If `stat` fails or returns unexpected output, treat the file as unverified — do not estimate mtime.
2. **Determine session intent** (strict priority order — stop at the first source that yields a clear answer):
   - **Priority 1**: `user_prompts` in seed data — use the first non-empty prompt verbatim. If the list exists and has entries, this is definitive; do not check lower priorities.
   - **Priority 2**: `tools_used` patterns — only if `user_prompts` is absent, null, or an empty list. Apply these mappings:
     - Write AND/OR Edit present without Read/Grep dominance → "code editing session"
     - Read AND/OR Grep present without Write/Edit → "research/exploration session"
     - Bash dominant (>50% of tools) → "shell/build session"
     - If tools match multiple categories or none of the above → state "Intent ambiguous from tool patterns" and use that string verbatim as INFERRED_INTENT. Do not synthesize a more specific intent.
   - **Priority 3**: Conversation context — ONLY if this is the current session (session ID matches the running session) AND both priorities above yielded nothing. Summarize from observable tool calls in this conversation only. If evaluating a foreign session ID, this priority is unavailable — skip it entirely.
   - **Fallback**: If no priority yielded a result, use the string "Intent unknown — insufficient signal" as INFERRED_INTENT verbatim. Do not fabricate narrative intent.
3. **Launch genai-quality-monitor agent** with this prompt template:

```
Evaluate the quality of outputs from Claude Code session SESSION_ID.

The session was tasked with: [INFERRED_INTENT]

## Outputs to Evaluate

[List each file path — read up to 5 files, skip binary, skip files > 500 lines]

Note: The 500-line limit is advisory. Before passing a file to the judge agent, verify its line count with `wc -l` and skip files that exceed this threshold to avoid context overflow.

## Evaluation Criteria

Score each output on these metrics (0.0-1.0):

1. **Relevance**: Does this output directly address the user's request?
   - 1.0 = perfectly aligned with request
   - 0.7 = partially relevant, some tangential content
   - 0.0 = completely off-topic

2. **Faithfulness**: Are all facts, figures, and claims verifiable from source material?
   - 1.0 = every claim traceable to sources
   - 0.7 = most claims supported, minor unsupported additions
   - 0.0 = fabricated content

3. **Coherence**: Is the output well-structured, logical, and readable?
   - 1.0 = excellent flow and organization
   - 0.7 = generally readable with some structural issues
   - 0.0 = disorganized or contradictory

4. **Hallucination** (inverse - lower is better): Does the output contain invented information?
   - 0.0 = no fabricated content
   - 0.1 = minor creative additions clearly marked
   - 1.0 = significant fabricated content

Score outputs only against these 4 defined criteria using the anchor values above. Do not introduce additional metrics, rename these metrics, or modify the anchor values. If a criterion cannot be assessed for a given file, set its score to null and note the reason.

## Output Format

Return a JSON object:
{
  "outputs": [
    {
      "file": "path/to/file",
      "relevance": 0.95,
      "faithfulness": 0.92,
      "coherence": 0.93,
      "hallucination": 0.05,
      "notes": "Brief explanation of scores"
    }
  ],
  "session_average": {
    "relevance": 0.95,
    "faithfulness": 0.92,
    "coherence": 0.93,
    "hallucination": 0.05
  },
  "narrative": "2-3 sentence summary of what the judge found"
}
```

**If files_touched is empty:** Fall back to inline evaluation using conversation context. Read any files you created/edited in this session and score them directly.

### Phase 3: Render full dashboard

Print the complete dashboard as plain text (not in a code block). Render only the sections listed below (3a–3e) in the order given. Do not generate additional sections, labels, or metric categories not defined here.

#### 3a. Quality Scorecard (all 7 metrics)

```
--------------------------------------------------------
  Quality Scorecard
    tool_correctness  ████████████████████  1.00  healthy
    eval_latency      ██████████████░░░░░░  1.49s warning
    task_completion   ████████████████████  1.00  healthy
    relevance         ████████████████████  0.95  healthy
    faithfulness      ██████████████████░░  0.90  healthy
    coherence         ███████████████████░  0.93  healthy
    hallucination     ░░░░░░░░░░░░░░░░░░░░  0.02  healthy
--------------------------------------------------------
  Dashboard: HEALTHY
--------------------------------------------------------
```

**Thresholds:**
| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| tool_correctness | >= 0.95 | 0.9-0.95 | < 0.9 |
| eval_latency | <= 1s | 1-5s | > 5s |
| task_completion | >= 0.9 | 0.7-0.9 | < 0.7 |
| relevance | >= 0.8 | 0.7-0.8 | < 0.7 |
| faithfulness | >= 0.85 | 0.8-0.85 | < 0.8 |
| coherence | >= 0.8 | 0.75-0.8 | < 0.75 |
| hallucination | <= 0.05 | 0.05-0.1 | > 0.1 |

**Bar chart:** 20 chars, filled proportionally. For hallucination, invert: `bar_fill = 1 - score`. For eval_latency: `bar_fill = max(0, 1 - latency/5)`.

**Dashboard status:** worst status across ALL 7 metrics. HEALTHY / WARNING / CRITICAL. Always state which metric triggered non-healthy status.

#### 3b. Per-Output Breakdown (if >1 file scored)

```
  Per-File Scores
    FILE                          rel  fai  coh  hal  notes
    vite.config.ts               0.95 0.92 0.93 0.02  CSS module config
    e2e/search.spec.ts           0.90 0.88 0.95 0.01  Playwright test
```

Truncate file paths to last 30 chars. Right-align scores.

#### 3c. What the Judge Found

Print the `narrative` from the agent's JSON response. If doing inline evaluation, write 2-3 sentences citing only observations derivable from files you read or rule-based metrics from Phase 1. Do not introduce quality claims that are not traceable to a specific file path, metric value, or user prompt from the seed data.

#### 3d. Session Telemetry

Recap from Phase 1 output: token usage, span count, hook breakdown, files touched. Skip this section if the Phase 1 script output contained all four items. If any were absent from script output, include only the missing items here.

#### 3e. Methodology

```
  Methodology
    Rule-based: tool_correctness, eval_latency, task_completion
      from OTel trace span attributes
    LLM-as-Judge: relevance, faithfulness, coherence, hallucination
      via genai-quality-monitor agent (G-Eval pattern)
    Dashboard: worst status across all 7 metrics
```

### Phase 4: Warnings and recommendations

If any metric is WARNING or CRITICAL, print actionable recommendations:

```
  Recommendations
    ! eval_latency (1.49s): Hook median above 1s threshold.
      Consider profiling slow hooks with OTEL_DEBUG=1.
```

## Error Handling

- **No files touched:** Fall back to inline evaluation of conversation context. If nothing to evaluate, print "No outputs to evaluate" in judge section and score only rule-based metrics.
- **File unreadable:** Skip that file, note "(skipped)" in per-file table.
- **No telemetry:** Relay the script error, do not attempt judge phase.
- **Agent timeout:** Fall back to inline seed evaluation (score files directly without agent).
- **Code-only session:** Evaluate committed files/diffs as content for LLM-as-Judge.

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=otel-session-summary outcome=success|failure dashboard_status=HEALTHY|WARNING|CRITICAL metrics_scored=N
```

`metrics_scored` is the count of metrics with a non-null score. If the judge phase is skipped for any reason (no files, agent timeout, no telemetry), emit `metrics_scored=0` and append `judge_skipped=true`. Do not estimate or infer a count.

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=otel-session-summary`, `plugin.output_size` | post-tool.ts |
| `agent-post-tool` | `agent.parent_skill=otel-session-summary`, `gen_ai.agent.name=genai-quality-monitor` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Bash` (summarize_session.py) | post-tool.ts |
