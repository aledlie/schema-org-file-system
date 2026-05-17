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
