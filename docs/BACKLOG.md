# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-03-29.

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

## Open Items

### ~~Migrate CLIP backend to `open-clip-torch`~~

**Status:** Done (2026-03-29)
**Priority:** Medium
**Effort:** 3–4 hrs
**Depends on:** ~~Batch CLIP inference cache layer~~ (done)

Replace the current dual CLIP implementations (`transformers.CLIPModel` in `scripts/file_organizer_content_based.py` + `src/analyzers/image_analyzer.py`, and `sentence-transformers` in `scripts/shared/clip_utils.py`) with a single `open-clip-torch` backend.

**Motivation:**
- Eliminates two separate model instances loading the same weights
- Direct tensor API (`model.encode_image(pixel_values)`) removes DataLoader overhead present in `sentence-transformers`, improving small-to-medium batch latency
- Native fp16 support via `model.to(torch.float16)` — resolves the fp16 open item in `docs/deep-learning-analysis-03-27-2026.md` simultaneously
- Opens path to larger model variants (ViT-L/14, ViT-H/14) without code changes

**Scope:**
- Replace `SentenceTransformer('clip-ViT-B-32')` in `scripts/shared/clip_utils.py:CLIPClassifier` with `open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')`
- Replace `CLIPModel.from_pretrained` + `CLIPProcessor.from_pretrained` in `scripts/file_organizer_content_based.py` and `src/analyzers/image_analyzer.py` with the same `open_clip` instance (via `CLIPClassifier.get_instance()`)
- Update `_run_batch()` to use `model.encode_image()` + `model.encode_text()` directly
- Add `open-clip-torch` to `pyproject.toml`; remove `sentence-transformers` if no other consumers remain
- Update `scripts/shared/constants.py:CLIP_BATCH_SIZE` if optimal batch size changes

**Out of scope:** model variant upgrade (ViT-B-32 → ViT-L/14) — treat as a separate backlog item.

### ~~Wire OCR confidence into classification pipeline~~

**Status:** Done (2026-03-30)
**Priority:** Low
**Effort:** 1–2 hrs
**Depends on:** ~~docTR migration~~ (done)

The `OCRResult.confidence` and `detected_language` fields are now stored in the database but not yet used for decision-making in the classification pipeline.

**Scope:**
- `content_organizer.py`: skip keyword classification when OCR confidence < 0.3 (low-quality text causes misclassification)
- `file_organizer_content_based.py`: use confidence to gate ID document detection (line 3278) — low-confidence OCR on a photo shouldn't trigger passport detection
- `content_classifier.py`: route non-English documents (via `detected_language`) to a language-specific folder or skip English keyword matching
- `file_processor.py`: pass `ocr_confidence` and `detected_language` from `ExtractionResult` through to `_persist_to_graph_store()`

### KIE predictor for structured document extraction

**Status:** Open
**Priority:** Low
**Effort:** 4–6 hrs (requires training data)
**Depends on:** ~~docTR migration~~ (done)

docTR's `kie_predictor()` supports multi-class detection for labeled field extraction (dates, amounts, addresses) on invoices, receipts, and contracts. No pretrained weights ship — requires fine-tuning on domain data.

**Scope:**
- Collect labeled samples from organized Financial/ and Legal/ folders
- Fine-tune KIE detection head on invoice/receipt fields
- Replace regex-based entity extraction in `content_classifier.py` with KIE predictions for structured documents
- Store extracted fields (vendor, amount, date) as Schema.org properties
