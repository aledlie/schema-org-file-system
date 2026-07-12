# Report Template

Jekyll-compatible markdown report for session quality analysis. LLM-as-Judge evaluation is always included.

## Frontmatter

```yaml
---
layout: single
author_profile: true
classes: wide
title: "{TITLE}"
date: {YYYY-MM-DD}
categories: [telemetry]
tags: [opentelemetry, observability, session-analysis, llm-as-judge, quality-metrics, {ADDITIONAL_TAGS}]
header:
  image: /assets/images/cover-reports.png
url: https://www.aledlie.com/reports/{YYYY-MM-DD}-{SLUG}/
permalink: /reports/{YYYY-MM-DD}-{SLUG}/
schema_type: analysis-article
schema_genre: "Session Report"
---
```

## Report Body Structure

### Opening Narrative (2-3 sentences)

Write a storytelling-style opening that describes what the session set out to accomplish. Avoid template language -- make it specific to the session's actual work.

**Good:** "What does it take for an AI to translate not just words, but *voice*? On a quiet Wednesday evening in Austin, a Claude Code session set out to answer that question."

**Bad:** "This report analyzes the telemetry data from a Claude Code session."

### Quality Scorecard

```markdown
## Quality Scorecard

Seven metrics. Three from rule-based telemetry analysis, four from LLM-as-Judge evaluation of the session outputs. Together they form a complete picture of how well this session did its job.

### The Headline

\```
 RELEVANCE       {BAR}  {SCORE}   {STATUS}
 FAITHFULNESS    {BAR}  {SCORE}   {STATUS}
 COHERENCE       {BAR}  {SCORE}   {STATUS}
 HALLUCINATION   {BAR}  {SCORE}   {STATUS}  (lower is better)
 TOOL ACCURACY   {BAR}  {SCORE}   {STATUS}
 EVAL LATENCY    {BAR}  {LATENCY} {STATUS}
 TASK COMPLETION {BAR}  {SCORE}   {STATUS}
\```

**Dashboard status: {OVERALL_STATUS}** -- {EXPLANATION}
```

### ASCII Bar Generation

For each metric, generate a 20-character bar:

- **Standard metrics** (higher is better): `filled = round(score * 20)`, use `█` for filled, `░` for empty
- **Hallucination** (lower is better): invert -- `filled = round((1 - score) * 20)`
- **Latency**: normalize -- `filled = max(0, round((1 - min(latency, 5) / 5) * 20))`

Align columns:
- Metric name: left-padded to 16 chars
- Bar: exactly 20 chars
- Score: right-aligned, 2 decimal places (or unit for latency)
- Status: healthy/warning/critical

### How We Measured

```markdown
### How We Measured

The first three metrics -- tool correctness, evaluation latency, and task completion -- were derived automatically from OpenTelemetry trace spans. Every tool call emits a span; the rule engine checks whether it succeeded and how long it took.

The content quality metrics come from **LLM-as-Judge evaluation** -- a G-Eval pattern where an AI judge reads the session's outputs and scores along four criteria: relevance, faithfulness, coherence, and hallucination. {SPECIFIC_DETAIL_ABOUT_WHAT_WAS_EVALUATED}
```

### Per-Output Breakdown

Always include a per-output table. For content sessions, each file is a row. For code sessions, each committed file or significant diff is a row.

```markdown
### Per-Output Breakdown

Each output was evaluated independently, then aggregated:

| Document | Relevance | Faithfulness | Coherence | Hallucination |
|----------|-----------|-------------|-----------|---------------|
| {FILE_1} ({LINES} lines) | {SCORE} | {SCORE} | {SCORE} | {SCORE} |
| ...      | ...       | ...         | ...       | ...           |
| **Session Average** | **{AVG}** | **{AVG}** | **{AVG}** | **{AVG}** |
```

### What the Judge Found

Narrative highlights. Pick out the most interesting findings:
- Which output scored highest/lowest and why
- Specific examples of faithfulness (data preserved correctly, code correctness)
- Any hallucination instances -- were they deliberate creative choices vs errors?
- Notable quality observations specific to this session's work

### Session Telemetry

```markdown
## Session Telemetry

| Metric | Value |
|--------|-------|
| Session ID | `{UUID}` |
| Date | {DATE} |
| Model | {MODEL} |
| Total Spans | {COUNT} |
| Tool Calls | {COUNT} (success: {COUNT}, failed: {COUNT}) |
| Input Tokens | {FORMATTED_NUMBER} |
| Output Tokens | {FORMATTED_NUMBER} |
| Cache Read Tokens | {FORMATTED_NUMBER} |
| Hooks Observed | {COMMA_SEPARATED_LIST} |
```

### Methodology Notes

Brief section explaining:
- What telemetry data was available for this session
- How outputs were identified for LLM-as-Judge evaluation
- Any caveats (e.g., "task_completion reflects telemetry tracking ratio, not actual deliverable status")
