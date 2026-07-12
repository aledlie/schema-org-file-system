---
description: List active agents, skills, and MCP servers
model: claude-sonnet-4-6
context: fork
---

# List Active Tools

Display active agents, skills, and MCP servers available in this environment.

## Instructions

### Step 1: Check Cache

1. Read `/Users/alyshialedlie/.claude/.cache/active-tools-list.md`
2. If exists, display contents and skip to Usage Notes
3. If not found, continue to Step 2

### Step 2: Scan Active Items (if no cache)

**Agents**: Glob `/Users/alyshialedlie/.claude/agents/*.md`, read frontmatter
**Skills**: Glob `/Users/alyshialedlie/.claude/skills/*/SKILL.md`, read frontmatter
**MCPs**: Read `/Users/alyshialedlie/.claude/.mcp.json`, parse `mcpServers` (ignore `_archived`)

### Step 3: Write Cache

Write results to `/Users/alyshialedlie/.claude/.cache/active-tools-list.md`

## Usage Notes

- Agents: `Task(subagent_type='agent-name', ...)`
- Skills: `Skill(skill='skill-name')`
- MCPs: Available as `mcp__servername__toolname` tools
- For lazy-loaded and archived items, use `/list-all-tools`

## Cache Mechanism

- **Location**: `/Users/alyshialedlie/.claude/.cache/active-tools-list.md`
- **Behavior**: First run scans directories and creates cache; subsequent runs read from cache
- **Invalidation**: Cache refreshes when new agents/skills are added
- **Manual refresh**: Delete cache file to force rescan
