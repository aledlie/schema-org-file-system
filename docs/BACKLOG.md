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

### Game-sprite keyword gate may false-positive on short substrings

**Status:** Open
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
