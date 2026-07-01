# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-01.

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

**Status:** Won't do (documented) — revisit only if a tz-aware DB backend (e.g. Postgres) is added.
**Priority:** P4 (no active bug; no benefit on the current backend)
**Source:** datetime.utcnow deprecation fix, 2026-06-27; audited 2026-07-01
**Context:** `datetime.utcnow()` was deprecated on Python 3.12+. The fix introduced `src/storage/_time.py::utcnow()` returning a **naive** UTC datetime as a behavior-preserving drop-in. It is used consistently across the storage layer (`models.py`, `graph_store.py`, `kv_store.py`, `migration.py`) — no stray `datetime.utcnow()` remains. The deprecation warning is gone and timestamps are naive-but-consistent.

**Audit finding (2026-07-01) — why this is closed:** the store is **SQLite-only** (`create_engine('sqlite:///…')` in `graph_store.py` and `kv_store.py`). SQLite has no native timezone type, so SQLAlchemy `DateTime(timezone=True)` is a **no-op** there — it does not persist tzinfo and returns **naive** datetimes on read. Flipping the column type buys nothing. Flipping `_time.py` to aware *without* a read-side coercion layer is a regression, not a cleanup: a fresh aware `utcnow()` compared against a DB-loaded naive `expires_at` raises `TypeError: can't compare offset-naive and offset-aware` in the `kv_store.py` TTL paths (lines ~117, 223, 600, 674, 743). The naive helper is the correct pragma for a single-backend SQLite store; aware UTC buys nothing until the backend changes.

**Corrections to the earlier proposed fix (now superseded):**
- Golden snapshots do **not** need updating — `test_generate_schema_golden.py::_VOLATILE_KEYS` already normalizes `dateCreated`/`dateModified`/`uploadDate` to `<normalized>` before diffing.
- `tests/unit/test_base.py` date assertions feed **explicit input datetimes**, not `utcnow()`, so they are unaffected.
- The plan omitted the one step that actually matters on SQLite: a `TypeDecorator` (`UtcDateTime`) coercing naive→aware(UTC) on every read.

**If revisited (Option B — only with a tz-aware backend):**
1. Add a `UtcDateTime` `TypeDecorator` that coerces naive→aware(UTC) on read; apply to all `DateTime` columns.
2. Switch `_time.py::utcnow()` to `datetime.now(timezone.utc)` (aware).
3. Audit `timeline_api.py:308` and `organized_at`/`started_at`/`completed_at` isoformat consumers for the added `+00:00` suffix.
4. No data-rewrite migration needed — read-side coercion handles legacy naive rows.

**Secondary (pre-existing, low risk):** `migration.py:271` sets `exif_datetime = datetime.fromisoformat(...)`, which is aware or naive depending on the EXIF string. Output-only (never compared), so an inconsistency, not a live bug.

**Affected (if revisited):**
- `src/storage/_time.py` (aware return)
- `src/storage/models.py` (column types + `UtcDateTime` TypeDecorator)
- `src/storage/kv_store.py` (comparison/arithmetic audit)
- `src/api/timeline_api.py` + any JSON-LD output consumers (offset format change)


