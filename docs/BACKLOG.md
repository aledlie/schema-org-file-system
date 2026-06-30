# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-06-27.

## Open Items

### Test set class imbalance in model evaluation

**Status:** Open
**Priority:** P3 (support starvation issue — not a model issue)
**Source:** model-evaluation session, 2026-05-16
**Context:** Classes with ≤2 samples (financial, property, technical, business, personal, legal, medical, filepath, creative) all score 0% precision/recall in evaluation. This is a test set issue, not a model issue — the classes have insufficient representation to meaningfully test or train.

**Proposed fix:** Two options:
  1. Rebalance the test set in `scripts/data_preprocessing.py` to ensure all categories have ≥30 samples (or adjust threshold as appropriate).
  2. Report evaluation metrics weighted only on classes with adequate support (e.g., support ≥ 30) to avoid reporting misleading per-class metrics.

Consider which approach aligns with project goals: broader coverage (option 1) or more honest metrics on well-represented classes (option 2).

**Affected:**
- `scripts/data_preprocessing.py` (class rebalancing, if choosing option 1)
- `scripts/evaluate_model.py` (metric filtering, if choosing option 2)

### Migrate storage timestamps to timezone-aware datetimes

**Status:** Open
**Priority:** P3 (correctness/cleanliness; no active bug)
**Source:** datetime.utcnow deprecation fix, 2026-06-27
**Context:** `datetime.utcnow()` was deprecated on Python 3.12+. The fix introduced `src/storage/_time.py::utcnow()` returning a **naive** UTC datetime as a behavior-preserving drop-in, because all storage `DateTime` columns are timezone-naive and `kv_store` compares stored timestamps against "now" (a naive→aware switch would change `.isoformat()` output and raise "can't compare offset-naive and offset-aware datetimes"). The naive helper silences the warning but leaves timestamps timezone-unaware — the modern-correct model is tz-aware UTC.

**Proposed fix:**
1. Change `DateTime` columns to `DateTime(timezone=True)` in `src/storage/models.py`.
2. Switch `_time.py::utcnow()` to return `datetime.now(timezone.utc)` (aware).
3. Audit `kv_store.py` comparisons/arithmetic for naive↔aware consistency.
4. Add a DB migration for existing rows and update any tests/golden snapshots that assert on `.isoformat()` output (aware adds a `+00:00` offset to `dateCreated`/`dateModified`).

**Affected:**
- `src/storage/_time.py` (aware return)
- `src/storage/models.py` (column types)
- `src/storage/kv_store.py` (comparison/arithmetic audit)
- `src/storage/migration.py` (data migration)
- `tests/integration/` + any JSON-LD output assertions (offset format change)


