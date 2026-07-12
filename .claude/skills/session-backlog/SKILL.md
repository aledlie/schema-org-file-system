---
name: session-backlog
description: Document and append un-implemented items from the current session to docs/BACKLOG.md. Records deferred work, skipped phases, TODO comments, review findings, and follow-up tasks as backlog entries.
allowed-tools: [Read, Edit, Grep, Glob, Bash]
tags: [backlog, session, deferred-work, documentation]
argument-hint: "[path/to/BACKLOG.md] (optional)"
model: claude-haiku-4-5
context: fork
---

# Session Backlog

You are a session backlog recorder. Sweep the current conversation for un-implemented work and append it to the project's BACKLOG.md — deferred items, skipped phases, code review findings, and follow-up tasks.

## When to Use

- User runs `/session-backlog` or `/session-backlog <path/to/BACKLOG.md>`
- After a session with deferred work, skipped phases, or partial implementations
- User asks to "capture remaining work" or "document what we didn't finish"
- After a code review session to record medium/low findings not yet fixed
- Do NOT use to implement backlog items — use backlog-implementer for that

## Commands

### /session-backlog

Document remaining un-implemented items from this session.

**Usage:**
```bash
/session-backlog [path/to/BACKLOG.md]
```

**Options:**
- Path argument defaults to `docs/BACKLOG.md`
- Falls back to `docs/backlog/BACKLOG.md` if the first path doesn't exist

## Workflow

### Phase 1: Identify the backlog file

1. Resolve the BACKLOG.md path (argument or default)
2. Read the existing file to understand current structure, sections, and ID numbering
3. Note the highest existing item ID per section to avoid collisions

### Phase 2: Sweep session for un-implemented items

Search the conversation context for items matching ANY of these categories:

1. **Skipped phases/items** - Backlog items explicitly marked as skipped with rationale
2. **Deferred review findings** - Code review findings rated Medium or Low that were noted but not fixed
3. **Reviewer recommendations** - Suggestions from code-reviewer agents marked as "optional", "P2+", or "consider"
4. **TODO/FIXME comments** - Any TODO or FIXME added to source code during this session
5. **Known limitations** - Explicitly acknowledged limitations of implementations made this session
6. **Follow-up work** - Items described as "future work", "next step", or "follow-up"
7. **Test gaps** - Missing tests identified but not written

For each item, extract:
- **What**: One-line description
- **Where**: File path and line number (if applicable)
- **Why deferred**: Rationale for not implementing now
- **Priority**: P1-P4 based on severity/impact
- **Source**: Which commit, review, or conversation turn produced it

### Phase 3: Deduplicate

Compare each extracted item against existing BACKLOG.md entries:
- Skip exact duplicates (same file + same description)
- Skip items that are already tracked under a different ID
- Flag near-duplicates for manual review (append `(possible duplicate of <ID>)`)

### Phase 4: Append to BACKLOG.md

1. Group new items by priority section, matching existing BACKLOG.md structure
2. Assign IDs following the existing convention (e.g., M41, L17, T7, etc.)
3. Use the same markdown format as existing entries:
   ```markdown
   #### <ID>: <Title>
   **Priority**: P<n> | **Source**: <session commit or review>
   <Description>. -- `<file:line>` (if applicable)
   ```
4. Append items to the appropriate existing section (do NOT create new sections unless no match exists)
5. If no items found, report "No un-implemented items found in this session" and stop

### Phase 5: Summary

Print a table of items added:

```
| ID | Priority | Description | Source |
|----|----------|-------------|--------|
```

## Output

After appending to BACKLOG.md, print a summary table:

```
| ID    | Priority | Description                          | Source            |
|-------|----------|--------------------------------------|-------------------|
| M42   | P2       | Add retry logic to fetch wrapper     | session:abc123    |
| L18   | P3       | Expand unit test coverage for parser | review:code-rev   |
```

- One row per item appended
- If no items found: print `No un-implemented items found in this session` and stop
- Do not print items that were skipped due to deduplication

## Rules

- NEVER remove or modify existing backlog entries
- NEVER change item status (that's backlog-implementer's job)
- ONLY append new items
- Preserve existing markdown structure exactly
- If uncertain whether something is a backlog item, include it with a `(review)` tag
- Do not include items that were implemented and committed during the session

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=session-backlog outcome=success|failure items_appended=N duplicates_skipped=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=session-backlog`, `plugin.output_size` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Edit` (BACKLOG.md append), `builtin.tool=Grep` (dedup scan) | post-tool.ts |
