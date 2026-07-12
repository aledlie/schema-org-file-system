# Agent-Auditor Scoring Specification

Reference document for agent-auditor. Read at the start of each audit for detailed rubrics, learning loop parameters, and state management schemas.

## Dimension 2: Definition Quality (0-10)

Check all of the following (1 point each, max 10):

1. **has_name** — Frontmatter contains non-empty `name:` field
2. **has_description** — Frontmatter contains non-empty `description:` field
3. **has_tools** — Frontmatter contains non-empty `tools:` field
4. **has_model** — Frontmatter contains non-empty `model:` field
5. **desc_length** — Description is 20-200 characters (catches both stubs and essays)
6. **when_section** — Contains `## When` section explaining invocation triggers
7. **output_section** — Contains `## Output` or `## Format` or `## Response` section
8. **lines_30_400** — Agent body is 30-400 lines (structural quality indicator)
9. **tools_restricted** — Tools field is non-empty AND not the full tool set (shows intentional restriction)
10. **has_sections** — Contains at least 2 section headers (basic structure)

**Scoring**: Sum of checks (0-10). If score > 10, cap at 10.

## Dimension 3: Prompt Engineering (0-10)

Check the following weighted items:

1. **role_statement** — Contains "You are" or similar role declaration (1.0 point)
2. **numbered_steps** — Contains numbered list `1.` `2.` etc. showing workflow (1.5 points)
3. **guardrails** — Contains guardrail/constraint language: "guardrail", "constraint", "never", "do not", "avoid" (1.0 point)
4. **code_examples** — Contains ` ``` ` code blocks (1.0 point)
5. **tables** — Contains markdown tables `| ... | ... |` (1.0 point)
6. **output_spec** — Explicit output format section (1.5 points)
7. **markdown_structure** — Has section headers AND bullet lists (1.0 point)
8. **scope_boundaries** — Describes what is in-scope vs out-of-scope (1.0 point)

**Scoring**: Sum weighted points, then normalize: `score = min(round((sum / 9) * 10, 1), 10)`.

## Dimension 4: Overlap & Redundancy (0-10)

**For each peer agent** (all other manifests):
1. If peer shares NO tools with this agent, skip it
2. Compute Jaccard similarity on keywords (stopwords removed, length > 2):
   - `J = len(keywords_self & keywords_peer) / len(keywords_self | keywords_peer)`
3. Track max overlap across all peers

**Scoring**:
- If max overlap <= 0.20: score = 10
- If max overlap <= 0.40: score = 8
- If max overlap <= 0.60: score = 6
- If max overlap <= 0.80: score = 4
- If max overlap > 0.80: score = 1

(Lower overlap = higher score, indicating uniqueness.)

## Dimension 5: Usage Alignment (telemetry-optional, 0-10)

**If telemetry is available**: Compare agent's stated purpose against observed invocation categories.
- Infer expected categories from description + name (code, review, testing, planning, etc.)
- Count actual categories from invocations
- **Score = round((matching_invocations / total_invocations) * 10, 1)**

**If no telemetry**: Default score = 5 (neutral; cannot assess alignment without usage data).

## Dimension 6: Efficiency & Cost (telemetry-optional, 0-10)

**If telemetry is available**:
- Measure agent's median duration vs all agents' median (duration score: 0-10)
- Count error rate vs all agents; penalize high error rates (amplification score: 0-10)
- Check if output density is reasonable vs median (output score: 0-10)
- Assess background usage appropriateness (background score: 0-10)
- **Final score = round(duration * 0.30 + amplification * 0.25 + output * 0.25 + background * 0.20, 1)**

**If no telemetry**: Default score = 5 (neutral; cannot assess without usage data).

## Scoring Implementation Notes

**Scoring robustness**:
- Dimensions 2-4 are deterministic (manifest content only) — always computable
- Dimensions 1, 5, 6 depend on telemetry — if unavailable, use neutral default (5/10) to avoid fabricated scores
- Never guess or interpolate missing telemetry; always flag when scoring without usage data

**Stopwords for keyword extraction** (exclude from Jaccard similarity):
```
the a an is are for and or to in of on with this that use when you it be
as by from at do not can if will all has have your was but they been its
each no so should would could may any
```

## Anti-Patterns

1. **Vocabulary duplication** — copying terminology from peer manifests inflates Jaccard overlap
2. **Scope creep** — expanding agent responsibility beyond its routing category
3. **Over-instrumentation** — adding telemetry hooks that increase latency without diagnostic value
4. **Phantom guardrails** — listing constraints the agent cannot actually enforce at runtime
5. **Stale telemetry baselines** — comparing against outdated span data after manifest changes

## Vocabulary Governance

When rewriting manifests, enforce lexical differentiation:
- Compute Jaccard coefficient against all peer manifests; flag if J > 0.30
- Prefer domain-specific jargon over generic phrases (e.g., "manifest frontmatter" not "file header")
- Maintain a disambiguation index mapping shared terms to agent-specific synonyms
- Cross-reference the routing dispatch table to ensure description keywords trigger correct invocation
- Validate that persona statements, identity declarations, and delegation chains use unique lexemes

---

## Audit History & State Management

All learning loop state is managed by agent-auditor using Read/Write tools. No external TypeScript modules required.

**Storage location**: `~/.claude/audit-history/`
- `{agent-name}.json` — Per-agent audit history, tier, CUSUM state, dimension stability
- `fleet-state.json` — Aggregate tier/grade distribution across fleet

**Backward compatibility**: If `~/.claude/audit-history/` does not exist, operate in one-shot mode (all agents at T1, full 6-dimension audit). The learning loop activates on the second audit when state exists.

### Sweep State & Partial-Audit Recovery

**File**: `~/.claude/audit-history/sweep-state.json`

Persisted at the end of each per-agent audit during an `--all` sweep. Enables resume from the last incomplete agent if the sweep is interrupted (context exhaustion, timeout, crash).

**Schema**:
```json
{
  "schema_version": 1,
  "sweep_id": "sweep-YYYYMMDD-HHMMSS",
  "started_at": "2026-04-06T12:00:00Z",
  "status": "in_progress",
  "total_discovered": 20,
  "manifest_queue": ["agent-a", "agent-b", "agent-c"],
  "completed": [
    {
      "agent_name": "agent-a",
      "completed_at": "2026-04-06T12:01:30Z",
      "score": 48,
      "grade": "A"
    }
  ],
  "current_agent": "agent-b",
  "current_step": 4,
  "skipped": [],
  "error_log": [],
  "interrupted_at": null,
  "interrupt_reason": null
}
```

**Field descriptions**:
- `manifest_queue`: Ordered list of agent names remaining to audit (agents not yet started)
- `completed`: Array of per-agent results with name, timestamp, score, and grade
- `current_agent`: Agent being audited when last persisted (null if between agents)
- `current_step`: Workflow step (1-8) the current agent was on when last persisted
- `skipped`: Agents skipped due to errors (with reason)
- `error_log`: Array of `{ "agent_name", "step", "error", "timestamp" }` for non-fatal errors
- `interrupted_at`: ISO timestamp if sweep was interrupted; null if running or completed
- `interrupt_reason`: `"context_budget"` | `"timeout"` | `"max_agents"` | `"user_cancel"` | `"error"`

**Lifecycle**:
1. **Create** — On `--all` sweep start, discover manifests, write `sweep-state.json` with `status: "in_progress"` and full `manifest_queue`
2. **Update** — After each agent completes scoring, move it from `manifest_queue` to `completed`, update `current_agent` to the next in queue, and persist. This is the checkpoint.
3. **Interrupt** — If the sweep stops early (budget, timeout, error), set `interrupted_at`, `interrupt_reason`, and `status: "interrupted"`. The partially-scored current agent is NOT added to `completed` — it will be re-audited on resume.
4. **Resume** — On the next `--all` invocation, if `sweep-state.json` exists with `status: "interrupted"`:
   - Report: `"Resuming sweep {sweep_id} — {N} of {total} agents completed, resuming from {current_agent}"`
   - Use `manifest_queue` as the remaining work list (do not re-discover; fleet may have changed)
   - Re-audit `current_agent` from step 1 (partial scores are discarded)
   - Continue through remaining `manifest_queue`
5. **Complete** — When all agents are scored, set `status: "completed"`, clear `current_agent` and `manifest_queue`. Retain the file for the report.
6. **Expire** — A completed `sweep-state.json` older than 24 hours is ignored on the next `--all` invocation. A fresh sweep starts. Interrupted sweeps never expire — they must be explicitly resumed or cleared.

**Clearing stale sweeps**: If the user runs `--all` and an interrupted sweep exists but the user wants a fresh start, they can pass `--fresh` to delete `sweep-state.json` and begin a new sweep.

**Consistency guarantee**: Because each per-agent audit-history file is persisted independently (step 5 in the workflow), completed agents always have consistent state even if the sweep is interrupted. Only the sweep-level ordering and progress are tracked in `sweep-state.json`.

**Per-agent state schema**:
```json
{
  "schema_version": 1,
  "agent_name": "example",
  "tier": "T1",
  "total_audits": 0,
  "tier_audit_count": 0,
  "last_audit_date": null,
  "last_manifest_fingerprint": null,
  "tool_risk": "execute",
  "max_tier": "T2",
  "dimensions": {
    "telemetry_health": {
      "ema": null, "scores": [], "shadow_scores": [],
      "variance": null, "stability": "unstable",
      "cusum_s_low": 0.0, "cusum_alarm": false,
      "last_full_score": null, "last_full_date": null
    },
    "definition_quality": { "...same structure..." },
    "prompt_engineering": { "...same structure..." },
    "overlap_redundancy": { "...same structure..." },
    "usage_alignment": { "...same structure..." },
    "efficiency_cost": { "...same structure..." }
  },
  "audit_log": [],
  "circuit_breaker_history": []
}
```

**Retention limits**: `scores` max 10 (rolling window), `shadow_scores` max 5, `audit_log` max 20, `circuit_breaker_history` never pruned (permanent governance record).

**Tool risk classification** (computed from agent's `tools:` frontmatter):

| Risk Tier | Tools Present | `max_tier` |
|-----------|--------------|------------|
| read-only | Read, Grep, Glob, WebFetch, WebSearch only | T3 |
| write | Write, Edit, MultiEdit (no Bash) | T2 |
| execute | Bash or Agent | T2 |

Set `tool_risk` and `max_tier` on first audit based on the agent's declared tools.

## Trust Tier System

Three tiers govern audit depth. Advancement is threshold-gated (not schedule-based — linear decay is optimal only for fixed-horizon training; open-ended governance requires threshold gating). Demotion is instant on circuit breaker.

| Tier | Name | Entry Criteria | Audit Depth |
|------|------|---------------|-------------|
| T1 | Burn-in | Default; <5 audits or post-circuit-breaker | Full 6-dimension audit |
| T2 | Established | See advancement criteria below | Full on unstable/marginal dims; spot-check on stable dims |
| T3 | Trusted | See advancement criteria below | Sentinel: 2 random dims full, stable dims shadow-scored |

### T1 to T2 Advancement

All conditions must be true simultaneously:
1. `total_audits >= 5`
2. Last 3 consecutive audits scored grade B or better (total >= 36)
3. No single dimension scored below 4 in the last 3 audits
4. No CUSUM alarm active on any dimension
5. Manifest has not changed since last audit (`last_manifest_fingerprint` matches)
6. `max_tier` allows T2 (all agent types qualify)

For execute-capable agents (`tool_risk: execute`): require 7+ audits instead of 5.

### T2 to T3 Advancement

All conditions must be true simultaneously:
1. `tier_audit_count >= 5` at T2 (10+ total audits minimum)
2. Last 5 consecutive audits scored grade A (total >= 48)
3. All dimensions classified Stable (see Per-Dimension Stability)
4. No CUSUM alarm triggered during entire T2 tenure
5. `max_tier` allows T3 (read-only agents only)

### Demotion Rules

- **Circuit breaker fires** — immediate T1, reset `tier_audit_count = 0`
- **Single audit drops below B at T3** — demote to T2
- **3-audit cooldown**: After circuit breaker, agent cannot advance beyond T1 for 3 audits

## Per-Dimension Stability Tracking

Each of the 6 dimensions maintains independent stability metrics. This enables dimension-level withdrawal (per CAT/IRT research, [PMC5676016](https://pmc.ncbi.nlm.nih.gov/articles/PMC5676016/): ~50% item reduction with equivalent measurement precision by targeting uncertain dimensions).

### EMA Computation

Exponential moving average with alpha=0.3 (consistent with `agent-improvement` skill):
```
ema_new = 0.3 * score_current + 0.7 * ema_previous
```
If no prior EMA exists (first audit), set `ema = score_current`.

### Rolling Variance

Computed from the rolling window of last 10 scores per dimension:
```
mean = sum(scores) / count(scores)
variance = sum((score - mean)^2 for score in scores) / count(scores)
```
If fewer than 3 scores exist, set `variance = null` (insufficient data, treated as Unstable).

### Stability Classification

| Classification | Criteria | Treatment at T2+ |
|---------------|----------|-----------------|
| Stable | ema >= 7.0 AND variance <= 1.0 AND no CUSUM alarm | Spot-check (T2) or shadow (T3) |
| Marginal | ema >= 4.0 AND variance <= 2.0 AND no CUSUM alarm | Full audit |
| Unstable | ema < 4.0 OR variance > 2.0 OR CUSUM alarm OR variance is null | Full audit (mandatory) |

### Dimension Withdrawal Order

When an agent advances to T2/T3, dimensions are withdrawn from full audit in this order (least-risk first, per SKILL0 progressive scaffolding withdrawal):

1. **D2** (Definition Quality) — most deterministic, checklist-based, only changes on manifest edit
2. **D4** (Overlap & Redundancy) — deterministic, but can shift when peer agents change
3. **D3** (Prompt Engineering) — semi-deterministic
4. **D1** (Telemetry Health) — telemetry-dependent, may fluctuate
5. **D5** (Usage Alignment) — telemetry-dependent
6. **D6** (Efficiency & Cost) — most volatile, withdraw last

A dimension is eligible for withdrawal only if classified Stable.

## Adaptive Audit Depth

Decision tree applied per-dimension on each audit invocation.

### Step 0: Load State

Read `~/.claude/audit-history/{agent-name}.json`. If file does not exist, initialize with `schema_version: 1, tier: "T1", total_audits: 0` and empty dimension records.

### Step 1: Check Manifest Change

Compute fingerprint: `name|description|tools|model|body_line_count`. Compare to stored `last_manifest_fingerprint`. If different — all dimensions FULL for this run regardless of tier.

### Step 2: Apply Depth Matrix

| Tier | Manifest Changed | Dim Stability | Depth |
|------|-----------------|---------------|-------|
| T1 | any | any | **FULL** |
| T2 | yes | any | **FULL** |
| T2 | no | Unstable or Marginal | **FULL** |
| T2 | no | Stable | **SPOT-CHECK** |
| T3 | yes | any | **FULL** |
| T3 | no | Unstable or Marginal | **FULL** |
| T3 | no | Stable | **SHADOW** |

### Depth Procedures

**FULL**: Score using the standard rubric (Dimensions 2-4 deterministic, Dimensions 1/5/6 telemetry-optional with default 5). Record score normally.

**SPOT-CHECK**: Score fully using the standard rubric. Compare result to dimension EMA:
- If `|score - ema| <= 1.5` — spot-check passes. Record score, update stats.
- If `|score - ema| > 1.5` — deviation detected. Record score, reclassify dimension stability, flag in report.

**SHADOW**: Score fully using the standard rubric. Record in `shadow_scores` array only (not in official `scores`). Official total uses `last_full_score` (carried forward). After 3 shadow scores accumulated:
- If mean of shadow scores deviates > 2.0 from `last_full_score` — silent regression detected. Restore dimension to FULL, reclassify as Marginal.
- If within 2.0 — withdrawal validated. Continue shadow mode.

**Composite scoring**: When dimensions are spot-checked or shadowed, the official total is always the sum of the 6 most recent valid scores (one per dimension). Carried-forward scores count as valid.

## CUSUM Regression Detection

Per-dimension Cumulative Sum (CUSUM) statistic for detecting small persistent score degradation. Calibrated for 0-10 dimension scores.

**Background**: CUSUM was introduced by Page (1954) for continuous inspection of sequential observations. The method accumulates deviations from a target; when the accumulation exceeds a decision threshold, an alarm signals a process shift.

> Page, E. S. (1954). "Continuous Inspection Schemes." *Biometrika*, 41(1-2), 100-115. [doi:10.1093/biomet/41.1-2.100](https://doi.org/10.1093/biomet/41.1-2.100)

### Parameters

| Parameter | Symbol | Value | Rationale |
|-----------|--------|-------|-----------|
| Allowable drift | K | 0.5 | Standard default for detecting 1-sigma shifts ([NIST Engineering Statistics Handbook 6.3.2.3.1](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc3231.htm); [Minitab CUSUM methods](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/control-charts/how-to/time-weighted-charts/cusum-chart/methods-and-formulas/methods-and-formulas/)) |
| Decision threshold | H | 3.0 | Aggressive setting (standard defaults are H=4 or H=5 per NIST/Minitab). H=3 chosen because audit frequency is low (~5-20 per agent) and false alarms are cheap to investigate. Estimated in-control ARL₀ ≈ 100 vs 336 at H=4 and 930 at H=5 ([NIST ARL table](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc3231.htm)) |
| Minimum observations | N_min | 5 | CUSUM requires sufficient baseline data; fewer than 5 scores yields unreliable EMA for the reference value |

**Note on trigger approximations**: With K=0.5 and H=3.0, the alarm triggers after approximately 6 consecutive 1-point drops or 3 consecutive 2-point drops. These are simplified estimates — actual trigger points depend on the EMA sequence and cumulative accumulation pattern, not a fixed count.

### Update Rule

Run per dimension after each FULL or SPOT-CHECK score (not after SHADOW or carried-forward):
```
S_low = max(0, S_low_prev + (ema - score - K))
```

`S_low` detects downward shifts (degradation). Only `S_low` triggers alarms.

### Alarm Condition

If `S_low > H`:
1. Set `cusum_alarm = true` for this dimension
2. Reclassify dimension as Unstable (regardless of EMA/variance)
3. If 3+ dimensions have `cusum_alarm = true` simultaneously — trigger circuit breaker (CB-4)
4. Flag in report: `"CUSUM alarm on D{N}, S_low = {value}"`

### Alarm Reset

After the next FULL audit of this dimension where the score is at or above the EMA:
- Set `cusum_alarm = false`
- Reset `S_low = 0`
- Reclassify dimension stability normally

## Circuit Breaker

Mandatory demotion to T1. Provides hard safety guarantee that no amount of historical trust overrides a severe current failure. Any single trigger fires the circuit breaker.

| ID | Trigger | Condition |
|----|---------|-----------|
| CB-1 | Grade collapse | Total score < 24 (Grade D) |
| CB-2 | Dimension floor | Any dimension scores 0 or 1 |
| CB-3 | Multi-regression | 3+ dimensions each drop >= 3 points from their EMA in a single audit |
| CB-4 | Multi-CUSUM | CUSUM alarms active on 3+ dimensions simultaneously |
| CB-5 | Manifest corruption | Frontmatter is malformed, missing `name:`, or fails YAML parse |

### On Circuit Breaker Activation

1. Set `tier = "T1"`, `tier_audit_count = 0`
2. Set all dimension stability classifications to Unstable
3. Reset all CUSUM accumulators (`cusum_s_low = 0`) for all dimensions
4. Clear all `cusum_alarm` flags
5. Record event in `circuit_breaker_history`: `{ "trigger": "CB-N", "date": "YYYY-MM-DD", "total_at_trigger": N, "dimensions_at_trigger": [N,N,N,N,N,N] }`
6. Next audit MUST be full 6-dimension (T1 behavior)
7. **3-audit cooldown**: Agent cannot advance beyond T1 for 3 audits after circuit breaker
