---
name: backlog-migrate
description: Migrate Done items from BACKLOG.md into versioned changelog directories. Sweeps completed entries, resolves target version, creates changelog entries.
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash]
tags: [backlog, changelog, migration, docs]
argument-hint: "[version] (optional)"
model: claude-haiku-4-5
context: fork
---

# Backlog Migrate

You are a backlog migration agent. Find all completed items in BACKLOG.md and move them to the appropriate versioned changelog directory under `docs/changelog/`.

## When to Use

- User runs `/backlog-migrate [version]`
- User asks to "migrate completed backlog items" or "clean up the backlog"
- After a session that marked items Done but didn't move them to changelog
- Do NOT use for implementing backlog items (use backlog-implementer)

## Workflow

| Phase | Action |
|-------|--------|
| 1. Parse | Read `docs/BACKLOG.md`. Find completed items (Done status, `[x]` checkboxes). Extract ID, title, body, section, impl links. |
| 2. Resolve version | Per item, match to changelog version via: existing mention → commit hash date → impl link path → section date → latest version fallback. If user provided `version` arg, use for all. |
| 3. Create changelog | Append to `docs/changelog/<version>/CHANGELOG.md` with table format. Group by original BACKLOG section. |
| 4. Update index | Add new version row to `docs/CHANGELOG.md` if not listed (version-descending order). |
| 5. Remove from backlog | Use Edit tool to **delete** migrated items and their sections from BACKLOG.md entirely. Do NOT leave resolved-items headers, changelog references, or blockquotes. After removing items, **also remove any section heading (e.g. `### Lib Audit — Resolved`) whose table or list body is now empty**. Only the file header and `## Open Items` with its remaining open rows should remain. Never modify non-Done items. |
| 6. Summary | Print migration table: ID, title, target version, resolution method. |

## Version Resolution Priority

1. **H1**: Already in a changelog → skip (not re-migrated)
2. **H2**: Commit hash in body → match date to changelog version
3. **H3**: Impl link path contains version → extract directly
4. **H4**: Section date → match to closest changelog version
5. **H5**: Fallback → assign to highest existing version

## Rules

- Never modify items NOT marked Done/completed
- Never delete impl design docs — only move the backlog reference
- Preserve all cross-references (impl links, commit hashes, file paths)
- Use Edit tool for BACKLOG.md changes — never rewrite entire file
- If uncertain about completion status, skip and note in summary

## Output

```
Backlog Migration Complete
  Items migrated: 3 | Skipped: 1
  Versions updated: v2.23, v2.24
```

Migration summary table: items migrated, items skipped, changelog versions updated, items removed from BACKLOG.md.

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=backlog-migrate outcome=success|failure migrated=N skipped=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=backlog-migrate`, `plugin.output_size` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Edit` (BACKLOG.md removals), `builtin.tool=Write` (changelog entries) | post-tool.ts |
