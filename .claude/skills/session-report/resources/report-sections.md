# Report Section Templates

Detailed templates for each report section.

---

## 1. Title and Metadata (Required)

```markdown
**Session Date**: YYYY-MM-DD<br>
**Project**: Project Name (e.g., ast-grep-mcp, AnalyticsBot)<br>
**Focus**: Brief description of session focus<br>
**Session Type**: Completion verification | Implementation | Migration | Refactoring
```

**Important**: Use `<br>` tags at the end of each line (except last) for proper Jekyll rendering.

---

## 2. Executive Summary (Required)

2-3 paragraphs with **quantified metrics**:
- What was accomplished (use specific numbers)
- Key metrics or results (percentages, counts, time savings)
- Business/technical impact

**Example:**
> Successfully completed Phase 2 of the optimization roadmap. Implemented SHA256-based score caching achieving **20-30% speedup**. Combined with batch test coverage (60-80%) and early exit optimization (5-10%), achieved **85-120% cumulative performance improvement**.

---

## 3. Key Metrics Table (Highly Recommended)

**Important**: Tables require a blank line before them for kramdown.

```markdown
**Key Metrics:**

| Metric | Value |
|--------|-------|
| **Services Refactored** | 3 |
| **New Modules Created** | 16 |
| **Code Reduction** | 70% |
| **Tests Passing** | 31/31 (100%) |
| **Breaking Changes** | 0 |
```

---

## 4. Problem Statement (Recommended)

Explain:
- Why this work was needed
- What problem was being solved
- Impact before the fix (quantified when possible)

---

## 5. Implementation Details (Required)

Document with **code examples** and **file references with line numbers**:

```markdown
### Phase 1: Component Updates

**File**: `src/services/ranker.py:19-221`

#### Key Components

**1. Cache Infrastructure**
\`\`\`python
class DuplicationRanker:
    def __init__(self, enable_cache: bool = True) -> None:
        self._score_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
\`\`\`

**Design Decisions:**
- SHA256 hashing for determinism
- Default enabled for maximum benefit
```

---

## 6. Before/After Comparisons (Recommended for Refactoring)

```markdown
| Aspect | Before | After | Change |
|--------|--------|-------|--------|
| **Total Lines** | 440 | 115 avg | -76% |
| **Cyclomatic Complexity** | 8 | 3 | -63% |
| **Test Pass Rate** | 95% | 100% | +5% |
```

---

## 7. Testing and Verification (Required)

Include actual test output:

```markdown
### Test Results

\`\`\`bash
$ npm run test
======================== test session starts =========================
collected 20 items
tests/unit/test_ranker_caching.py::TestScoreCaching PASSED [100%]
======================= 20 passed in 0.13s ==========================
\`\`\`

| Test Suite | Tests | Passed | Status |
|------------|-------|--------|--------|
| Unit Tests | 31 | 31 | PASS |
| Integration | 15 | 15 | PASS |
```

---

## 8. Key Decisions and Trade-offs (Recommended)

```markdown
### Decision 1: SHA256 vs Simple Dict Hashing
**Choice**: SHA256 hashing
**Rationale**: Deterministic, collision-resistant, fast (<1ms)
**Alternative Considered**: Python's `hash()`, rejected due to non-determinism
**Trade-off**: Slight overhead for correctness guarantee
```

---

## 9. Challenges and Solutions (Optional)

```markdown
### Challenge 1: Color Contrast Complexity
**Problem**: Global variable change caused violations to INCREASE from 2 to 7
**Root Cause**: Gray color used throughout site for various elements
**Solution**: Applied targeted overrides to specific elements only
**Lesson Learned**: Always test global variable changes thoroughly
```

---

## 10. Files Modified/Created (Required)

```markdown
## Files Modified

### Created Files (18 total)
- `backend/src/services/inventory/types.ts` (55 lines)
- `backend/src/services/inventory/PaginationManager.ts` (90 lines)

### Modified Files (3)
- `src/utils/error-utils.ts` - Sentry v8 API update
```

---

## 11. Git Commits (Recommended)

```markdown
## Git Commits

| Commit | Description | Files | Lines |
|--------|-------------|-------|-------|
| `d8e919e` | refactor(inventory): modularize service | 9 | +1,297/-492 |
| `b2617db` | refactor(filesystem): extract modules | 9 | +1,209/-498 |
```

---

## 12. Next Steps (Optional)

```markdown
## Next Steps

### Immediate
1. Verify errors appear in Sentry dashboard

### Short-term (Next Session)
2. **Bug #3**: Landmark Structure Refactor (8 hours)

### Medium-term
3. CI/CD improvements (2.5 hours)
```

---

## 13. References (Required)

```markdown
## References

### Code Files
- `src/features/deduplication/ranker.py:19-221` - Score caching
- `tests/unit/test_ranker_caching.py:1-324` - Test suite

### Documentation
- [WCAG 2.4.3: Focus Order](https://www.w3.org/WAI/WCAG21/Understanding/focus-order.html)
- Previous session: `2025-11-28-phase-2-performance-optimizations.md`
```
