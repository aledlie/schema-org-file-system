# Hooks Configuration Guide

This guide explains how to configure and customize the hooks system for your project.

## Quick Start Configuration

### 1. Register Hooks in settings.json

The hooks are configured in `~/.claude/settings.json`. Current configuration uses a unified TypeScript runner:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js session-start"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "mcp__.*|Skill|Task",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js pre-tool"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|mcp__.*|Skill|Task",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js post-tool"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js stop"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js user-prompt"
          }
        ]
      }
    ]
  }
}
```

### 2. Build the Hooks

```bash
cd ~/.claude/hooks
npm install
npm run build
```

## Matcher Configuration

Matchers control which tools trigger hooks:

| Matcher | Description |
|---------|-------------|
| `""` (empty) | Matches all tools |
| `"mcp__.*"` | Matches all MCP tools |
| `"Write\|Edit\|MultiEdit"` | Matches file modification tools |
| `"mcp__.*\|Skill\|Task"` | Matches MCP, Skill, and Task tools |

## Environment Variables

### OpenTelemetry Configuration

Set in `settings.json` under `env`:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://ingest.integritystudio.ai",
    "OTEL_EXPORTER_OTLP_HEADERS": "x-api-key=${OTEL_API_KEY}",
    "OTEL_RESOURCE_ATTRIBUTES": "deployment.environment=development,service.version=1.0.0,user.name=alyshia",
    "OTEL_SERVICE_NAME": "claude-code-hooks"
  }
}
```

### Per-Session Environment Variables

Set before starting Claude Code:

```bash
# Disable telemetry for this session
OTEL_ENABLED=false claude

# Enable debug logging
OTEL_LOG_LEVEL=debug claude
```

## Hook Execution Order

Hooks run in the order specified in settings.json. For Stop hooks:

```json
"Stop": [
  {
    "hooks": [
      { "command": "...hook-runner.js stop" }  // Runs all Stop handlers
    ]
  }
]
```

The `stop.ts` handler internally runs:
1. TypeScript type checking (tsc --noEmit)
2. Python type checking (mypy/pyright)
3. Error handling reminders
4. OTEL dashboard cleanup

## Cache Management

### Cache Locations

| Cache | Location | Purpose |
|-------|----------|---------|
| TypeScript check queue | `~/.claude/.cache/tsc-queue/` | Files queued for tsc checking |
| Python check queue | `~/.claude/.cache/py-queue/` | Files queued for mypy/pyright |
| Tool list cache | `~/.claude/.cache/active-tools-list.md` | Cached `/list-active-tools` output |
| Agent/skill list | `~/.claude/.cache/agents-skills-list.md` | Cached `/list-all-tools` output |

### Manual Cache Cleanup

```bash
# Remove all cached data
rm -rf ~/.claude/.cache/*

# Remove type check queues only
rm -rf ~/.claude/.cache/tsc-queue ~/.claude/.cache/py-queue
```

## Selective Hook Configuration

### Minimal Setup (Telemetry Only)

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js session-start"
          }
        ]
      }
    ]
  }
}
```

### File Tracking Only

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js post-tool"
          }
        ]
      }
    ]
  }
}
```

### MCP Tracking Only

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/dist/hook-runner.js pre-tool"
          }
        ]
      }
    ]
  }
}
```

## Troubleshooting Configuration

### Hook Not Executing

1. **Check registration:** Verify hook is in `~/.claude/settings.json`
2. **Check build:** Ensure `dist/` contains compiled JS (`npm run build`)
3. **Check matcher:** Verify the matcher pattern matches the tool being used
4. **Check logs:** `~/.claude/logs/hook-performance.log`

### TypeScript Compilation Errors

```bash
cd ~/.claude/hooks
npx tsc --noEmit
```

### Performance Issues

**Issue:** Hooks are slow

**Solutions:**
1. Use specific matchers instead of empty string
2. Check OTEL dashboard for hook duration metrics
3. Reduce type check frequency by limiting matchers

### Debugging Hooks

Enable debug logging:

```bash
export OTEL_LOG_LEVEL=debug
```

Check local telemetry files:
```bash
ls -la ~/.claude-history/telemetry/
tail -20 ~/.claude-history/telemetry/traces-$(date +%Y-%m-%d).jsonl
```

## Best Practices

1. **Start minimal** - Enable hooks one at a time
2. **Use specific matchers** - Avoid empty matchers for high-frequency hooks
3. **Monitor performance** - Check OTEL dashboard for slow hooks
4. **Version control** - Commit `~/.claude/` directory to git
5. **Build after changes** - Always run `npm run build` after editing TypeScript

## See Also

- [README.md](./README.md) - Hooks overview
- [PERFORMANCE_MONITORING.md](./PERFORMANCE_MONITORING.md) - Performance tracking guide
