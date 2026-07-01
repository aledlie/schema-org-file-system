# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-01.

## Open Items

### [P1 / SECURITY] Scrub driver's-license PII from git history before any push

**Status:** Open — **blocks first push of `main`**
**Priority:** P1 (biometric PII in version-control history)
**Source:** test-set augmentation, 2026-07-01
**Context:** `results/test_set_augmentation/redacted/460014_alyshia_mledlie_p1.png` and `_p2.png` are a **driver's license**. OCR-based redaction (`scripts/redact_pii.py`) blacked out digits/name but **cannot remove the biometric face photo or physical description** — non-text PII is outside the tool's reach. The files were removed from the working tree in commit `1eacc17`, but the blobs still exist in history at commit `faf8586`. `main` has **never been pushed** (origin is at `ff6e6c4`), so the PII has not left the machine — but it must be scrubbed before the first push.

**Fix (run when the checkout is quiet — history rewrite changes all SHAs; do not run with concurrent Claude sessions active):**
```
git filter-repo --invert-paths \
  --path results/test_set_augmentation/redacted/460014_alyshia_mledlie_p1.png \
  --path results/test_set_augmentation/redacted/460014_alyshia_mledlie_p2.png
```
(or drop the two files from `faf8586` via interactive rebase). Verify with `git log --all --oneline -- 'results/test_set_augmentation/redacted/460014*'` returning nothing.

**Root-cause note — `redact_pii.py` blind spots** (also in CLAUDE.md Gotchas): OCR redaction cannot remove (a) **biometric photos** (driver's license, passport), (b) **OCR-unreadable stylized text** (the certificate was excluded for a machine-invisible but human-readable name), or (c) **alphabetic PII** (addresses, third-party names). Never commit such documents on OCR-redaction alone.

### Test set class imbalance in model evaluation

**Status:** Reframed (2026-07-01) — original premise was wrong; residual work is classifier accuracy + coverage, not sample count.
**Priority:** P3
**Source:** model-evaluation session, 2026-05-16; investigated 2026-07-01
**Original context:** Classes with ≤2 samples scored 0% F1; assumed a test-set support-starvation issue.

**2026-07-01 investigation findings:**
- The old `evaluate_model.py` ran only the **filename-heuristic baseline** (`FileCategorizationModel`), which has *no code path* to medical/financial/personal/property/business — so those classes scored 0% regardless of sample count. Fixed by adding `--classifier content` (runs the production `ContentBasedFileOrganizer` CLIP+OCR pipeline).
- Test-set label vocabulary **already matches** the production classifier (verified by set-diff against the full production vocab). Earlier "taxonomy mismatch" reports (`financial→media`, `medical→game_assets`) were **misclassifications**, not label problems.
- `filepath` **is** a valid production category (the filepath-matching stage emits it); do not treat it as alien vocab.
- Insurance cards classify as `medical`/`insurance` (not `identification`); an intermediate relabel to `identification` was reverted. `fonts` and `research` samples were verified to classify correctly under `--classifier content`.

**Remaining work (real, not sample count):**
1. **Classifier accuracy** — under `--classifier content`, scanned financial statements classify as `media` and medical scans as `game_assets` (CLIP sees a document raster as a generic image). Improve via CLIP vocab / OCR-first routing for document-type rasters.
2. **Coverage gaps** — production categories `person`, `identification`, `other` still have **no** test samples. `fonts` and `research` were added 2026-07-01 (`results/test_set_augmentation/`). `identification` needs a real ID doc, but the only candidate (a driver's license) was removed for biometric PII — source a synthetic/sample ID.
3. **Option 2 still valid** — report per-class metrics only for classes with adequate support to avoid misleading 0%s.

**Affected:**
- `scripts/evaluate_model.py` (content classifier path — done; metric filtering — pending)
- `src/classifiers/content_classifier.py`, CLIP vocab (accuracy on document rasters)

### Reconcile `person` vs `personal` category convention

**Status:** Open
**Priority:** P3 (taxonomy ambiguity; causes avoidable eval misses)
**Source:** test-set / classifier alignment, 2026-07-01
**Context:** The production classifier can emit **both** `person` and `personal` as a file's main category, from two different stages of `detect_file_category`:
- **Person entity detection** (Classification Priority #2) fires first for name-bearing documents (resumes, signatures, contact info) → returns `person`.
- **Content classification** (`content_classifier.py`, later stage) has a `personal` document category → returns `personal` when no person entity is detected.

Because Person detection runs earlier and wins, a personal document that names an individual is labeled `person`, while an equivalent one without a detectable name is labeled `personal`. The split is an artifact of stage ordering, not a meaningful semantic distinction, and it produces avoidable evaluation misses (test label `personal` vs prediction `person`).

**Proposed fix (define a convention):**
1. Decide the canonical taxonomy: either (a) **merge** — treat `person` as the entity/owner and `personal` as the document class, and have the evaluator map one to the other; or (b) **keep distinct** with an explicit rule (e.g., `person` = files attributable to a specific named individual; `personal` = personal-life documents with no identified person) and relabel the test set accordingly.
2. Document the chosen convention in `CLAUDE.md` (Classification Priority) and apply it consistently in `content_classifier.py` and any test-set labels.
3. Add an evaluator alias/mapping layer if (a) is chosen so `person`/`personal` are scored consistently.

**Affected:**
- `src/classifiers/content_classifier.py` (category vocabulary)
- `scripts/file_organizer_content_based.py` (`detect_file_category` stage ordering)
- `CLAUDE.md` (Classification Priority documentation)
- test-set labels + `scripts/evaluate_model.py` (optional alias mapping)

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


