# Analysis Templates

Templates for root cause analysis and session documentation.

---

## Error Inventory Template

```markdown
## Error Inventory (Session: YYYY-MM-DD)

Total Errors: X across Y projects

| ID | Project | Component | Type | Frequency | First Seen |
|----|---------|-----------|------|-----------|------------|
| E1 | jobs | RepomixWorker | ENOENT | 140 occurrences | Nov 18 |
| E2 | AnalyticsBot | EventStream | Test failure | 20 tests | Nov 17 |
```

---

## Root Cause Analysis Template

```markdown
## Root Cause Analysis: [Error Name]

### Hypothesis 1: [Description] (X% likelihood)
**Evidence For:**
- [Supporting evidence 1]
- [Supporting evidence 2]

**Evidence Against:**
- [Contradicting evidence]

**Verification Test:**
[How to test this hypothesis]
→ Result: [What happened]

**Conclusion:** ✅ Confirmed / ❌ Not the issue

### Hypothesis 2: [Description] (X% likelihood)
**Evidence For:**
- [Supporting evidence]

**Evidence Against:**
- [Contradicting evidence]

**Verification Test:**
[How to test]
→ Result: [What happened]

**Conclusion:** ✅ Confirmed / ❌ Not the issue
```

---

## Fix Strategy Template

```markdown
## Fix Strategy: [Error Name]

### Option 1: [Description] (RECOMMENDED) ⭐
- Time: X minutes/hours
- Risk: Low/Medium/High
- Completeness: Root cause fix / Workaround
- Maintainability: [Assessment]
- Dependencies: None / [List blockers]

### Option 2: [Description]
- Time: X minutes/hours
- Risk: Low/Medium/High
- Completeness: Root cause fix / Workaround
- Maintainability: [Assessment]
- Dependencies: None / [List blockers]

### Option 3: [Description]
- Time: X minutes/hours
- Risk: Low/Medium/High
- Completeness: Root cause fix / Workaround
- Maintainability: [Assessment]
- Dependencies: None / [List blockers]

**Selected: Option X** - [Rationale]
```

---

## Session Summary Template

```markdown
# Bug Detective Session Summary
Date: YYYY-MM-DD
Duration: X hours
Repositories: [list]

## Executive Summary
[2-3 sentences on what was accomplished]

## Issues Analyzed: X
## Issues Fixed: Y
## Priority Breakdown:
- P0: X critical (Y fixed)
- P1: X high (Y fixed)
- P2: X medium (Y fixed)

## Detailed Fixes

### Fix 1: [Error Name]
**Problem:** [Description]
**Root Cause:** [What was wrong]
**Solution:** [What was done]
**Impact:** [Tests unblocked, etc.]
**Commit:** [hash]

### Fix 2: [Error Name]
...

## Remaining Issues
| Priority | Issue | Estimate | Notes |
|----------|-------|----------|-------|
| P1 | [Description] | X hours | [Notes] |
| P2 | [Description] | X hours | [Notes] |

## Lessons Learned
- [What worked]
- [What didn't]
- [Insights gained]

## Next Session Priorities
1. [First priority]
2. [Second priority]
3. [Third priority]
```

---

## Error Categories Reference

### Infrastructure
- Environment variables
- Permissions
- Dependencies
- Configuration

### Code Logic
- Null/undefined access
- Type mismatches
- Logic errors
- Race conditions

### Integration
- API changes
- Version incompatibilities
- Mock configurations
- External service failures

### Testing
- Flaky tests
- Mock issues
- Test data problems
- Coverage gaps

---

## Root Cause Categories

Common root causes to consider:
- Configuration errors (env vars, settings)
- Missing dependencies (packages, services)
- Code logic errors (bugs in implementation)
- Integration issues (API changes, version mismatches)
- Infrastructure problems (permissions, resources)
- Environmental differences (local vs prod)
