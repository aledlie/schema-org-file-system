# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-06-27.

## Open Items

### Add low-confidence → uncategorized rule in evaluator

**Status:** Open
**Priority:** P2 (271 uncategorized → media misclassifications)
**Source:** model-evaluation session, 2026-05-16
**Context:** 271 uncategorized files are being misclassified as media. Root cause: `FileCategorizationModel.predict_category` never emits 'uncategorized' for image files — it always falls through to `('media', 'photos_other', 0.6)`. The evaluator needs explicit logic to route low-confidence predictions to uncategorized.

**Proposed fix:** Two options:
  1. Add explicit low-confidence threshold (e.g., max score < 0.5) that routes to 'uncategorized' instead of falling through to default media category.
  2. Further relabel the test set (scripts/data_preprocessing.py) if these low-confidence files are actually disguised game assets or other hard categories.

**Affected:**
- `scripts/evaluate_model.py:60-61` (prediction routing)
- `src/classifiers/file_categorization_model.py` (predict_category logic, if choosing option 1)
- `scripts/data_preprocessing.py` (test set relabeling, if choosing option 2)

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

### ~~`media` category acts as a catch-all in classifier output~~

**Status:** Done (2026-06-27) — investigated; hypothesis disproven for production, no code change warranted.
**Priority:** P2 (drives most evaluation false positives)
**Source:** model-evaluation session, 2026-05-16
**Context:** On the December test set, the classifier appeared to route `uncategorized → media` (265), `game_assets → media` (213), and `property_management → media` (20), with `media` precision 27.94% / recall 92.42% — consistent with `media` being a fallback. This was a hypothesis derived from the misclassification table, not a verified code claim.

**Findings (cascade audit, 2026-06-27):**
- Production has **no single terminal `media` catch-all**. The terminal fallback in `detect_file_category` → `_classify_by_content_and_kie` → `ContentClassifier.classify_content` is **`('uncategorized', 'other')`** (`content_classifier.py:575/580/669`).
- `media` is assigned *conditionally by extension* in `classify_media_file` (Priority 4): unconditional for **video** (any ext), **audio** `.mp3/.m4a/.aac/.flac/.wma`, and **`.jpg/.jpeg/.heic` without EXIF** (line 2430). **`.png/.gif/.webp/.bmp/.tiff`** without metadata fall through (line 2435) to CLIP/OCR/KIE and default to `uncategorized` — i.e. the dominant ambiguous case already routes correctly.
- The cited misclassification numbers were an **artifact of `scripts/evaluate_model.py`**, whose old logic mapped *every* image to `media/photos_other 0.6` and did not simulate production's conditional gating. Fixed under the "low-confidence → uncategorized rule in evaluator" item (commit `b5a9295`): the evaluator now gates `media` on photo evidence, lifting media precision 27.94% → 68.86%.
- Evidence-gated check of the one residual spot (line 2430, `.jpg/.jpeg/.heic` → `media`): of 66 such files reaching it, 57 are ground-truth `media` and the 9 "non-media" are real photos **mislabeled** `game_assets` in the test set (healthcare stock photos, company OG images). Tightening line 2430 would push correctly-classified photos out of `media` and regress production. **No genuine over-assignment observed → no change made.**

**Follow-up (resolved 2026-06-27):** the 8 misfiled `.jpg` photos labeled `game_assets` (healthcare/company/art images under `Media/Photos/Other`) were corrected to `media` in the relabel track — `relabel_test_set.py` gained pass 6 (non-`Games` JPEG/HEIC `game_assets` → `media`) and pass 2 no longer promotes photo-extension files. Eval accuracy held (93.28% → 93.26%); `media` support corrected 211 → 220. Commit `6fada91`.

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

### ~~Remove obsolete renamer files re-added on `feat/easyocr-integration`~~

**Status:** Done (2026-06-29) — both files deleted; entry point and importers verified clean.
**Priority:** P1 (blocks clean merge of `feat/easyocr-integration`; one file is import-broken)
**Source:** easyocr integration session, 2026-06-27
**Context:** A concurrent Claude session created branch `feat/easyocr-integration` and commit `045d3d3` ("salvage compatible parts of easyocr WIP stash"), which restored `scripts/image_content_renamer.py` and `scripts/screenshot_renamer.py` — the pre-consolidation files that refactor `725f7a8` deliberately deleted when unifying the renamers into `scripts/rename_images.py` + `scripts/shared/`. `screenshot_renamer.py:23` imports `from shared.ocr_utils import ...`, but `ocr_utils.py` no longer exists (it became `shared/ocr_classifier.py`), so the file fails to import. The later easyocr commit (`3af68ce`) does not depend on either file.

**Resolution (2026-06-29):**
1. `git rm scripts/image_content_renamer.py scripts/screenshot_renamer.py`.
2. Confirmed no code imports either file — the only residual mentions are comments (`rename_images.py:4` historical docstring; `filename_classifier.py:1040/1061` describe the on-disk filename pattern produced by the old tool, not a code dependency). Consolidated entry point `rename_images.py --profile {photo,screenshot}` parses clean.
3. The other `045d3d3` edits are kept: `requirements.txt` `easyocr>=1.7.0` is now genuinely used by `3af68ce`, and the `CLIPClassifier.get_instance()` changes in `analyze_renamed_files.py` / `image_content_analyzer.py` are compatible.

**Affected:**
- `scripts/image_content_renamer.py` (deleted)
- `scripts/screenshot_renamer.py` (deleted)

### Benchmark easyocr vs docTR accuracy on the screenshot test set

