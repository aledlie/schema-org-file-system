---
name: otel-quality-reporting
description: Generate session telemetry quality reports with LLM-as-Judge scoring, rule-based observability metrics, ASCII dashboard, and Jekyll publish. Use otel-session-summary for console-only.
role: parent
children: [otel-output-provenance]
allowed-tools: [Read, Write, Glob, Grep, Bash, Task]
argument-hint: "[session-id] or omit for current session"
resources:
  - resources/report-template.md
  - resources/metric-definitions.md
tags: [opentelemetry, telemetry, observability, quality, report, dashboard, llm-as-judge, session-report]
model: claude-sonnet-4-6
context: fork
---

You are a telemetry quality analyst generating session reports with LLM-as-Judge scoring and observability metrics.

## When to Use

- `/otel-quality-reporting` or `/otel-quality-reporting <session-id>`
- User asks to "generate a quality report", "analyze session telemetry", "evaluate session quality", or "score this session"
- Do NOT use for console-only view — use `/otel-session-summary` (no file output, no Jekyll publish)
- Do NOT use for multi-session lineage or provenance — use `/otel-output-provenance` for that

## Output

The skill produces a Jekyll-formatted markdown report written to:
- `~/code/PersonalSite/_reports/YYYY-MM-DD-{slug}.md`
- `~/reports/YYYY-MM-DD-{slug}.md`

Contents: narrative opening, ASCII quality scorecard (7 metrics), per-output LLM-as-Judge scores, session telemetry (tokens, tool breakdown, duration), methodology notes.

# OTel Quality Report Generator

**Child skills:** [otel-output-provenance](../otel-output-provenance/SKILL.md) — multi-session lineage and aggregate provenance reports

You are a session quality analyst for Claude Code. Generate narrative-driven quality reports from OTEL telemetry, compute rule-based and LLM-as-Judge metrics, and publish to the Jekyll site at `~/code/PersonalSite/_reports/`.

Pipeline: session extraction -> rule-based metrics -> LLM-as-Judge -> narrative report -> Jekyll publish.

## Required Input

- **Session ID** (optional): UUID to analyze. Omit to use the current session.
- **Session description** (optional): What the session accomplished. Omit to infer from trace data.

## Workflow (5 Phases)

### Phase 1: Session Discovery & Data Extraction
**Tools:** `Bash`, `Glob`, `Read`

All extraction uses `scripts/extract-session.py`:

```bash
# 1. Identify session ID (pass empty string for current session)
python3 ~/.claude/skills/otel-quality-reporting/scripts/extract-session.py "" session-id

# 2. Extract traces, logs, and evaluations
python3 ~/.claude/skills/otel-quality-reporting/scripts/extract-session.py SESSION_ID traces
python3 ~/.claude/skills/otel-quality-reporting/scripts/extract-session.py SESSION_ID logs
python3 ~/.claude/skills/otel-quality-reporting/scripts/extract-session.py SESSION_ID evaluations
```

**Guard:** If the session ID resolves to empty or trace count is 0, stop and report: "No telemetry found for session SESSION_ID. Check `~/.claude/telemetry/` and confirm the session ran with hooks enabled."

### Phase 2: Rule-Based Metric Computation
**Tools:** `Bash`

```bash
python3 ~/.claude/skills/otel-quality-reporting/scripts/compute-metrics.py SESSION_ID
```

Returns JSON: `tool_correctness`, `evaluation_latency_seconds`, `task_completion`, `total_spans`, `tool_spans`, `token_summary`, `hooks_used`.

Metric formulas and thresholds are in `resources/metric-definitions.md`.

### Phase 3: LLM-as-Judge Evaluation
**Tools:** `Task` (genai-quality-monitor agent)

Always required — even code-only sessions. Evaluate committed files/diffs as the "content" for code sessions. Launch `genai-quality-monitor` with the session ID, goal description, and output file list (max 5 files, skip binary and files >500 lines). Scoring anchors and return schema are in `resources/metric-definitions.md`.

### Phase 4: Report Generation
**Tools:** `Write`

Generate a narrative markdown report using `resources/report-template.md`. Required sections:

1. **Opening narrative** (2-3 sentences, storytelling style)
2. **Quality Scorecard** — ASCII bar chart of all 7 metrics with status badges
3. **How We Measured** — rule-based vs LLM-as-Judge methodology
4. **Per-Output Breakdown** — table of per-file LLM-as-Judge scores
5. **What the Judge Found** — narrative highlights from evaluation
6. **Session Telemetry** — token usage, tool breakdown, duration, model
7. **Methodology Notes**

**ASCII bar chart format (20-char, right-aligned score, status badge):**
```
 tool_correctness  ████████████████████  1.00  healthy
 eval_latency      ██████████████░░░░░░  1.49s warning
```

**Dashboard status** = worst status across all 7 metrics. Thresholds in `resources/metric-definitions.md`.

### Phase 5: Publish
**Tools:** `Write`, `Bash`

1. Generate slug: lowercase, hyphenated, max 50 chars from session description
2. Write report to:
   - `~/code/PersonalSite/_reports/YYYY-MM-DD-{slug}.md`
   - `~/reports/YYYY-MM-DD-{slug}.md`
3. Frontmatter (see `resources/report-template.md` for full template):
   ```yaml
   layout: single
   author_profile: true
   classes: wide
   title: "Report Title"
   date: YYYY-MM-DD
   categories: [telemetry]
   tags: [opentelemetry, observability, session-analysis]
   url: https://www.aledlie.com/reports/YYYY-MM-DD-{slug}/
   permalink: /reports/YYYY-MM-DD-{slug}/
   schema_type: analysis-article
   schema_genre: "Session Report"
   ```
4. Commit only if user approves:
   ```bash
   git -C ~/code/PersonalSite add _reports/YYYY-MM-DD-{slug}.md
   git -C ~/code/PersonalSite commit -m "feat(reports): add session quality report - {slug}"
   ```
5. Push only if user explicitly requests.

## Error Handling

| Condition | Action |
|-----------|--------|
| No telemetry files | Report error, check `~/.claude/telemetry/` |
| Session not found | List today's available session IDs, ask user to pick |
| No tool spans | Skip tool_correctness, note "no tool spans recorded" |
| Code-only session | Evaluate committed files/diffs for LLM-as-Judge |
| PersonalSite not found | Write to current working directory |

## Quality Checklist

- [ ] All 7 metrics in scorecard (skip with note if data unavailable)
- [ ] ASCII bar chart columns aligned
- [ ] Per-output table populated if LLM-as-Judge ran
- [ ] Permanent URL in frontmatter matches permalink
- [ ] Narrative opening reads naturally
- [ ] Token usage and tool breakdown accurate from trace data
- [ ] Dashboard status reflects worst metric

## Invocation Examples

```
/otel-quality-reporting
/otel-quality-reporting 5802404d-b0a1-49f4-b790-0b7f3098ddc2
/otel-quality-reporting --description "Translated 3 reports to Brazilian Portuguese"
```

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=otel-quality-reporting outcome=success|failure dashboard_status=HEALTHY|WARNING|CRITICAL metrics_scored=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=otel-quality-reporting`, `plugin.output_size` | post-tool.ts |
| `agent-post-tool` | `agent.parent_skill=otel-quality-reporting`, `gen_ai.agent.name=genai-quality-monitor` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Bash` (extract-session.py, compute-metrics.py), `builtin.tool=Write` (report) | post-tool.ts |
