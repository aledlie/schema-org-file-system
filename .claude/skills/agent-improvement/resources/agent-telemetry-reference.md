# Agent Telemetry Reference

## Span Types

| Span Name | Trigger | Key Attributes |
|-----------|---------|----------------|
| `hook:agent-pre-tool` | Before agent invocation | `agent.type`, `agent.category`, `agent.source_type`, `agent.is_background`, `agent.model`, `agent.prompt_length`, `agent.description` |
| `hook:agent-post-tool` | After agent completes | `agent.output_size`, `agent.has_error`, `agent.has_rate_limit`, `agent.output_mentions_error`, `agent.output.has_structure`, `agent.output.has_code`, `agent.output.has_actions`, `agent.output.truncated`, `agent.output.empty` |

## Common Queries

```bash
# Count agent invocations per day (last 7 days)
grep 'AGENT_NAME' ~/.claude/telemetry/traces-2026-02-*.jsonl | grep 'agent-post-tool' | wc -l

# Extract error spans
grep 'AGENT_NAME' ~/.claude/telemetry/traces-*.jsonl | grep 'agent-post-tool' | grep '"agent.has_error":true'

# Extract rate-limit spans
grep 'AGENT_NAME' ~/.claude/telemetry/traces-*.jsonl | grep 'agent-post-tool' | grep '"agent.has_rate_limit":true'

# Daily error/rate-limit breakdown (pipe to python3)
grep 'AGENT_NAME' ~/.claude/telemetry/traces-*.jsonl | grep 'agent-post-tool' | python3 -c "
import sys, json
from collections import defaultdict
from datetime import datetime
daily = defaultdict(lambda: {'total': 0, 'errors': 0, 'rate_limits': 0})
for line in sys.stdin:
    d = json.loads(line)
    a = d.get('attributes', {})
    dt = datetime.fromtimestamp(d['startTime'][0]).strftime('%m-%d')
    daily[dt]['total'] += 1
    if a.get('agent.has_error'): daily[dt]['errors'] += 1
    if a.get('agent.has_rate_limit'): daily[dt]['rate_limits'] += 1
for date in sorted(daily):
    d = daily[date]
    print(f'{date} | total={d[\"total\"]:>4} | err={d[\"errors\"]:>3} | rl={d[\"rate_limits\"]:>3}')
"
```

## Evaluation Record Names

Written to `~/.claude/telemetry/evaluations-YYYY-MM-DD.jsonl`:

| Name | Description |
|------|-------------|
| `agent.quality.score` | Total score (0-60) |
| `agent.quality.score.telemetry` | Telemetry health dimension (0-10) |
| `agent.quality.score.definition` | Definition quality dimension (0-10) |
| `agent.quality.score.prompting` | Prompt engineering dimension (0-10) |
| `agent.quality.score.overlap` | Overlap & redundancy dimension (0-10) |
| `agent.quality.score.alignment` | Usage alignment dimension (0-10) |
| `agent.quality.score.efficiency` | Efficiency & cost dimension (0-10) |
| `agent.investigation.error_rate` | Error rate finding from investigation |
| `agent.investigation.rate_limit_rate` | Rate-limit rate finding |
| `agent.improvement.fix_deployed` | Count of fixes applied |
