# Aggregate Provenance Report Template

Jekyll-compatible markdown report for multi-session output provenance analysis. Always includes LLM-as-Judge evaluation.

## Frontmatter

```yaml
---
layout: single
author_profile: true
classes: wide
title: "{TITLE}"
date: {YYYY-MM-DD}
categories: [telemetry]
tags: [opentelemetry, observability, session-analysis, llm-as-judge, quality-metrics, aggregate, multi-session, provenance, {ADDITIONAL_TAGS}]
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

Write a storytelling-style opening about the multi-session arc. Describe the journey from first research to final deliverable. Mention how many sessions and how much calendar time was involved.

**Good:** "How does a 1,463-line frontend design spec come into existence? Not in a single sitting. Over eight days, six Claude Code sessions wove together platform research, codebase audits, and UX pattern extraction -- then distilled it all into a production specification."

**Bad:** "This report aggregates telemetry data from multiple Claude Code sessions."

### Quality Scorecard

```markdown
## Quality Scorecard

Seven metrics. Three from rule-based telemetry analysis across all {N} contributing sessions, four from LLM-as-Judge evaluation of the {M} deliverable documents.

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

Same rules as otel-quality-reporting:
- Standard metrics (higher is better): `filled = round(score * 20)`, `filled chars = filled * "█"`, `empty chars = (20 - filled) * "░"`
- Hallucination (lower is better): invert -- `filled = round((1 - score) * 20)`
- Latency: normalize -- `filled = max(0, round((1 - min(latency, 5) / 5) * 20))`
- Metric name: left-padded to 16 chars
- Bar: exactly 20 chars
- Score: right-aligned, 2 decimal places
- Status: healthy/warning/critical

### Session Timeline (REQUIRED for aggregate reports)

```markdown
## Session Timeline

\```
{DATE} {TIME} ━━━ S{N}: {ROLE} ({SPANS} spans, {DURATION}) ━━━ {END_TIME}
{DATE} {TIME} ━━ S{N}: {ROLE} ({SPANS} spans, {DURATION}) ━━ {END_TIME}
                                      ^ {EVENT_MARKER}
\```
```

Use `━` for timeline bars. Group by date. Mark significant events (commits, phase transitions).

### Per-Output Breakdown

```markdown
### Per-Output Breakdown

| Document | Relevance | Faithfulness | Coherence | Hallucination |
|----------|-----------|-------------|-----------|---------------|
| `{FILE_1}` ({LINES} lines) | {SCORE} | {SCORE} | {SCORE} | {SCORE} |
| ...      | ...       | ...         | ...       | ...           |
| **Session Average** | **{AVG}** | **{AVG}** | **{AVG}** | **{AVG}** |
```

### What the Judge Found

Narrative highlights specific to this provenance analysis:
- Which output scored highest/lowest and why
- Cross-document consistency (do references between docs check out?)
- Code-level verification results (line references, function names, interface fields)
- Any hallucination instances and their nature
- How research quality propagated into the design deliverable

### Session Telemetry (Aggregate + Per-Session)

```markdown
## Session Telemetry

### Aggregate

| Metric | Value |
|--------|-------|
| Contributing Sessions | {COUNT} |
| Date Range | {START_DATE} to {END_DATE} |
| Primary Model | {MODEL} ({LLM_CALLS} calls) |
| Total Spans | {COUNT} |
| Tool Calls | {COUNT} (success: {COUNT}, failed: {COUNT}) |
| Input Tokens | {FORMATTED_NUMBER} |
| Output Tokens | {FORMATTED_NUMBER} |
| Cache Read Tokens | {FORMATTED_NUMBER} |

### Per-Session Breakdown

| # | Session ID | Phase | Duration | Spans | Tool Calls | Role |
|---|-----------|-------|----------|-------|------------|------|
| S1 | `{SHORT_ID}` | {PHASE} | {DURATION} | {COUNT} | {COUNT} | {DESCRIPTION} |
```

### Tool Usage Table

```markdown
### Tool Usage (Aggregate)

| Tool | Count | Sessions Used In |
|------|-------|-----------------|
| {TOOL} | {COUNT} | {SESSION_LIST} |
```

### Token Usage by Phase

Group sessions into phases (research, design, implementation, review, commit) and show token usage per phase.

### Per-Session Rule-Based Metrics

```markdown
## Rule-Based Metrics (Per Session)

| Session | tool_correctness | eval_latency (ms) | task_completion | Spans | Tool Spans |
|---------|------------------|--------------------|-----------------|-------|------------|
| S1 `{ID}` | {SCORE} | {MS} | {SCORE} | {COUNT} | {COUNT} |
```

### Methodology Notes

Required for aggregate reports:
- How sessions were discovered (keyword matching, temporal correlation, agent description matching)
- Which telemetry files were scanned
- Any attribution caveats (token metrics without session.id, evaluation pipeline gaps)
- Time zone conventions used
- Cross-document verification methodology (if LLM-as-Judge checked code references)
