---
description: Update dev documentation before context compaction
argument-hint: Optional - specific context or tasks to focus on (leave empty for comprehensive update)
---

We're approaching context limits. Please update the development documentation to ensure seamless continuation after context reset.

## Required Updates

### 1. Update Session History (NOT CLAUDE.md)

**IMPORTANT**: Keep CLAUDE.md focused on current architecture. Add session details to SESSION_HISTORY.md instead.

For the current project:
- Update `docs/SESSION_HISTORY.md` (or create if missing) with:
  - Date heading (e.g., `## 2025-11-18: Brief Session Title`)
  - Problems solved and bugs fixed
  - Key technical decisions and why
  - Files modified with brief explanations
  - Commits made (with commit messages)
  - Status: ✅ Complete or 🔄 In Progress
  - Any learnings or patterns discovered

- Update CLAUDE.md "Current Status" section ONLY with:
  - Production URLs and deployment status
  - Test counts and passing status
  - Current development phase
  - Pointer to SESSION_HISTORY.md

**Pattern**: SESSION_HISTORY.md = chronological session log, CLAUDE.md = current architecture snapshot

### 2. Update Active Task Documentation
For each task in `/dev/active/`:
- Update `[task-name]-context.md` with:
  - Current implementation state
  - Key decisions made this session
  - Files modified and why
  - Any blockers or issues discovered
  - Next immediate steps
  - Last Updated timestamp

- Update `[task-name]-tasks.md` with:
  - Mark completed tasks as ✅
  - Add any new tasks discovered
  - Update in-progress tasks with current status
  - Reorder priorities if needed

### 3. Archive Completed Tasks

For each task directory in `~/dev/active/`:
- Check if `[task-name]-tasks.md` has ALL tasks marked as ✅
- If all tasks complete:
  - Add "Archived: YYYY-MM-DD" timestamp to context.md
  - Move entire task directory to `~/dev/archive/`
  - Use Bash tool: `mv ~/dev/active/[task-name] ~/dev/archive/`
- Skip tasks with any incomplete items (keep in active/)

**Criteria for archiving**:
- ✅ All checklist items marked complete
- ✅ No 🔄 or ⏸️ status indicators
- ✅ No open blockers or pending work
- ✅ All commits pushed (verified in context.md)

### 4. Capture Session Context
Include any relevant information about:
- Complex problems solved
- Architectural decisions made
- Tricky bugs found and fixed
- Integration points discovered
- Testing approaches used
- Performance optimizations made

### 5. Update Memory (if applicable)
- Store any new patterns or solutions in project memory/documentation
- Update entity relationships discovered
- Add observations about system behavior

### 6. Document Unfinished Work
- What was being worked on when context limit approached
- Exact state of any partially completed features
- Commands that need to be run on restart
- Any temporary workarounds that need permanent fixes

### 7. Create Handoff Notes
If switching to a new conversation:
- Exact file and line being edited
- The goal of current changes
- Any uncommitted changes that need attention
- Test commands to verify work

## Additional Context: $ARGUMENTS

**Priority**: Focus on capturing information that would be hard to rediscover or reconstruct from code alone.