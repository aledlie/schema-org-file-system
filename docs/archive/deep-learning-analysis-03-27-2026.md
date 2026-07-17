# Schema.org File System — ML/AI Audit

**Date:** 2026-03-27 | **Last Updated:** 2026-03-29
**Version:** 2.0.0 (was 1.3.0 at audit time)
**Scope:** 191 files | ~305K LOC

> **Historical snapshot (2026-03).** The stack table below is as of the audit date. Since then, CLIP inference moved to `open-clip-torch` (not `sentence-transformers`) and the CLIP embedding cache is raw `.npy` files under `.cache/clip_embeddings_v2/` (`joblib` removed). Read the Status columns as historical, not current.

---

## ML/AI Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| Vision classification | CLIP via `sentence-transformers` (`cb5ef25`) | Conditional (optional dep) |
| OCR | EasyOCR (`43c1f3a`; replaced pytesseract) | Core |
| PDF → image | `pdf2image` | Optional |
| Device detection | MPS → CUDA → CPU auto-select | Solid |
| Embedding cache | `joblib.Memory` disk cache (`c4c106b`) | Built-in |
| Cost tracking | `pandas` groupby/agg (`728aa39`; replaced custom loops) | Built-in |
| Preprocessing | `sklearn` split/vocab/encoder (`e151813`; replaced custom) | Built-in |

---

## Top Issues

### High Priority

- ~~**No model caching**~~ — **Done** (`c4c106b`, `8975f3e`): `joblib.Memory` disk cache added; CLIP embeddings cached by content hash.
- **Single-image inference** — no batch processing; ~3–5 sec per image with no GPU parallelization. Estimated 4–8x gain with batching. Still open.
- ~~**No lock file**~~ — **Done** (`cedfe06`): `pip-compile` lock file added.

### Medium Priority

- ~~**God class**~~ — **Done** (`49566dd`–`6685adb`): all major classes extracted into `src/classifiers/`, `src/analyzers/`, `src/organizers/`, `src/pipeline/`, `src/utils/`. God-file retained as thin entry point.
- ~~**N+1 queries**~~ — **Done**: `joinedload`/`selectinload` added on graph relationships.
- **No fp16/int8 quantization** — CLIP runs full fp32 (~2 GB RAM). Half-precision would cut that in half with ~2x speedup.
- **No retry on OCR failure** — failed extractions are silently skipped.

### Low Priority

- No CI/CD (only manual GitHub Pages deploy)
- ~~No benchmark suite~~ — **Done** (`7326fa3`): `tests/performance/test_export_benchmark.py` covers SchemaOrgExporter at 100/1k/10k entities; extended in `2.0.0` with per-entity serialization and relationship benchmarks (`S10`).
- ~~CLIP embeddings not cached by content hash~~ — **Done** (`c4c106b`): `joblib.Memory` disk cache.

---

## What's Good

- Graceful degradation on all optional deps (AI, docs, monitoring)
- ~85% type annotation coverage, mypy configured
- Graph storage schema is solid — confidence scores on all ML predictions, SHA-256 dedup IDs
- 19 test files (unit + integration + 6 Playwright E2E specs; +7 from refactor batch)
- Sentry error tracking with decorator/context manager patterns
- Cost-per-feature ROI tracking built into the pipeline

---

## Recommended Next Steps

| Priority | Task | Effort | Status |
|----------|------|--------|--------|
| 1 | Add `pip-compile` lock file | 1–2 hrs | Done (`cedfe06`) |
| 2 | CLIP singleton/module-level cache | 2–4 hrs | Done (`8975f3e`) |
| 3 | Batch CLIP inference (8–32 images) | 6–8 hrs | Open |
| 4 | `joinedload` on graph queries | 2–3 hrs | Done |
| 5 | Split `file_organizer_content_based.py` per refactor plan | 1–2 days | Done (`49566dd`–`6685adb`) |
| 6 | fp16 quantization for CLIP | 1–2 hrs | Open |

---

## Post-Audit Commits (2026-03-27 → 2026-03-28)

| Commit | Description |
|--------|-------------|
| `cb5ef25` | `sentence-transformers` replaces bare `transformers` for CLIP inference |
| `43c1f3a` | `easyocr` replaces `pytesseract` as OCR backend |
| `8975f3e` | `joblib.Memory` disk cache for CLIP embeddings (merge) |
| `c4c106b` | `joblib.Memory` disk cache feat implementation |
| `e151813` | `sklearn` replaces custom split/vocab/encoder |
| `728aa39` | `pandas` groupby/agg replaces manual cost aggregation loops |
| `235fb18` | Replace EXIF magic numbers with named constants in `image_content_renamer.py` |
| `5c69a40` | Fix `Image.open()` file handle leak in `image_content_renamer.py` |
| `0eaad81` | Update typing imports to modern syntax (`str \| None`) |
| `a63eac7` | Add unit tests for `scripts/shared/` module (141 lines) |
| `575d2d8` | Add `SchemaOrgSerializable` mixin — JSON-LD interface for all models |
| `95a98a9` | Wire `SchemaOrgSerializable` into all storage models |
| `8060b7f` | Add `SchemaOrgExporter`, variants, full test suite |
| `7326fa3` | Add export pipeline benchmark suite (`tests/performance/`) |
| `7c14484` | Wire `SchemaOrgExporter` into API; add JSON-LD context + validation |
| `d8804ef` | Wrap bulk endpoints in JSON-LD `@context`/`@graph`; annotate schema.org property URLs |
| `43c2d32` | Consolidate alignment docs into `SCHEMA_ORG_ARCHITECTURE.md` |

**Schema.org integration** (S1–S10) fully landed in v2.0.0: exporter, variants, context generation, REST API bulk endpoints, validation tests, and benchmarks.

## Post-Audit Commits (2026-03-29)

| Commit | Description |
|--------|-------------|
| `49566dd` | Extract `TextExtractor` → `src/analyzers/text_extractor.py` |
| `4c21368` | Extract `ContentClassifier` → `src/classifiers/` |
| `ff36546` | Extract `ImageMetadataParser`, `ImageContentAnalyzer` → `src/analyzers/` |
| `bfc5a7f` | Extract `FileProcessor`, `BatchProcessor` → `src/pipeline/` |
| `31bf8ab` | Extract `CostTracker`, `FileProcessingErrorTracker` → `src/utils/tracking.py` |
| `026f584` | Fix: add genius-bar Apple pattern; fix game-asset uppercase guard in organizer |
| `6685adb` | Extract `ContentOrganizer`, `BaseOrganizer` → `src/organizers/` (merge PR #3) |
