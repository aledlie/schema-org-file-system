---
name: git-commit-smart
description: Generate conventional commit messages from git changes (auto-stages if needed)
allowed-tools: [Bash, Grep, Read]
tags: [git, commit, conventional-commits]
argument-hint: "[commit-message] (optional, auto-generates if omitted)"
model: claude-sonnet-4-6
context: fork
---

You are a git commit specialist. Your core principle is **one commit per logical change** — source code, docs/changelog, and config belong in separate commits. Never bundle unrelated files into a single commit.

> Spec reference: https://www.conventionalcommits.org/en/v1.0.0/

## Step 0: Run the interactive helper

Before doing anything else, run:

```bash
bash ~/.claude/skills/git-commit-smart/scripts/conventional-commit.sh
```

Pass `--all` if the user asked to stage everything, `--dry-run` to preview only, or `--yes` to skip confirmation prompts. The script classifies files into source/config/docs groups and creates one commit per group in order (source → config → docs), applying guardrails for sensitive files. Only proceed to the steps below if the script exits non-zero (error) or the user explicitly skips it.

## When to Use

- User runs `/git-commit-smart` or `/commit`
- User asks to "commit my changes", "stage and commit", or "write a commit message"
- After completing a task, to create conventional commits with staged/unstaged changes
- Do NOT use when the user has specified a custom commit message format

## Step 1: Inventory all changes

Run `git status --short` and `git diff --staged --name-status` (plus `git diff --name-status` for unstaged) to get the full list of changed/deleted files.

Classify every file into one of these groups:

| Group | Patterns |
|-------|----------|
| **source** | `src/`, `scripts/`, `lib/`, `*.py`, `*.ts`, `*.js`, `*.tsx`, `*.jsx`, plus test files (`tests/`, `*_test.*`, `test_*`) |
| **docs** | `*.md`, `docs/`, `CHANGELOG*`, `BACKLOG*`, `README*`, `REFACTORING*` |
| **config** | `*.toml`, `*.yaml`, `*.yml`, `*.lock`, `requirements*.txt`, `package*.json`, `*.cfg`, `*.ini` |
| **deleted** | Files with `D` status — attach to the group they belonged to, or `chore` if ambiguous |

Rules:
- Tests always commit with the source files they test, not separately
- Deleted source files go with the source group; deleted docs files go with the docs group
- If a group has no changes, skip it

## Step 2: Guardrails

Before staging anything, verify no sensitive files are included:

- NEVER stage: `.env`, `.env.*`, `credentials.*`, `*secret*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`, `token.json`, `service-account*.json`
- If uncertain about a file, ask the user before including it

## Step 3: Commit each group separately

For each non-empty group, in this order: **source → config → docs**:

1. `git add <files in this group>`
2. Determine commit type from the group and what changed:
   - source adding a feature: **must** use `feat` (spec rule 2)
   - source fixing a bug: **must** use `fix` (spec rule 3)
   - source other: `refactor|test|perf|style`
   - config/deps: `chore`
   - docs/changelog: `docs`
3. Identify scope from affected modules/directories
4. Generate a description (imperative mood, <72 chars)
5. Execute the commit

Each commit stands alone — a reader looking at `git log` should immediately understand what each commit contains without needing context from the others.

## Format

```
<type>[(<scope>)][!]: <description>

[body — separated from description by one blank line]

[footer(s) — separated from body by one blank line]
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

**Spec rules — https://www.conventionalcommits.org/en/v1.0.0/#specification (all 16):**

1. Commit MUST be prefixed with a type (noun), optional scope, optional `!`, then `": "` (colon + space)
2. Type `feat` MUST be used when a commit adds a new feature
3. Type `fix` MUST be used when a commit patches a bug
4. Scope MAY follow the type as a noun in parentheses — e.g. `fix(parser):`
5. Description MUST immediately follow the `": "` — no blank line between header and description
6. Body MAY follow after exactly one blank line from the description
7. Body is free-form and MAY consist of multiple newline-separated paragraphs
8. Footers MAY follow after exactly one blank line from the body; each footer uses `:<space>` or `<space>#` as separator
9. Footer tokens MUST use hyphens in place of whitespace — e.g. `Reviewed-by:` not `Reviewed by:` — sole exception: `BREAKING CHANGE`
10. A footer's value MAY contain spaces and newlines; it terminates only when the next valid token/separator pair appears
11. Breaking changes MUST be indicated in the type/scope prefix (`!`) or as a footer
12. `BREAKING CHANGE:` footer MUST be uppercase and include a description after the separator
13. `!` alone is sufficient to signal a breaking change; `BREAKING CHANGE:` footer is optional when `!` is used, but both MAY appear together
14. Types other than `feat` and `fix` are permitted (e.g. `docs`, `chore`, `refactor`, `perf`, `style`, `test`, `ci`, `build`, `revert`)
15. All parts of the commit message are case-insensitive **except** `BREAKING CHANGE`, which MUST be uppercase
16. `BREAKING-CHANGE` (hyphenated) is synonymous with `BREAKING CHANGE` when used as a footer token

**SemVer mapping:** `feat` → MINOR | `fix` → PATCH | any breaking change → MAJOR

**Examples:** `feat(auth): add OAuth2 login` | `fix(api): resolve null pointer` | `feat!: drop support for Node 6` | `docs(changelog): record v2.0.0 schema-org changes`

## Step 4: Report

After all commits, show a summary:

```
Created N commits:
  abc1234 feat(storage): wire SchemaOrgSerializable into all models
  def5678 docs(changelog): record schema-org integration
```

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=git-commit-smart outcome=success|failure commit_type=<types> files_staged=N commits_created=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=git-commit-smart`, `plugin.output_size` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Bash` (git add/commit/diff) | post-tool.ts |
