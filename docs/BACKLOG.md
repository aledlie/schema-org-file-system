# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-06-26.

## Open Items

### Improve OCR preprocessing for dark-background screenshots

**Status:** Open
**Depends on:** docTR migration (done)
**Context:** Priority 4.5 screenshot sub-classification (added 2026-03-31) correctly routes screenshots to OCR/CLIP, but ~87 raw `Screenshot*` files in `~/Documents/Media/Photos/Screenshots/` remain unclassified because docTR produces no usable text on dark-background terminal/IDE/dashboard screenshots and CLIP scores are uniformly ~5% (below the 15% threshold).

- Add image inversion preprocessing in `scripts/shared/ocr_utils.py` for dark-background images (detect mean luminance < threshold, invert before OCR)
- Consider adaptive contrast enhancement (CLAHE) as a second pass when initial OCR yields < 30 chars
- Evaluate lowering `CLIP_ENHANCE_THRESHOLD` for screenshot-specific classification (currently 0.15, screenshots score ~0.05)
- Add `_SCREENSHOT_KEYWORDS` entries for IDE/code patterns (`import`, `function`, `class`, `def`, `const`) and browser patterns (`http`, `www`, `.com`, `search`)

### ~~Filename-pattern classification duplicated across two organizers~~

**Status:** Done (2026-06-27)
**Context:** The two `classify_by_filename_patterns` copies had drifted well past "near-identical" — the live script was a ~1530-line superset (research-paper detection, structured screenshot patterns, more rules) and `content_organizer` a stale ~779-line copy used only by its own unit test (~459 net divergent lines).

**Fix:** extracted the script's canonical rule set into `scripts/shared/filename_classifier.py` as a free function `classify_by_filename_patterns(file_path, *, game_sprite_keywords, last_file_state=None) -> (category, subcategory, organization, people) | None`. The research helpers (`RESEARCH_CATEGORY`, `SCHOLARLY_ARTICLE_SCHEMA_TYPE`, `_detect_research_publisher`, `_RESEARCH_PREFIX_PATTERNS`) moved into the shared module too. Both organizers now delegate; instance-specific state (sprite vocabulary, the per-file research side-channel) is passed in. `content_organizer` adopted the superset (its behavior now matches production).

**Validation:**
- Live path proven **byte-identical**: old vs new over 6027 Dec filenames (incl. the research side-channel state) → 0 mismatches.
- `pytest tests/unit/` → 771 passed, 2 skipped. Updated one `content_organizer` test (`test_screenshot_detected` → split into `test_software_screenshot_detected` + `test_bare_screenshot_deferred`) to match the production contract: structured `<kind>_<8hex>` screenshots match at the filename stage; bare `screenshot_*` defers to the later OCR/`SCREENSHOT_KEYWORDS` stage.
- Removed now-dead `_EXTRA_GAME_AUDIO_FP_KEYWORDS` from `content_organizer`. New module + script lint clean.

**Affected:**
- `scripts/shared/filename_classifier.py` (new — single source of truth)
- `scripts/file_organizer_content_based.py` (delegates; research helpers re-exported)
- `src/organizers/content_organizer.py` (delegates; dead keyword set removed)
- `tests/unit/test_content_organizer.py` (screenshot test updated to production contract)

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

### ~~Verify relabel_test_set.py does not regress true `media` labels~~

**Status:** Done (2026-06-26) — verified, then narrowed `_RELABEL_ELIGIBLE_CATEGORIES` to `{'uncategorized'}` (backlog fix option 1).
**Priority:** P2 (potential silent regression in evaluation accuracy)
**Source:** relabel-extension session, 2026-05-16

**Findings (Dec dataset, `results/ml_data_dec/`, 6027 samples):**
- The flagged triage passes (3–5, gated on `_RELABEL_ELIGIBLE_CATEGORIES`) fire **0** times on Dec, so the eligible-set extension overwrites **0** `media` labels there — the extension itself does not regress media.
- The measured media movement (support 314→211, F1 0.50→0.43, precision 0.36→0.28) comes entirely from the pre-existing, location-grounded passes 1 (`parent_folder == 'Games'`, 20 media→game_assets) and 2 (`Other/` sprite-like, 83), which are the script's intended label-rot correction and are out of scope for this item.
- Controlled comparison: preserving all original `media` labels yields overall acc 0.9096 (vs 0.9074 with relabel) — i.e. the corrective passes trade a sliver of overall accuracy for cleaner game_assets labels, as designed.

**Fix applied:** narrowed `_RELABEL_ELIGIBLE_CATEGORIES` to `{'uncategorized'}` so the triage passes can never overwrite a `media` label on future datasets. Verified a **0-row no-op** on Dec; re-ran eval → **90.74% category accuracy, media F1 42.90%** (baseline held exactly). Updated the module docstring to record why `media` is excluded.

**Affected:**
- `scripts/relabel_test_set.py` (`_RELABEL_ELIGIBLE_CATEGORIES` + docstring)
- `results/ml_data_dec/test_relabeled.json` (regenerated; byte-equivalent labels)

### `media` category acts as a catch-all in classifier output

**Status:** Open (hypothesis — needs confirmation)
**Priority:** P2 (drives most evaluation false positives)
**Source:** model-evaluation session, 2026-05-16
**Context:** On the December test set, the classifier routes `uncategorized → media` (265), `game_assets → media` (213), and `property_management → media` (20). `media` precision is 27.94% while recall is 92.42% — a precision/recall imbalance consistent with `media` being used as a fallback when no other category scores high enough. This is a hypothesis derived from the misclassification table, not a verified code claim.

**Proposed fix:**
1. Audit the priority chain in `src/classifiers/` and `scripts/file_organizer_content_based.py` to confirm whether `media` is the terminal fallback for image/audio/video extensions.
2. If confirmed, require positive evidence (CLIP score above threshold, EXIF camera tags, or screenshot/photo filename pattern) before assigning `media` — otherwise route to `uncategorized` so the classifier under-claims rather than over-claims.

**Affected:**
- `src/classifiers/content_classifier.py`
- `scripts/file_organizer_content_based.py` (priority chain)
- `scripts/shared/constants.py` (`CLIP_ENHANCE_THRESHOLD` / `CLIP_ENHANCE_HIGH_THRESHOLD` may need tuning)
