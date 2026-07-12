# Claude Code Configuration

This directory contains Claude Code configuration, hooks, skills, and agents.

## Structure

```
.claude/
├── skills/          # Skill definitions
├── hooks/           # Hook scripts
├── agents/          # Agent definitions
├── commands/        # Slash commands
├── logs/            # Hook execution logs
├── scripts/         # Utility scripts
└── schemas/         # JSON schemas
```

## Setup

1. Install dependencies:
   ```bash
   cd .claude
   npm install
   ```

2. Validate configuration:
   ```bash
   npm run validate
   ```

3. Check environment:
   ```bash
   npm run check-env
   ```

4. View status:
   ```bash
   npm run status
   ```

## Adding Components

### Skills
1. Copy skill to `.claude/skills/`
2. Update `.claude/skills/skill-rules.json`
3. Run `npm run validate`

### Hooks
1. Copy hook to `.claude/hooks/`
2. Make executable: `chmod +x .claude/hooks/your-hook.sh`
3. Update `.claude/settings.json`

### Agents
1. Copy agent to `.claude/agents/`
2. No configuration needed

## Performance Monitoring

See `hooks/PERFORMANCE_MONITORING.md` for how to add performance tracking to hooks.

## Documentation

- Integration: See `~/dev/CLAUDE_INTEGRATION_GUIDE.md`
- Hooks: See `hooks/PERFORMANCE_MONITORING.md`
