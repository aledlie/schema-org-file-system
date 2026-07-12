# Metric Definitions

All seven metrics are required for every report.

## Rule-Based Metrics (from OTel trace spans)

### tool_correctness
- **Score range:** 0.0 - 1.0
- **Source:** `hook:builtin-post-tool` and `hook:mcp-post-tool` spans
- **Formula:** `count(success=true) / count(all tool spans)`
- **Attributes:** `builtin.success` (boolean), `mcp.success` (boolean)
- **Thresholds:** healthy >= 0.95, warning 0.9-0.95, critical < 0.9

### evaluation_latency
- **Score range:** numeric (seconds)
- **Source:** All hook spans with duration
- **Formula:** `median(span.duration)` in seconds
- **Duration format:** `[seconds, nanoseconds]` tuple -> `seconds + nanoseconds / 1e9`
- **Display:** Format as milliseconds if < 1s, seconds otherwise
- **Thresholds:** healthy <= 1s, warning 1-5s, critical > 5s

### task_completion
- **Score range:** 0.0 - 1.0
- **Source:** `hook:builtin-post-tool` spans where `builtin.tool` in (TaskCreate, TaskUpdate)
- **Formula:** `count(TaskUpdate with status=completed) / count(TaskCreate)`
- **Fallback:** 1.0 if no task tools were used in the session
- **Thresholds:** healthy >= 0.9, warning 0.7-0.9, critical < 0.7
- **Caveat:** Reflects telemetry tracking ratio, not necessarily actual deliverable status

## LLM-as-Judge Metrics (always evaluated)

All four metrics use the G-Eval pattern via the `genai-quality-monitor` agent. The judge reads session outputs and scores against the user's original request.

### relevance
- **Score range:** 0.0 - 1.0
- **Question:** Does the output directly address the user's request?
- **Anchors:**
  - 1.0 = perfectly aligned with request
  - 0.7 = partially relevant, some tangential content
  - 0.0 = completely off-topic
- **Thresholds:** healthy >= 0.8, warning 0.7-0.8, critical < 0.7

### faithfulness
- **Score range:** 0.0 - 1.0
- **Question:** Are all facts, figures, and claims verifiable from source material?
- **Anchors:**
  - 1.0 = every claim traceable to sources
  - 0.7 = most claims supported, minor unsupported additions
  - 0.0 = fabricated content
- **Thresholds:** healthy >= 0.85, warning 0.8-0.85, critical < 0.8

### coherence
- **Score range:** 0.0 - 1.0
- **Question:** Is the output well-structured, logical, and readable?
- **Anchors:**
  - 1.0 = excellent flow and organization
  - 0.7 = generally readable with some structural issues
  - 0.0 = disorganized or contradictory
- **Thresholds:** healthy >= 0.8, warning 0.75-0.8, critical < 0.75

### hallucination
- **Score range:** 0.0 - 1.0 (lower is better)
- **Question:** Does the output contain invented information not in sources?
- **Anchors:**
  - 0.0 = no fabricated content
  - 0.1 = minor creative additions clearly marked
  - 1.0 = significant fabricated content
- **Thresholds:** healthy <= 0.05, warning 0.05-0.1, critical > 0.1
- **Note:** Distinguish deliberate creative additions (from explicit user request) from accidental fabrication

## Dashboard Status

The overall dashboard status is the **worst** status across all seven metrics:
- **HEALTHY** = all metrics healthy
- **WARNING** = at least one metric in warning, none critical
- **CRITICAL** = at least one metric critical

Always explain which metric triggered a non-healthy status and why.

## Output Identification for LLM-as-Judge

To find session outputs for evaluation:

1. **Content sessions:** Look for files created/modified by the session in the working directory
2. **Code sessions:** Use `git diff` or committed file paths from trace data
3. **Translation sessions:** The translated output files
4. **Report sessions:** The generated report files

The `builtin.tool` attribute on Write/Edit spans identifies which files were touched. Cross-reference with `session.id` to find session-specific outputs.
