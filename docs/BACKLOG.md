# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-06-26.

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
