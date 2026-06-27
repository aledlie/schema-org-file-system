# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-03-30.

## Completed

### ~~Batch CLIP inference cache layer (Phases 1–4)~~

**Status:** Done (PRs #4–#7, merged 2026-03-29)
- Replaced joblib cache with manual pickle + probe-without-execute
- Added `get_cached_embeddings_batch()` API
- Routed `ContentBasedFileOrganizer` and `ImageContentAnalyzer` through cache
- Added CLIP pre-warm in `BatchProcessor`

### ~~Replace EasyOCR + pytesseract with docTR~~

**Status:** Done (committed 2026-03-29)
- Unified two parallel OCR engines into single docTR backend
- `scripts/shared/ocr_utils.py` rewritten: `fast_base` detection, `straighten_pages`, `detect_language`, `detect_orientation`, `resolve_blocks`
- Added `OCRResult` dataclass with confidence/language/orientation metadata
- `extract_ocr_with_confidence()` and `extract_ocr_pdf_with_confidence()` for rich results
- `src/analyzers/text_extractor.py`: added `ExtractionResult` dataclass and `extract()` method
- `src/storage/models.py`: added `ocr_confidence` and `detected_language` columns
- Removed pytesseract and system tesseract dependency

### ~~Migrate CLIP backend to `open-clip-torch`~~

**Status:** Done (2026-03-29)
- Replaced `transformers.CLIPModel` + `sentence-transformers` with single `open-clip-torch` backend
- Unified to `CLIPClassifier.get_instance()` singleton across all consumers
- Native fp16 support via `model.to(torch.float16)`

### ~~Wire OCR confidence into classification pipeline~~

**Status:** Done (2026-03-30)
- `content_organizer.py`: skips keyword classification when OCR confidence < 0.3
- `file_organizer_content_based.py`: gates ID document detection on confidence >= 0.3
- `content_classifier.py`: skips English keyword matching for non-English documents
- `file_organizer_content_based.py`: threads `ocr_confidence` and `detected_language` to `_persist_to_graph_store()`

## Open Items

### ~~KIE predictor for structured document extraction~~

**Status:** Done (2026-03-30)
**Depends on:** ~~docTR migration~~ (done)

- `scripts/shared/kie_utils.py`: `KIEField`/`KIEResult` dataclasses, `extract_kie_fields()`, `extract_kie_fields_pdf()` with graceful fallback when weights absent
- `scripts/shared/kie_schema_mapping.py`: 10 field classes mapped to Schema.org Invoice properties (`provider`, `totalPaymentDue`, `confirmationNumber`, `paymentDueDate`)
- `src/classifiers/content_classifier.py`: `classify_with_kie()` short-circuits to `financial/invoices` when vendor + amount/date detected at >= 0.5 confidence
- `scripts/file_organizer_content_based.py`: KIE extraction at Priority 3.5 (gated on OCR confidence >= 0.3), KIE classification at Priority 6, results merged into `schema_data` and stored in `kie_fields` column
- `src/storage/models.py`: `kie_fields` JSON column on File model
- `scripts/collect_kie_training_data.py`: scan Financial/ docs, export OCR word boxes for manual labeling
- `scripts/train_kie_model.py`: fine-tune KIE classification head (frozen backbones), save weights to `models/kie_invoice_v1.pt`
- 19 unit tests in `tests/unit/test_kie_utils.py`

### Improve OCR preprocessing for dark-background screenshots

**Status:** Open
**Depends on:** docTR migration (done)
**Context:** Priority 4.5 screenshot sub-classification (added 2026-03-31) correctly routes screenshots to OCR/CLIP, but ~87 raw `Screenshot*` files in `~/Documents/Media/Photos/Screenshots/` remain unclassified because docTR produces no usable text on dark-background terminal/IDE/dashboard screenshots and CLIP scores are uniformly ~5% (below the 15% threshold).

- Add image inversion preprocessing in `scripts/shared/ocr_utils.py` for dark-background images (detect mean luminance < threshold, invert before OCR)
- Consider adaptive contrast enhancement (CLAHE) as a second pass when initial OCR yields < 30 chars
- Evaluate lowering `CLIP_ENHANCE_THRESHOLD` for screenshot-specific classification (currently 0.15, screenshots score ~0.05)
- Add `_SCREENSHOT_KEYWORDS` entries for IDE/code patterns (`import`, `function`, `class`, `def`, `const`) and browser patterns (`http`, `www`, `.com`, `search`)

### ~~Game-sprite keyword gate may false-positive on short substrings~~

**Status:** Done (2026-04-19, fix(organizer) commit)
**Context:** `src/organizers/content_organizer.py:1206` and `scripts/file_organizer_content_based.py:2661` gate the broad snake_case `^[a-z]+(_[a-z0-9]+)+$` "Game asset (named)" rule on `any(kw in stem for kw in self.game_sprite_keywords)` (added 2026-04-19 to stop non-game snake_case files like `flipside_swolmates_map.png` being misrouted to `GameAssets/Sprites/`).

`self.game_sprite_keywords` contains short tokens (`arm`, `leg`, `ring`, `ore`, `icon`, `ui`, `up`, `over`, `main`, `bar`, `body`, `eye`, `hand`) that are substrings of common non-game words. Examples of likely false-positives:

- `legal_doc.png` → matches `leg`
- `earrings_vendor.png` → matches `ring` / `earring`
- `main_menu_mockup.png` → matches `main` / `menu`
- `iconography_notes.png` → matches `icon`
- `barn_photo.png` → matches `bar`

**Proposed fix:** switch `kw in stem` to word-boundary matching against `stem.split('_')` tokens, i.e. `any(kw in tokens for kw in self.game_sprite_keywords)` where `tokens = stem.split('_')`. Aligns intent (keyword is a filename component) with implementation.

**Affected:**
- `src/organizers/content_organizer.py:1206-1211`
- `scripts/file_organizer_content_based.py:2661-2671`

### Filename-pattern classification duplicated across two organizers

**Status:** Open
**Context:** `src/organizers/content_organizer.py` and `scripts/file_organizer_content_based.py` both carry near-identical filename-pattern rule sets (including the `Game asset (named)` regex + keyword-gate added 2026-04-19). Any rule change must be applied in both places or classification drifts between entry points.

**Proposed fix:** extract the filename-pattern rules into a shared module (e.g. `scripts/shared/filename_classifier.py` or `src/classifiers/filename_patterns.py`) returning `(category, subcategory, organization, schema_data)`. Both organizers import and call one function.

**Affected:**
- `src/organizers/content_organizer.py` (classify_file filename-pattern block, ~lines 1100-1250)
- `scripts/file_organizer_content_based.py` (same logic, ~lines 2600-2780)

### ~~ImageContentRenamer status strings → Enum~~

**Status:** Done (2026-04-19)
**Context:** `rename_file()` returns a result dict with stringly-typed `status` values (`'pending'`, `'skipped'`, `'renamed'`, `'would_rename'`, `'no_content'`, `'low_confidence'`, `'error'`). `process_directory()` branches on these strings with a long if/elif chain. No single source of truth; typos would silently fall through.

**Proposed fix:** introduce `RenameStatus(Enum)`; replace string literals and collapse the print branches in `process_directory()` into a status→formatter lookup dict.

**Affected:**
- `scripts/image_content_renamer.py:306-425`

### ~~ImageContentRenamer `_get_date_string` duplicates `ImageMetadataParser.extract_datetime`~~

**Status:** Done (2026-04-19)
**Context:** `ImageContentRenamer._get_date_string()` (scripts/image_content_renamer.py:260) performs EXIF + mtime extraction that duplicates `src/analyzers/image_metadata.py:ImageMetadataParser.extract_datetime()` (lines 92-108). The `ImageMetadataParser` version handles more EXIF tag names and has stronger error handling.

**Proposed fix:** delete `_get_date_string` and call `ImageMetadataParser.extract_datetime()`; format the returned datetime as `YYYYMMDD` at the callsite in `generate_filename()`.

**Affected:**
- `scripts/image_content_renamer.py:27-28` (delete `_EXIF_TAG_*` constants)
- `scripts/image_content_renamer.py:260-280` (delete `_get_date_string`)

### ~~ImageContentRenamer `should_rename` patterns duplicate `image_renamer_metadata.is_generic_filename`~~

**Status:** Done (2026-04-19) — merged patterns into `scripts/shared/filename_utils.py`
**Context:** `scripts/image_content_renamer.py:282` and `scripts/image_renamer_metadata.py:69-77` both maintain generic-filename regex lists. The `image_renamer_metadata` version has a more complete pattern set (MD5 hashes, Unix timestamps, UUIDs) that's missing here.

**Proposed fix:** move the merged pattern list into `scripts/shared/filename_utils.py` (new module) as `GENERIC_FILENAME_PATTERNS` plus `is_generic_filename(name)` helper. Both renamers import and call it.

**Affected:**
- `scripts/image_content_renamer.py:282-304`
- `scripts/image_renamer_metadata.py:69-77`

### ~~ImageContentRenamer TOCTOU on collision resolution~~

**Status:** Done (2026-04-19)
**Context:** `rename_file()` checks `new_path.exists()` before `file_path.rename(new_path)` (lines 356/364). A concurrent process creating `new_path` between the check and the rename would cause a silent overwrite on POSIX or a `FileExistsError` depending on platform.

**Proposed fix:** drop the pre-check and wrap `rename()` in try/except `FileExistsError`; on failure, call `resolve_collision()` and retry once.

**Affected:**
- `scripts/image_content_renamer.py:354-370`

### ~~Expand GAME_SPRITE_KEYWORDS for sprite anatomy/UI vocabulary~~

**Status:** Done (2026-05-16)
**Priority:** P1 (highest yield — 629 game_assets → media misclassifications)
**Source:** model-evaluation session, 2026-05-16
**Context:** After fixing underscore-stripped keywords, plural matching, and threshold ≥ 0.3 + parent_folder=Games override, evaluation accuracy improved from 74.57% to 83.87%. This is the highest-yield improvement identified: 629 game_asset files are still being misclassified as media (e.g., `c_rug_3.png`, `feet_brown_2.png`, `glow_01_3.png`, `mee_2_1.png`) due to missing sprite anatomy/game-UI vocabulary in `GAME_SPRITE_KEYWORDS`.

**Proposed fix:** add body-part and game-UI terms to `scripts/shared/constants.py` `GAME_SPRITE_KEYWORDS`: `rug`, `glow`, `mee`, `gelf`, `salamander`, `blob`, `bubble`, `lever`, `spine`, `mandible`, `pupils`. Potential accuracy gain: 84%+.

**Caveat:** This touches `scripts/shared/constants.py` which is used by production code (`file_organizer_content_based.py` and `image_content_renamer.py`), not just the evaluator simulator. Requires careful regression review against production classification patterns.

**Affected:**
- `scripts/shared/constants.py` (GAME_SPRITE_KEYWORDS)
- `scripts/file_organizer_content_based.py` (imports GAME_SPRITE_KEYWORDS)
- `scripts/image_content_renamer.py` (imports GAME_SPRITE_KEYWORDS)
- `scripts/evaluate_model.py` (test harness)

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

### Verify relabel_test_set.py does not regress true `media` labels

**Status:** Open
**Priority:** P2 (potential silent regression in evaluation accuracy)
**Source:** relabel-extension session, 2026-05-16
**Context:** `scripts/relabel_test_set.py` was extended (passes 3–5) to relabel files in triage locations (`Uncategorized`, `Desktop`, `Downloads`). `_RELABEL_ELIGIBLE_CATEGORIES` now includes `'media'`, which means a sample currently labeled `media` can be overwritten to `game_assets`, `media/screenshot`, `financial`, `legal`, or `personal`. On the December dataset (`results/ml_data_dec/`) where many `media` labels are legitimate, this could degrade media-class recall.

**Proposed fix:**
1. Re-run `organize-files evaluate --test-data results/ml_data_dec/test_relabeled.json` with the extended script and diff against the pre-extension baseline (90.74% category accuracy, F1 42.9% for `media`).
2. If `media` recall drops materially, narrow `_RELABEL_ELIGIBLE_CATEGORIES` to `{'uncategorized'}` only, or require an additional triage-location signal before overwriting a `media` label.

**Affected:**
- `scripts/relabel_test_set.py:97` (`_RELABEL_ELIGIBLE_CATEGORIES` definition)
- `scripts/relabel_test_set.py:130-148` (triage pass guard logic)

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

### Collapse private `ImageContentAnalyzer` into the shared CLIP+OCR pipeline

**Status:** Open
**Priority:** P1 (removes a parallel CLIP entry point; ~180 LOC)
**Source:** simplification audit, 2026-06-26
**Depends on:** none (pairs with "Compute CLIP embedding once per image" below)

**Context:** `scripts/file_organizer_content_based.py:1145-1320` defines a private `ImageContentAnalyzer` with its own CLIP zero-shot path (`classify_image_content`), its own 11-prompt category list (`_CLASSIFY_CATEGORIES`, lines 1208-1220), its own per-file result cache (`_clip_result_cache`, lines 1159/1236), and OpenCV face detection (`detect_people`, `is_home_interior_no_people`, `has_people_in_photo`). This duplicates `scripts/shared/clip_classification.py:classify_with_ocr_fallback`, which already wraps the `CLIPClassifier` singleton (`scripts/shared/clip_utils.py`) and the embedding cache. Only three methods are consumed — by `detect_file_category` tier 5 (photo composition, ~lines 3632/3647) and the interior check. Net result: two parallel CLIP code paths, two category lists, two per-file caches.

**Proposed fix:**
1. Move the 11 interior/people prompts (`_CLASSIFY_CATEGORIES`) into a single home — either a `CLIP_INTERIOR_CATEGORIES` constant in `scripts/shared/constants.py` or an `INTERIOR_DETECTION_PROFILE` in `scripts/rename_images.py`. (Subsumes audit item "unify category sets via profile".)
2. Replace `classify_image_content` calls with `classify_with_ocr_fallback` (or a thin `_clip_scores(path, categories)` helper over the singleton) so all CLIP scoring goes through one path.
3. Keep face detection (`detect_people`) — it is OpenCV, not CLIP. Extract it to `scripts/shared/vision_utils.py` shared with the duplicate cascade loader in `src/analyzers/image_analyzer.py:82`.
4. Drop `_clip_result_cache` (line 1159) and `_clip_enhance_cache` (line 3379); rely on the embedding cache (`.cache/clip_embeddings_v2/`) + singleton. (Subsumes audit item "consolidate per-file CLIP caches".)
5. Delete `ImageContentAnalyzer` once callers are migrated.

**Affected:**
- `scripts/file_organizer_content_based.py:1145-1320` (class), `1208-1220` (`_CLASSIFY_CATEGORIES`), `1159`/`3379` (caches), tiers 5/9 callers
- `scripts/shared/clip_classification.py` (`classify_with_ocr_fallback`)
- `scripts/shared/constants.py` or `scripts/rename_images.py` (new interior-category home)
- new `scripts/shared/vision_utils.py` (shared face-cascade loader)

**Validation (GATED):** the people thresholds differ by method — `0.15` in `has_people_in_photo` vs `0.2` in `is_home_interior_no_people`. Preserve each exactly during the move; do NOT harmonize without a dedicated eval run. After refactor run `pytest tests/unit/` and `organize-files evaluate --test-data results/ml_data_dec/test_relabeled.json`; confirm category accuracy holds at the 90.74% baseline before merging.

### Compute CLIP embedding once per image, reuse across rename + classification tiers

**Status:** Open
**Priority:** P1 (1–2 redundant model passes per image)
**Source:** simplification audit, 2026-06-26
**Depends on:** pairs with "Collapse private `ImageContentAnalyzer`" (shared cache)

**Context:** Each image is CLIP-scored up to three times with different prompt sets, re-encoding the same pixels each time:
1. Rename pre-step — `_maybe_rename_image` → `ImageAnalyzer.analyze_image` → `classify_with_ocr_fallback` (`scripts/rename_images.py:313`) with `profile.categories`.
2. `detect_file_category` tiers 4.5/6 — `enhance_weak_image_classification` → `_run_clip_signal` (`scripts/file_organizer_content_based.py:~3315-3344`) with `CLIP_CATEGORY_PROMPTS`.
3. Tier 5 — `ImageContentAnalyzer.classify_image_content` with `_CLASSIFY_CATEGORIES`.
The image embedding is identical across all three (only the text prompts differ), but the rename-phase result is discarded rather than threaded forward.

**Proposed fix:**
1. Ensure every call site routes through the embedding-level cache (`scripts/shared/clip_cache.py:get_cached_embedding`, per-image fp32 `.npy`) so the image is encoded once and only text-prompt similarity is recomputed per prompt set.
2. Alternatively compute the image embedding once in `organize_file` and pass it down to `detect_file_category` and the rename step, scoring all prompt sets against the cached embedding.
3. Land after / alongside the cache consolidation from the `ImageContentAnalyzer` collapse so there is a single cache to populate.

**Affected:**
- `scripts/file_organizer_content_based.py` (`_maybe_rename_image` ~4036, `_run_clip_signal` ~3315, `enhance_weak_image_classification` ~3344, tier 5 ~3632)
- `scripts/rename_images.py:302-350` (`ImageAnalyzer.analyze_image`)
- `scripts/shared/clip_cache.py`, `scripts/shared/clip_utils.py` (`classify_raw`)

**Validation (GATED):** scores and routing must be byte-identical. Run `pytest tests/unit/` and the December eval; additionally confirm `.cache/clip_embeddings_v2/` hit-rate rises and per-image CLIP call count drops (temporary counter or cost-tracker output).

### ~~Image-rename pre-step is dead — `ImageContentRenamer` shim missing `.analyzer` (regression)~~

**Status:** Done (2026-06-26) — replaced shim with direct `ImageAnalyzer(PHOTO_PROFILE)` (`self.rename_analyzer`), used `IMAGE_EXTENSIONS_WIDE` for the extension gate, deleted the shim. Verified: analyzer runs end-to-end (no `AttributeError`); 770 unit tests pass; December eval holds at 90.74% category accuracy.
**Priority:** P1 (silently disables content-based image renaming)
**Source:** simplification audit, 2026-06-26
**Context:** The in-flight `rename_images.py` consolidation left `ImageContentRenamer` (`scripts/rename_images.py:413-438`) as a compat shim that exposes `IMAGE_EXTENSIONS` and `process_directory` but **not** `.analyzer` — only the real `ImageRenamer` class has `self.analyzer` (line 371). `file_organizer_content_based.py` constructs the shim (`self.image_renamer = ImageContentRenamer(dry_run=False)`, line 1362) then accesses `self.image_renamer.analyzer.analyze_image(...)` (line 4052) and `...analyzer.content_classifier` (line 3596). Accessing `.analyzer` raises `AttributeError`, swallowed by the `try/except` in `organize_file` (~line 4101). Net effect: **every generic-named image (`IMG_*`, `Screenshot*`, …) skips the rename pre-step**, so filename-pattern classification never sees the descriptive name. Confirmed at runtime: `ImageContentRenamer(dry_run=False).analyzer` → `AttributeError: 'ImageContentRenamer' object has no attribute 'analyzer'`.

**Proposed fix (audit item "remove `ImageContentRenamer` shim", now revealed as a bug fix):**
1. In `file_organizer_content_based.py`: import `ImageAnalyzer, PHOTO_PROFILE, IMAGE_EXTENSIONS_WIDE` from `rename_images`; replace `self.image_renamer = ImageContentRenamer(dry_run=False)` (line 1362) with `self.image_analyzer = ImageAnalyzer(PHOTO_PROFILE)`.
2. Update line 4049 `self.image_renamer.IMAGE_EXTENSIONS` → `IMAGE_EXTENSIONS_WIDE`; line 4052 → `self.image_analyzer.analyze_image(file_path)`; line 3596 → `self.image_analyzer.content_classifier`.
3. Delete the `ImageContentRenamer` shim (only callers are `file_organizer` + a docstring mention in `filename_utils.py:5`).

**Affected:**
- `scripts/rename_images.py:413-438` (shim to delete)
- `scripts/file_organizer_content_based.py:94, 1362, 3596, 4049, 4052`

**Validation (GATED — re-activates a behavior-changing stage):** restoring renaming feeds the filename-pattern tiers and can shift classifications. After the fix run `pytest tests/unit/` and `organize-files content --dry-run --limit 200` on a sample to confirm renames fire and routing is sane; run the December eval before merging.
