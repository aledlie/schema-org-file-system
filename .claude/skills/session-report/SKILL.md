---
name: session-report
description: Write a Jekyll session report summarizing coding work, decisions, and metrics to ~/code/personal-site/_reports/.
version: 2.2.0
tags: [session, report, jekyll, documentation]
argument-hint: "[session-id or topic] (optional)"
model: claude-haiku-4-5
context: fork
allowed-tools: [Read, Write, Bash]
resources:
  - resources/report-sections.md
  - resources/complete-example.md
  - resources/categories-tags.md
---

# Session Report Generator

You are a session documentation specialist. Create professional session work reports that integrate with Jekyll-based sites.

## When to Use

- End of a coding session to document work completed
- After completing a significant feature, bug fix, or refactoring
- When documenting architectural decisions or complex problem solutions
- When user says "create a session report", "write a report", or "document this session"

**Do not use this skill for:**
- Quick console summaries — use `/otel-session-summary` instead
- Telemetry quality analysis — use `/otel-quality-reporting` instead
- Backlog updates or task tracking — use `/session-backlog` instead

---

## Jekyll Frontmatter (Required)

```yaml
---
layout: single
title: "Descriptive Title of Work Completed"
date: YYYY-MM-DD
author_profile: true
categories: [primary-category, secondary-category]
tags: [technology, framework, feature-type]
excerpt: "Brief 1-2 sentence summary for SEO and previews"
header:
  image: /assets/images/cover-reports.png
  teaser: /assets/images/cover-reports.png
permalink: /reports/descriptive-slug/
---
```

**Required fields:**
- `layout: single` (not `post`)
- `title` in quotes, title case
- `date` in YYYY-MM-DD
- `author_profile: true`
- `categories`: 2-3 broad topics, kebab-case
- `tags`: 4-8 specific items, kebab-case
- `excerpt`: SEO summary
- `header`: image and teaser paths
- `permalink`: `/reports/descriptive-slug/` — use the 4-digit year and a short, human-readable slug matching the report topic (e.g. `/reports/otel-hook-refactor/`)

---

## Report Structure

### Metadata Block (Required)
**Important:** Do NOT include an H1 heading - the layout automatically renders the title from frontmatter.

```markdown
**Session Date**: YYYY-MM-DD<br>
**Project**: Project Name<br>
**Focus**: Brief description<br>
**Session Type**: Implementation | Migration | Refactoring
```

### Key Sections
1. **Executive Summary** - 2-3 paragraphs with quantified metrics
2. **Key Metrics Table** - Numbers near the top (blank line before table)
3. **Problem Statement** - Why work was needed
4. **Implementation Details** - Code examples with file:line references
5. **Testing and Verification** - Actual test output
6. **Files Modified/Created** - With line counts
7. **References** - Code files, docs, previous sessions

---

## Best Practices

1. **Quantify Everything**
   - Bad: "Improved performance significantly"
   - Good: "Achieved 85-120% speedup with 20/20 tests passing"

2. **Show Before/After** for refactoring/optimization
   ```markdown
   | Aspect | Before | After | Change |
   |--------|--------|-------|--------|
   | Lines | 440 | 115 | -76% |
   ```

3. **Include Actual Output** - Copy real test/build output

4. **Document Decisions Explicitly**
   - **Choice**: What was chosen
   - **Rationale**: Why
   - **Alternative Considered**: What was rejected
   - **Trade-off**: What was sacrificed

5. **Reference Files with Lines**: `src/services/ranker.py:19-221`

6. **Link Previous Work**: Creates documentation chain

---

## File Saving

**Path**: `~/code/personal-site/_reports/YYYY-MM-DD-descriptive-slug.md`

**Absolute path**: `/Users/alyshialedlie/code/personal-site/_reports/`

Use Write tool (not Bash echo).

After writing the file, run the readability appendix script via Bash:

```bash
python3 ~/.claude/skills/session-report/resources/textstat-appendix.py <saved-report-path>
```

This auto-installs `textstat` if needed, appends a `## Appendix: Readability Analysis` section with Flesch, Gunning Fog, SMOG, Dale-Chall, and corpus stats, and is idempotent (safe to re-run).

---

## Quality Checklist

- [ ] `layout: single` (not `post`)
- [ ] Header includes `image` and `teaser`
- [ ] `excerpt` included for SEO
- [ ] `permalink` set to `/reports/descriptive-slug/`
- [ ] Filename: `YYYY-MM-DD-descriptive-slug.md`
- [ ] **NO H1 heading** - layout renders title from frontmatter
- [ ] Metadata block uses `<br>` line breaks
- [ ] Key metrics table with blank line before
- [ ] Executive summary with specific numbers
- [ ] Code examples with language identifiers
- [ ] File references use `filename:line-range` format
- [ ] Test results with pass/fail counts
- [ ] Git commits with hashes

---

## Usage

When user says "create a session report":

1. **Gather**: Review conversation for accomplishments, files, tests, decisions
2. **Structure**: Organize into sections
3. **Generate**: Create frontmatter with title, categories, tags
4. **Write**: Follow template structure
5. **Save**: Use Write tool to save to `_reports/`
6. **Analyse**: Run `textstat-appendix.py` via Bash to append readability metrics
7. **Confirm**: Report location to user

---

## Resources

- [Report Sections](resources/report-sections.md) - Detailed section templates
- [Complete Example](resources/complete-example.md) - Full report example
- [Categories & Tags](resources/categories-tags.md) - Common categories and tags

## Output

The skill produces a single Jekyll-formatted markdown file:
- **Path**: `~/code/personal-site/_reports/YYYY-MM-DD-descriptive-slug.md`
- **Format**: Markdown with YAML frontmatter (`layout: single`, categories, tags, excerpt, header images)
- **Sections**: Metadata block, executive summary with quantified metrics, key metrics table, problem statement, implementation details with `file:line` references, testing/verification output, files modified list, references
- **Delivery**: Written via Write tool; location confirmed to user

---

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=session-report outcome=success|failure report_path=<path> sections=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=session-report`, `plugin.output_size` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Write` (Jekyll report), `builtin.file_path` | post-tool.ts |

---

**Version:** 2.2.0
