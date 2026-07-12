# Agent-Auditor Lightweight Telemetry Queries

Reference resource for agent-auditor. Read when scoring telemetry-dependent dimensions (D1, D5, D6) to bootstrap above the neutral default of 5/10.

## Data Sources

| Source | Path | Format | Contains |
|--------|------|--------|----------|
| Traces | `~/.claude-history/telemetry/traces-YYYY-MM-DD.jsonl` | JSONL | OTEL spans with `agent.type`, `agent.category`, duration, status |
| Audit History | `~/.claude/audit-history/{agent-name}.json` | JSON | Prior scores, tier, CUSUM state |

## Trace Span Schema (Agent Invocations)

Agent invocation spans contain these attributes:

```
agent.type            — agent name (e.g. "agent-auditor")
agent.category        — routing category (e.g. "observability", "code-quality")
agent.source_type     — "active" | "lazy"
agent.is_background   — boolean
agent.model           — model override or "default"
agent.prompt_length   — integer (input prompt token estimate)
gen_ai.agent.name     — same as agent.type
gen_ai.agent.id       — "active:{name}" or "lazy:{name}"
```

Span-level fields: `startTime`, `endTime`, `duration` (array `[seconds, nanoseconds]`), `status` (object `{"code": N}` where 1=OK, 2=ERROR).

**Important**: `status` is a nested object, not a flat attribute. Match `"status":{"code":2}` exactly — do not grep for `"code":2` alone, as it may match unrelated fields.

## Query Procedures

### Q1: Invocation Count (for D1 — Telemetry Health)

Count spans where `agent.type` matches the target agent across the last 30 days of trace files.

```bash
# Count invocations for a specific agent in last 30 days
for f in $(ls ~/.claude-history/telemetry/traces-*.jsonl | tail -30); do
  grep -c '"agent.type":"TARGET_AGENT"' "$f" 2>/dev/null
done | awk '{s+=$1} END {print s+0}'
```

**Scoring map** (invocation count → D1 score component):

| Invocations (30d) | Score Contribution |
|--------------------|--------------------|
| 0 | 2 (dormant — penalize but don't zero) |
| 1-2 | 4 |
| 3-5 | 6 |
| 6-10 | 8 |
| 11+ | 10 |

### Q2: Error Rate (for D1 — Telemetry Health)

Count spans with `status.code: 2` vs total for the target agent.

```bash
# Total and error spans for agent (parse status.code from JSON)
grep '"agent.type":"TARGET_AGENT"' ~/.claude-history/telemetry/traces-*.jsonl \
  | python3 -c "
import sys, json
total, errors = 0, 0
for line in sys.stdin:
    try:
        d = json.loads(line)
        total += 1
        if d.get('status', {}).get('code') == 2:
            errors += 1
    except: pass
print(f'total={total} errors={errors} rate={errors/total*100:.1f}%' if total else 'total=0')
"
```

**Scoring map** (error rate → D1 modifier):

| Error Rate | Modifier |
|------------|----------|
| 0% | +0 (no penalty) |
| 1-10% | -1 |
| 11-25% | -2 |
| 26-50% | -3 |
| 51%+ | -5 |

**D1 Final**: `clamp(invocation_score + error_modifier, 0, 10)`

### Q3: Category Alignment (for D5 — Usage Alignment)

Extract `agent.category` and `gen_ai.agent.description` from invocation spans. Compare against the agent's stated purpose in its manifest description.

```bash
# Extract unique categories and descriptions for agent
grep '"agent.type":"TARGET_AGENT"' ~/.claude-history/telemetry/traces-*.jsonl \
  | python3 -c "
import sys, json
cats, descs = set(), set()
for line in sys.stdin:
    try:
        d = json.loads(line)
        a = d.get('attributes', {})
        if c := a.get('agent.category'): cats.add(c)
        if d := a.get('gen_ai.agent.description'): descs.add(d)
    except: pass
print('Categories:', cats)
print('Descriptions:', descs)
"
```

**Scoring**:
1. Infer expected categories from manifest `name` + `description` keywords
2. Compare inferred categories against observed `agent.category` values
3. Score = `round((matching / total_observed) * 10, 1)` — same formula as scoring spec D5

If no spans found, retain default 5.

### Q4: Duration & Output Efficiency (for D6 — Efficiency & Cost)

Extract duration and prompt length for the target agent and compute median.

```bash
# Extract durations (nanoseconds) for agent
grep '"agent.type":"TARGET_AGENT"' ~/.claude-history/telemetry/traces-*.jsonl \
  | python3 -c "
import sys, json, statistics
durations, prompts = [], []
for line in sys.stdin:
    try:
        d = json.loads(line)
        a = d.get('attributes', {})
        dur = d.get('duration', [0, 0])
        durations.append(dur[0] * 1e9 + dur[1])
        if pl := a.get('agent.prompt_length'): prompts.append(pl)
    except: pass
if durations:
    med_ms = statistics.median(durations) / 1e6
    print(f'Median duration: {med_ms:.0f}ms')
    print(f'Invocations: {len(durations)}')
if prompts:
    print(f'Median prompt length: {statistics.median(prompts):.0f} tokens')
"
```

**Scoring** (median duration → D6 duration component, weight 0.30):

| Median Duration | Score |
|-----------------|-------|
| <10s | 10 |
| 10-30s | 8 |
| 30-60s | 6 |
| 60-120s | 4 |
| 120s+ | 2 |

**Error amplification** (weight 0.25): Reuse the error rate from Q2. Invert the D1 error modifier into a 0-10 score:

| Error Rate | Score |
|------------|-------|
| 0% | 10 |
| 1-10% | 8 |
| 11-25% | 6 |
| 26-50% | 4 |
| 51%+ | 2 |

**Output density** (weight 0.25): Compare `agent.prompt_length` median to the fleet median (sampled from 3-5 peer agents). Score reflects proportional efficiency:

| Prompt Length vs Fleet Median | Score |
|-------------------------------|-------|
| ≤0.5x (very concise) | 10 |
| 0.5x-1.0x | 8 |
| 1.0x-2.0x | 6 |
| 2.0x-3.0x | 4 |
| >3.0x (very verbose) | 2 |

**Background usage** (weight 0.20): Check `agent.is_background` ratio. The "expected" pattern is determined from the manifest: if the manifest contains `background: true` in frontmatter or mentions "background" in its workflow, the expected pattern is background-majority; otherwise foreground-majority. If the manifest does not specify, assign neutral score 5 and flag as unassessable.

| Condition | Score |
|-----------|-------|
| Background ratio matches manifest expectation | 10 |
| Mismatch but <25% of invocations | 6 |
| Mismatch and >25% of invocations | 3 |
| Manifest does not specify — unassessable | 5 |

**D6 Final**: `round(duration * 0.30 + error_amplification * 0.25 + output_density * 0.25 + background * 0.20, 1)`

## Execution Guidelines

- **Time budget**: All queries combined must complete in <15 seconds. Use `tail -30` on trace files to limit scan window.
- **Fallback**: If trace files are missing, empty, or queries fail, retain the neutral default (5/10) for the affected dimension. Never fabricate scores.
- **Fleet baseline**: When computing relative metrics (D6 output density, duration percentiles), query 3-5 peer agents for comparison rather than the full fleet.
- **Cache results**: Store raw query results in audit-history alongside scores so subsequent audits can detect trends without re-querying.
