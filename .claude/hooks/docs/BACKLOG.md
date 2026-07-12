# Backlog

## Open

<!-- All items resolved — see Done section and Review Findings below -->

### PERF-001: otel.test.ts cold import (~1.5s on first test) — **Done**

Hoisted `await import('./otel.js')` to top-level `beforeAll`; removed per-test `{ timeout: OTEL_IMPORT_MS }`. — `lib/otel.test.ts` (commit bdf628f)

### PERF-002: otel-monitor.test.ts cold import (~1.5s on first test) — **Done**

Hoisted `await import('./otel-monitor.js')` to top-level `beforeAll`; removed per-test timeout. — `lib/otel-monitor.test.ts` (commit bdf628f)

---

## Review Findings (Deferred)

### SEC-001: `eval "$tsc_cmd"` command injection in tsc-check.sh — **Done**
**Priority**: P0 (Critical) | **Source**: code review (tsc-check.sh)
Replaced `eval "$tsc_cmd"` with a `case` dispatch on known TSC command strings. — `tsc-check.sh:83`

### SEC-002: `eval curl` command injection in performance-monitor.sh — **Done**
**Priority**: P0 (Critical) | **Source**: code review (tsc-check.sh sourced deps)
Removed `eval curl` and replaced with direct `curl` invocations using explicit `-H` flags. — `lib/performance-monitor.sh:186`

### SEC-003: `cd` without subshell mutates working directory — **Done**
**Priority**: P1 (High) | **Source**: code review (tsc-check.sh)
Wrapped `get_tsc_command` and `run_tsc_check` bodies in `() (` subshells. — `tsc-check.sh` (commit 62db09f)

### SEC-004: Unquoted `$REPOS_TO_CHECK` word-splitting — **Done**
**Priority**: P1 (High) | **Source**: code review (tsc-check.sh)
Replaced with bash array via `while IFS= read -r` loop; all expansions use `"${arr[@]}"`. — `tsc-check.sh` (commit 62db09f)

### SEC-005: `$CLAUDE_PROJECT_DIR` not validated — **Done**
**Priority**: P1 (High) | **Source**: code review (tsc-check.sh)
Added `[ ! -d "$CLAUDE_PROJECT_DIR" ]` existence check with early exit. — `tsc-check.sh` (commit 62db09f)

### T3: Remove unreachable dead-code guard in retryWithBackoff — **Done**
**Priority**: P2 | **Source**: final code review (a29d9619eda092856)
Removed unreachable `if (!lastError)` guard. — `lib/exponential-backoff.ts` (commit ce7c2d3)

### T4: Add test for maxRetries < 1 (negative value) — **Done**
**Priority**: P3 | **Source**: final code review (a29d9619eda092856)
Added test for `maxRetries: -1`. — `lib/exponential-backoff.test.ts` (commit ce7c2d3)

### T5: Improve caps delay test with length assertion — **Done**
**Priority**: P3 | **Source**: final code review (a29d9619eda092856)
Added `expect(delays).toHaveLength(4)`. — `lib/exponential-backoff.test.ts` (commit ce7c2d3)

### TSC-001: Redundant `grep -c` invocation — **Done**
**Priority**: P2 (Medium) | **Source**: code review (tsc-check.sh)
Computed `TS_ERROR_COUNT` once into variable. — `tsc-check.sh` (commit 62db09f)

### TSC-002: Dead code — `tsconfig.app.json` check inside unreachable branch — **Done**
**Priority**: P2 (Medium) | **Source**: code review (tsc-check.sh)
Removed dead `tsconfig.app.json` branch from inside `elif tsconfig.json` block. — `tsc-check.sh` (commit 62db09f)

### TSC-003: Redundant jq parsing of `$TOOL_INPUT` — **Done**
**Priority**: P2 (Medium) | **Source**: code review (tsc-check.sh)
Removed `TOOL_INPUT` variable; file paths parsed directly from `$HOOK_INPUT`. — `tsc-check.sh` (commit 62db09f)

### TSC-004: Cache file written with no integrity protection — **Done**
**Priority**: P2 (Medium) | **Source**: code review (tsc-check.sh)
Cache now stores enum keys (app/build/src/build-noconfig/default); written with `chmod 600`. — `tsc-check.sh` (commit 62db09f)

