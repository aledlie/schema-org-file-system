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

### Pre-warm / share the easyocr Reader to amortize model-load latency

**Status:** Done
**Priority:** P3 (first-call latency; batch runs)
**Source:** easyocr integration session, 2026-06-27
**Context:** `ocr_easyocr._get_reader()` lazily builds a process-local singleton `easyocr.Reader` on first use (multi-second model load). In a batch organize run the first screenshot pays this cost mid-loop, and the Reader is not pre-warmed the way `BatchProcessor` pre-warms the CLIP cache. There is also no `clear_cache()` equivalent for tests/long-running processes to reclaim the Reader's memory (CLIPClassifier has one).

**Proposed fix:**
1. Add an optional pre-warm hook (mirror the CLIP cache pre-warm in `src/pipeline/batch_processor.py`) so the Reader loads before the per-file loop when easyocr is enabled and screenshots are expected.
2. Add a `clear_reader()`/`clear_cache()` to `ocr_easyocr` for symmetry with `CLIPClassifier.clear_cache()`.

**Affected:**
- `scripts/shared/ocr_easyocr.py`
- `src/pipeline/batch_processor.py` (pre-warm)

### easyocr screenshot path discards confidence/language/orientation

**Status:** Done
**Priority:** P3 (feature parity with docTR OCRResult)
**Source:** easyocr integration session, 2026-06-27
**Context:** `extract_text_easyocr` calls `reader.readtext(..., detail=0, paragraph=True)`, which returns plain text only. The docTR path exposes a rich `OCRResult` (confidence, language, word_count, orientation) via `extract_ocr_with_confidence`, used by the content organizer. There is currently no easyocr-backed equivalent, so any confidence-aware screenshot logic silently uses docTR even when easyocr is the active screenshot backend.

**Proposed fix:**
1. Add an easyocr variant that uses `detail=1` to recover per-box text + confidence, mapping into the existing `OCRResult` shape (language/orientation may be unavailable → `None`).
2. Route `extract_ocr_with_confidence` (or a screenshot-specific sibling) through it when `EASYOCR_AVAILABLE`, consistent with `extract_screenshot_text`.

**Affected:**
- `scripts/shared/ocr_easyocr.py` (detail=1 extraction)
- `scripts/shared/ocr_classifier.py::extract_ocr_with_confidence`

### easyocr language set hardcoded to English

**Status:** Done
**Priority:** P3 (non-English mobile captures)
**Source:** easyocr integration session, 2026-06-27
**Context:** `ocr_easyocr._EASYOCR_LANGUAGES = ["en"]`. Mobile captures and screenshots frequently contain non-English text; docTR's predictor runs with `detect_language=True`. The easyocr Reader's language list is fixed at construction and adding languages increases model load/memory, so this needs a deliberate default + override.

**Proposed fix:**
1. Make the language list configurable (env var, e.g. `OCR_EASYOCR_LANGS`, or a constant in `shared/constants.py`).
2. Default to `["en"]` to keep load cost low; document the memory/latency tradeoff of adding languages.

**Affected:**
- `scripts/shared/ocr_easyocr.py`
- `scripts/shared/constants.py` (if centralizing the default)

### easyocr not applied to the `rename_images.py --profile screenshot` flow

**Status:** Done
**Priority:** P3 (coverage gap; possible duplicate OCR backends)
**Source:** easyocr integration session, 2026-06-27
**Context:** easyocr currently routes only through `classify_by_ocr` (the content-organizer CLIP-fallback path). The standalone `rename_images.py --profile screenshot` analyzer still extracts text via docTR (`ImageAnalyzer._detect_number` at `rename_images.py:392` uses `extract_ocr_text` with a residual `--psm 10 --oem 3` tesseract config string that is now ignored). It is unclear whether the screenshot renamer profile should also prefer easyocr for its text extraction, or whether `_detect_number` (single-character sprite numbering) is better served by docTR.

**Proposed fix:**
1. Decide whether the screenshot renamer profile should share `extract_screenshot_text`.
2. Clean up the dead `config="--psm 10 --oem 3"` argument left over from the pytesseract era.

**Affected:**
- `scripts/rename_images.py:392` (`_detect_number`, and the screenshot profile's OCR usage)

### Drop stale `stash@{0}` (feat/easyocr-replaces-pytesseract WIP)

**Status:** Done
**Priority:** P3 (housekeeping)
**Source:** easyocr integration session, 2026-06-27
**Context:** `stash@{0}` ("WIP on feat/easyocr-replaces-pytesseract: 0863309") predates the CLIP/OCR consolidation; applying it earlier this session produced merge conflicts and reverted the `open_clip` refactor. Its only easyocr content was a dependency line (the real easyocr code lived in commit `0863309`'s `ocr_utils.py`). Now that easyocr is reimplemented against the current docTR architecture (commit `3af68ce`), the stash is obsolete.

**Proposed fix:** After confirming nothing else is wanted from it (`git stash show -p stash@{0}`), `git stash drop stash@{0}`.

**Affected:** git stash (no files)

