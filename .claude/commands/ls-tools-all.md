---
description: List all agents, skills, and commands (active, lazy-loaded, and archived) with descriptions
model: claude-sonnet-4-6
context: fork
---

# List Available Agents, Skills, and Commands

## Quick Reference

| Category | Count | Location |
|----------|-------|----------|
| Active Agents | 3 | `agents/*.md` |
| Active Skills | 5 | `skills/*/SKILL.md` |
| Lazy Agents | 7 | `lazy-agents/*.md` |
| Lazy Skills | 12+ | `lazy-skills/*/SKILL.md` |
| Archived | Various | `archive/` |

Display all active, lazy-loaded, and archived agents, skills, and commands with their descriptions to help you choose the right tool for your task.

## Instructions

### Step 1: Check for Cached Data

1. **Check if cache exists**: Look for `/Users/alyshialedlie/.claude/.cache/agents-skills-list.md`
2. **If cache exists**:
   - Read the cache file
   - Display its contents directly
   - Skip to "Usage Notes" section
3. **If cache does NOT exist or is outdated**: Continue to Step 2

### Step 2: Scan and Cache Agent/Skill Information

1. **List Active Agents**: Find all agent files in `/Users/alyshialedlie/.claude/agents/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/agents/*.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Exclude README.md files
   - Store in memory for caching

2. **List Active Skills**: Find all skill files in `/Users/alyshialedlie/.claude/skills/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/skills/*/SKILL.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

3. **List Lazy-Loaded Agents**: Find all lazy agent files in `/Users/alyshialedlie/.claude/lazy-agents/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/lazy-agents/*.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

4. **List Lazy-Loaded Skills**: Find all lazy skill files in `/Users/alyshialedlie/.claude/lazy-skills/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/lazy-skills/*/SKILL.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

5. **List Archived Agents**: Find all archived agent files in `/Users/alyshialedlie/.claude/archive/agents/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/archive/agents/*.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

6. **List Archived Commands**: Find all archived command files in `/Users/alyshialedlie/.claude/archive/commands/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/archive/commands/*.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

7. **List Archived Skills**: Find all archived skill files in `/Users/alyshialedlie/.claude/archive/skills/` directory
   - Use Glob to find `/Users/alyshialedlie/.claude/archive/skills/*/SKILL.md`
   - Read each file (first 10 lines to extract YAML frontmatter)
   - Parse `name` and `description` fields
   - Store in memory for caching

8. **Write Cache File**: Save gathered information to `/Users/alyshialedlie/.claude/.cache/agents-skills-list.md`
   - Create `.cache` directory if it doesn't exist
   - Write complete formatted output
   - Include timestamp in cache file

### Step 3: Format Output

Present in clear, organized format:
   ```
   ## Active Agents (X total)

   - **agent-name**: Description of what it does
   - **another-agent**: Description...

   ## Active Skills (X total)

   - **skill-name**: Description of what it does
   - **another-skill**: Description...

   ---

   ## Lazy-Loaded Items

   ### Lazy-Loaded Agents (X total)
   - **agent-name**: Description... *(lazy)*

   ### Lazy-Loaded Skills (X total)
   - **skill-name**: Description... *(lazy)*

   ---

   ## Archived Items

   ### Archived Agents (X total)
   - **agent-name**: Description... *(archived)*

   ### Archived Commands (X total)
   - **command-name**: Description... *(archived)*

   ### Archived Skills (X total)
   - **skill-name**: Description... *(archived)*
   ```

### Step 4: Usage Notes

Add helpful information about:
- How to invoke agents: `Task(subagent_type='agent-name', ...)`
- How to invoke skills: `Skill(skill='skill-name')`
- Lazy-loaded items are available but not auto-loaded to save context; invoke via Skill tool
- Lazy-loaded locations: `/Users/alyshialedlie/.claude/lazy-agents/` and `/Users/alyshialedlie/.claude/lazy-skills/`
- Archived items are deprecated/inactive but can be restored by moving them from `archive/` to the active directory
- Archived items location: `/Users/alyshialedlie/.claude/archive/`
- Note that cache was used (if applicable)

## Cache Management

**Cache Location**: `/Users/alyshialedlie/.claude/.cache/agents-skills-list.md`

**Cache Invalidation**: The cache should be regenerated when:
- New agents or skills are added
- Agent/skill descriptions are updated
- User explicitly requests fresh data
- Cache file is older than 7 days (optional check)

**Manual Cache Refresh**: To force refresh, delete the cache file:
```bash
rm /Users/alyshialedlie/.claude/.cache/agents-skills-list.md
```

## Expected Behavior

- **First run**: Scan all agents/skills/commands (active, lazy-loaded, and archived), create cache, display results (~3-5 seconds)
- **Subsequent runs**: Read from cache, display instantly (~0.5 seconds)
- Display all active agents with brief descriptions
- Display all active skills with brief descriptions
- Display all lazy-loaded agents and skills in a separate section
- Display all archived agents, commands, and skills in a separate section
- Count totals for each category (active, lazy-loaded, and archived separately)
- Provide usage instructions
- Handle cases where directories don't exist
- Handle YAML parsing errors gracefully

## Cache File Format

The cache file should contain:
```markdown
# Agents and Skills Quick Reference

**Last Updated**: YYYY-MM-DD HH:MM:SS
**Cache Location**: /Users/alyshialedlie/.claude/.cache/agents-skills-list.md

## Active Agents (X total)

- **agent-name**: Description...

## Active Skills (X total)

- **skill-name**: Description...

---

## Lazy-Loaded Items

### Lazy-Loaded Agents (X total)
- **agent-name**: Description... *(lazy)*

### Lazy-Loaded Skills (X total)
- **skill-name**: Description... *(lazy)*

---

## Archived Items

### Archived Agents (X total)
- **agent-name**: Description... *(archived)*

### Archived Commands (X total)
- **command-name**: Description... *(archived)*

### Archived Skills (X total)
- **skill-name**: Description... *(archived)*

## How to Use

[Usage instructions...]
```

## Performance Benefits

- **Without cache**: 15+ file reads, 3-5 seconds
- **With cache**: 1 file read, <0.5 seconds
- **Efficiency gain**: 10x faster on subsequent runs

## Notes

- This command helps discover available tools without manual directory exploration
- Useful when you need to choose the right agent or skill for a task
- Cache provides instant access to tool inventory
- Always use absolute paths for reliability
- Lazy-loaded items are available on-demand via Skill tool (not auto-loaded to save context)
- Archived items are shown separately for reference and can be restored if needed
- To restore an archived item, move it from `archive/` to the corresponding active directory