### TSC-005: `find` missing `-mindepth 1` may delete cache root — **Done**
**Priority**: P3 (Low) | **Source**: code review (tsc-check.sh)
Added `-mindepth 1` to find cleanup command. — `tsc-check.sh` (commit 62db09f)

### TSC-006: `SESSION_ID` unsanitized — **Done**
**Priority**: P3 (Low) | **Source**: code review (tsc-check.sh)
Sanitized with `tr -cd '[:alnum:]-_'` and fallback to `default`. — `tsc-check.sh` (commit 62db09f)

### TSC-007: `perf_end` status string doesn't match OTEL error pattern — **Done**
**Priority**: P3 (Low) | **Source**: code review (tsc-check.sh)
Changed to `perf_end "error-tsc-errors-found"`. — `tsc-check.sh` (commit 62db09f)

### BUG-001: OVERFLOW stderr noise in session-start tests — **Done**
**Priority**: Low | **Source**: test suite stderr
Already fixed — `beforeEach`/`afterEach` in `describe('getUtilizationBar')` mocks `console.error`. — `handlers/session-start.test.ts:27-33`

### PERF-003: exponential-backoff.test.ts suite takes 2.5s — **Done**
**Priority**: Medium | `delayFn` injection already in codebase; suite now runs in 88ms.

### PERF-004: file-utils.test.ts lock tests take 1.6s — **Done**
**Priority**: Medium | Lock tests now run in 5ms.

### PERF-005: langtrace.test.ts suite takes 1.5s — **Done**
**Priority**: Low-Medium | Suite now runs in 225ms.

### PERF-006: load-envrc.test.ts suite takes 1.6s — **Done**
**Priority**: Low-Medium | Suite now runs in 167ms.

### PERF-007: Overall test suite duration (40.9s) exceeds 30s target — **Done**
**Priority**: Meta | Full suite now runs in ~6s. Target (<30s) met.

---

## Code Review Findings (Not Yet Implemented)

### CQ-001: Cache staleness via unvalidated enum key in tsc-check.sh — **Done**
**Priority**: P2 (Medium) | **Source**: final code review (db6a1b9)
Added tsconfig mtime check; cache auto-invalidates when any tsconfig*.json is newer than cache file. — `tsc-check.sh` (commit e0139a0)

### CQ-002: Inner loop whitespace handling in tsc-check.sh — **Done**
**Priority**: P3 (Low) | **Source**: final code review (db6a1b9)
Added `IFS=` to inner `while read -r file_path` loop for whitespace safety. — `tsc-check.sh` (commit e0139a0)

### CQ-003: Type narrowing assertion for lastError in exponential-backoff.ts — **Done**
**Priority**: P3 (Low) | **Source**: final code review (db6a1b9)
Added `throw lastError!` with loop invariant comment. — `lib/exponential-backoff.ts` (commit 3922dd6)

### CQ-004: Test coverage gap for delayFn consistency — **Done**
**Priority**: P3 (Low) | **Source**: final code review (db6a1b9)
Added test asserting `delayFn` receives same delay values as `onRetry`. — `lib/exponential-backoff.test.ts` (commit 3922dd6)

### CQ-005: TOCTOU race on `entries.length` in parseWritePath
**Priority**: P3 (Low) | **Source**: final code review (cf629fd)
Detect version directory as "new" by counting entries (>1 = existing). After process restart, any version dir with exactly 1 file re-fires. Mitigated by README comparison idempotency (line 157). Consider persisting processed versions to cache or inverting logic to compare detected version vs current README link. — `handlers/post-tool-changelog-sync.ts:94-96`

### CQ-006: MKDIR_CHANGELOG_PATTERN doesn't match trailing flags
**Priority**: P4 (Very Low) | **Source**: final code review (cf629fd)
Regex `(?:(?:--?\w+)\s+)*` requires flags in contiguous block before path. Edge case: `mkdir docs/changelog/1.2 --verbose` silently misses. No impact (Write route provides fallback), but coverage could be expanded. — `handlers/post-tool-changelog-sync.ts:38`

### CQ-007: getStringField coerces non-string tool_input values
**Priority**: P4 (Very Low) | **Source**: final code review (cf629fd)
`String(ti[key])` on non-string values returns `"[object Object]"`. Prefer narrowing to `typeof val === 'string'` for clarity and safety. Safe in practice (patterns won't match), but defensive. — `handlers/post-tool-changelog-sync.ts:29`
