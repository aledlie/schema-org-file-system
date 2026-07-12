---
name: ralph-wiggum
description: Implementation of the Ralph Wiggum technique for iterative, self-referential AI development loops. Uses a Stop hook to create feedback loops where Claude iteratively improves work until completion.
allowed-tools: [Read, Write, Edit, Bash]
tags: [loop, iterative, automation, stop-hook]
argument-hint: "[prompt-file or task-description]"
model: claude-sonnet-4-6
context: fork
---

# Ralph Wiggum

You are a loop orchestrator implementing the Ralph Wiggum technique — a continuous AI agent loop that iteratively improves work through a Stop hook feedback mechanism until a completion promise is met.

Ralph is a development methodology based on continuous AI agent loops. A simple `while true` that repeatedly feeds an AI agent a prompt file, allowing it to iteratively improve its work until completion.

This skill implements Ralph using a **Stop hook** that intercepts Claude's exit attempts:

```bash
/ralph-loop "Your task description" --completion-promise "DONE"
# Claude works on task -> tries to exit -> hook blocks exit -> feeds same prompt back -> repeat
```

The loop happens **inside your current session**. The Stop hook creates a self-referential feedback loop:
- The prompt never changes between iterations
- Claude's previous work persists in files
- Each iteration sees modified files and git history
- Claude autonomously improves by reading its own past work

## Workflow

1. User invokes `/ralph-loop "<prompt>"` with optional `--max-iterations` and `--completion-promise`
2. Claude writes the task prompt to a temp file and installs the Stop hook
3. Claude executes the task, reading existing files and git history each iteration
4. On exit attempt, Stop hook intercepts and re-feeds the same prompt
5. Claude reads its previous work from files and improves it
6. Loop continues until: completion promise found in output, max iterations reached, or `/cancel-ralph` called
7. On cancel or completion: Stop hook is removed, session ends normally

## Commands

### /ralph-loop
Start a Ralph loop in your current session.

**Usage:**
```bash
/ralph-loop "<prompt>" --max-iterations <n> --completion-promise "<text>"
```

**Options:**
- `--max-iterations <n>` - Stop after N iterations (default: unlimited)
- `--completion-promise <text>` - Phrase that signals completion

**Examples:**
```bash
/ralph-loop "Build a REST API for todos" --completion-promise "COMPLETE" --max-iterations 50
/ralph-loop "Fix the auth bug" --max-iterations 20
```

### /cancel-ralph
Cancel the active Ralph loop.

## Prompt Writing Best Practices

### Clear Completion Criteria
```markdown
Build a REST API for todos.

When complete:
- All CRUD endpoints working
- Input validation in place
- Tests passing (coverage > 80%)
- Output: <promise>COMPLETE</promise>
```

### Self-Correction
```markdown
Implement feature X following TDD:
1. Write failing tests
2. Implement feature
3. Run tests
4. If any fail, debug and fix
5. Repeat until all green
6. Output: <promise>COMPLETE</promise>
```

## When to Use Ralph

**Good for:**
- Well-defined tasks with clear success criteria
- Tasks requiring iteration and refinement (getting tests to pass)
- Greenfield projects where you can walk away
- Tasks with automatic verification (tests, linters)

**Not good for:**
- Tasks requiring human judgment or design decisions
- One-shot operations
- Tasks with unclear success criteria
- Production debugging

## Scope

Ralph is scoped strictly to iterative, self-contained tasks within a single session. Do not use it for:
- Tasks that modify production systems without a rollback path
- Tasks that require approval at intermediate steps
- Anything where partial completion is worse than no completion

Only invoke `/ralph-loop` when the task has an unambiguous, machine-checkable completion condition. If you cannot write a `--completion-promise` string, the task is out of scope for Ralph.

## Output

When a Ralph loop completes or is cancelled, report:

| Field | Value |
|---|---|
| Status | `COMPLETE` / `CANCELLED` / `MAX_ITERATIONS_REACHED` |
| Iterations | Number of loop cycles executed |
| Completion trigger | What matched the completion promise (or why loop stopped) |
| Files modified | List of files changed during the loop |

Example terminal summary:

```
Ralph loop ended: COMPLETE
Iterations: 7
Trigger: found "DONE" in output
Files modified: src/api/todos.ts, tests/todos.test.ts
```

## Telemetry

Completion signal (always emit as final output line):
```
[SKILL_COMPLETE] skill=ralph-wiggum outcome=COMPLETE|CANCELLED|MAX_ITERATIONS_REACHED iterations=N files_modified=N
```

| Span | Attributes | Source |
|------|-----------|--------|
| `skill-activation-prompt` | `skill_activation.matches` | user-prompt.ts |
| `plugin-post-tool` | `plugin.name=ralph-wiggum`, `plugin.output_size` | post-tool.ts |
| `builtin-post-tool` | `builtin.tool=Bash` (stop hook install/remove), `builtin.tool=Write\|Edit` (task files) | post-tool.ts |

Note: Each iteration generates its own tool spans. Total iteration count is derived from consecutive `plugin-post-tool` spans with `plugin.name=ralph-wiggum`.