**Status:** Open
**Priority:** P2 (validates the premise behind the whole easyocr integration)
**Source:** easyocr integration session, 2026-06-27
**Context:** easyocr was wired into the screenshot/mobile OCR path (`extract_screenshot_text` → `classify_by_ocr`) on the asserted basis that it is "more accurate on screenshots and mobile UI text" than docTR — but this was never measured against this project's data. The selector currently *always* prefers easyocr when installed; if easyocr is in fact worse on some screenshot classes, this regresses classification silently.

**Proposed fix:**
1. Assemble (or reuse) a labeled screenshot/mobile-capture subset of the eval set.
2. Run both backends (`extract_text_easyocr` vs `extract_ocr_text`) and compare downstream `classify_by_ocr` category accuracy + raw text quality (char-error-rate against ground truth where available).
3. If mixed, replace the unconditional preference with an evidence-based choice (e.g., easyocr only for high-density UI text / small fonts; docTR otherwise) or add a confidence-gated fallback.
4. Record results so the preference order is justified, not assumed.

**Affected:**
- `scripts/evaluate_model.py` or a new bench under `tests/performance/`
- `scripts/shared/ocr_classifier.py::extract_screenshot_text` (selection logic, if findings warrant)

### easyocr runs CPU-only on Apple Silicon (MPS unused)

**Status:** Open
**Priority:** P2 (latency on the primary dev platform; macOS arm64)
**Source:** easyocr integration session, 2026-06-27
**Context:** `ocr_easyocr._use_gpu()` returns `torch.cuda.is_available()`, so on macOS (MPS) and CPU-only hosts easyocr loads with `gpu=False`. easyocr historically has no MPS backend, so this is currently correct — but it means every screenshot OCR on the dev machine runs on CPU, which is slow for the per-image readtext path. Verified at runtime: the Reader logs `pin_memory ... not supported on MPS` and falls back to CPU.

**Proposed fix:**
1. Confirm current easyocr (≥1.7.2) still lacks usable MPS support; if a build supports it, allow `gpu=True` (or `gpu='mps'`) on MPS.
2. Otherwise, document the CPU limitation and consider: (a) caching OCR results per image like the CLIP embedding cache, and/or (b) restricting easyocr to the cases where its accuracy edge justifies the CPU cost (see the benchmark item above).

**Affected:**
- `scripts/shared/ocr_easyocr.py::_use_gpu` / `_get_reader`

### Pre-warm / share the easyocr Reader to amortize model-load latency

**Status:** Open
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

**Status:** Open
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

**Status:** Open
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

**Status:** Open (uninvestigated)
**Priority:** P3 (coverage gap; possible duplicate OCR backends)
**Source:** easyocr integration session, 2026-06-27
**Context:** easyocr currently routes only through `classify_by_ocr` (the content-organizer CLIP-fallback path). The standalone `rename_images.py --profile screenshot` analyzer still extracts text via docTR (`ImageAnalyzer._detect_number` at `rename_images.py:392` uses `extract_ocr_text` with a residual `--psm 10 --oem 3` tesseract config string that is now ignored). It is unclear whether the screenshot renamer profile should also prefer easyocr for its text extraction, or whether `_detect_number` (single-character sprite numbering) is better served by docTR.

**Proposed fix:**
1. Decide whether the screenshot renamer profile should share `extract_screenshot_text`.
2. Clean up the dead `config="--psm 10 --oem 3"` argument left over from the pytesseract era.

**Affected:**
- `scripts/rename_images.py:392` (`_detect_number`, and the screenshot profile's OCR usage)

### Drop stale `stash@{0}` (feat/easyocr-replaces-pytesseract WIP)

**Status:** Open
**Priority:** P3 (housekeeping)
**Source:** easyocr integration session, 2026-06-27
**Context:** `stash@{0}` ("WIP on feat/easyocr-replaces-pytesseract: 0863309") predates the CLIP/OCR consolidation; applying it earlier this session produced merge conflicts and reverted the `open_clip` refactor. Its only easyocr content was a dependency line (the real easyocr code lived in commit `0863309`'s `ocr_utils.py`). Now that easyocr is reimplemented against the current docTR architecture (commit `3af68ce`), the stash is obsolete.

**Proposed fix:** After confirming nothing else is wanted from it (`git stash show -p stash@{0}`), `git stash drop stash@{0}`.

**Affected:** git stash (no files)

### Guard against multi-agent shared-working-dir collisions

**Status:** Open
**Priority:** P2 (process/safety; recurrence of a previously-recorded issue)
**Source:** easyocr integration session, 2026-06-27
**Context:** During this session a *separate* concurrent Claude process created branch `feat/easyocr-integration` and committed `045d3d3` in the **shared** repo working directory, which silently reverted cleanup done on `main` in this session (checked-out branch changed under us). Four `claude` processes were running against the same checkout. This is a recurrence of the pattern recorded in project memory ("forked skill made unauthorized commits; audit git after any write-capable fork"). The repo already uses isolated `worktree-agent-*` branches for parallel work, so the collision came from agents operating directly in the primary checkout rather than in worktrees.

**Proposed fix:**
1. Establish a convention that parallel/background agents must run in their own git worktree (the repo already has the `worktree-agent-*` pattern + `EnterWorktree` tooling), never the shared primary checkout.
2. Consider a pre-write/pre-commit guard that warns when more than one agent session has the same checkout open, or asserts the expected branch before committing.
3. Audit git state at session start when background agents may be active (the memory note already advises this).

**Affected:**
- Process/tooling (no single source file); optionally a guard hook under `hooks/`
