# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.

## Quick Start

```bash
source venv/bin/activate
organize-files content --source ~/Downloads --dry-run --limit 100
organize-files health                    # Check dependencies
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `organize-files content` | AI-powered organization (CLIP, OCR) |
| `organize-files name` | Filename pattern organization (no AI) |
| `organize-files type` | Extension-based organization |
| `organize-files health` | Check system dependencies |
| `organize-files migrate-ids` | Run database migration |
| `organize-files update-site` | Update dashboard data |
| `organize-files timeline` | Generate timeline visualization data |

## Project Structure

```
├── src/                    # Core library
│   ├── cli.py              # Unified CLI entry point
│   ├── generators.py       # Schema.org metadata generation
│   ├── error_tracking.py   # Sentry integration
│   ├── api/
│   │   ├── schema_org_api.py    # FastAPI JSON-LD REST endpoints
│   │   └── schema_org_models.py # Pydantic request/response models
│   └── storage/
│       ├── graph_store.py       # SQLAlchemy graph with canonical IDs
│       ├── models.py            # ORM models with to_schema_org()
│       ├── schema_org_exporter.py   # Bulk export (JSON, NDJSON, @graph)
│       ├── schema_org_context.py    # JSON-LD @context document generation
│       ├── schema_org_variants.py   # CategoryVariants, PersonVariants, FileVariants
│       └── schema_org_base.py       # Shared base types
├── scripts/
│   ├── shared/                          # Shared utilities
│   │   ├── clip_classification.py       # Unified CLIP+OCR pipeline (classify_with_ocr_fallback, CLIPResult)
│   │   ├── ocr_classifier.py            # OCR fallback logic (classify_by_ocr, apply_ocr_fallback)
│   │   ├── clip_utils.py                # CLIPClassifier singleton (ViT-B-32)
│   │   ├── clip_cache.py                # Embedding cache (.cache/clip_embeddings_v2/)
│   │   ├── file_organizer.py            # FileOrganizer (mode=in-place|folder, drives both renamers)
│   │   └── ...                          # file_ops, filename_utils, constants, status, confidence_gate
│   ├── file_organizer_content_based.py  # Main AI organizer
│   ├── image_content_renamer.py         # CLIP-based image renaming via FileOrganizer (mode=in-place default)
│   ├── screenshot_renamer.py            # CLIP screenshot renamer via FileOrganizer (mode=folder default)
│   └── image_content_analyzer.py        # Image content analysis
├── tests/
│   ├── unit/               # Unit tests (pytest)
│   ├── integration/        # Integration tests (schema.org export pipeline)
│   ├── performance/        # Benchmark suite (pytest-benchmark)
│   └── e2e/                # E2E tests (Playwright + OpenTelemetry)
├── _site/                  # Dashboard UI
└── results/                # Reports & database
```

**Note on `scripts/shared/`:** Scripts must be run from the project root (or with `scripts/` on `sys.path`) so that `from shared.x import y` resolves correctly. The `organize-files` CLI entry point handles this automatically.

## Classification Priority

1. **Organization Detection** - client, vendor, invoice, company names
2. **Person Detection** - resume, contact, signatures (OCR-enhanced)
3. **Legal/Contract** - contracts, agreements, terms
4. **E-commerce/Shopping** - product listings, carts
5. **Software UI** - app interfaces, dashboards
6. **Game Assets** - 200+ patterns, sprites, textures, audio
7. **Filepath Matching** - directory structure patterns
8. **Content Analysis** - OCR text and CLIP vision
9. **MIME Type Fallback** - file extension

## Output Folders

```
~/Documents/
├── Organization/{CompanyName}/    # Vendor/partner files
├── Person/{PersonName}/           # Person-related files
├── GameAssets/                    # Sprites, textures, models
├── Financial/                     # Invoices, receipts
├── Technical/                     # Code, configs
└── Media/                         # Photos, videos, audio
```

## Environment

| Variable | Description |
|----------|-------------|
| `FILE_SYSTEM_SENTRY_DSN` | Sentry error tracking (Doppler) |
| `FILE_ORGANIZE_MODE` | `in-place` (default for image renamer) or `folder` (default for screenshot renamer) |
| `--sentry-dsn` | CLI override |

## Dependencies

```bash
pip install -e ".[all]" && brew install tesseract poppler
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| HEIC fails | `pip install pillow-heif` |
| No OCR | `pip install python-doctr[torch]` |
| No AI | `pip install torch transformers` |

## Schema.org Reference

See [`docs/SCHEMA_ORG_ARCHITECTURE.md`](docs/SCHEMA_ORG_ARCHITECTURE.md) for type mappings, IRI generation, JSON-LD context, per-entity `to_schema_org()` implementations, and relationship rules.

## REST API

FastAPI app at `src/api/schema_org_api.py`. Key endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/{entity}/{id}/schema-org` | Single entity as JSON-LD |
| `GET /api/{entity}/schema-org/bulk` | Filtered list as `{"@context":…,"@graph":[…]}` |
| `GET /api/schema-org/export` | Full `@graph` document, filterable by entity type |
| `GET /api/schema-org/graph` | Full graph, all entity types |
| `GET /schema/context` | Standalone JSON-LD `@context` document |

Entity types: `files`, `categories`, `companies`, `people`, `locations`.

## Gotchas

| Issue | Detail |
|-------|--------|
| Large images silently skipped | Pillow rejects images >178M pixels (decompression-bomb guard); affects oversized PNGs like maps/renders |
| CLIP embedding cache | Lives at `.cache/clip_embeddings_v2/` (fp32 `.npy` per image); safe to `rm -rf` to reset |
| `scripts/shared/` import path | Scripts must run from project root so `from shared.x import y` resolves; `organize-files` CLI handles this automatically |
| FileOrganizer modes | Both `image_content_renamer.py` and `screenshot_renamer.py` support `--mode in-place\|folder` and `FILE_ORGANIZE_MODE` env var; defaults differ by script |
| Unified CLIP+OCR API | `classify_with_ocr_fallback()` in `scripts/shared/clip_classification.py` is the shared entry point; returns `CLIPResult(category, confidence, all_scores)`; both renamer tools call it |

## Testing

```bash
pytest tests/unit/           # 753 unit tests
pytest tests/integration/    # schema.org export pipeline
pytest tests/performance/ --benchmark-only -m "not slow"   # benchmarks (skip 10k)
pytest tests/e2e/            # Playwright E2E
```

---
**Python:** 3.14 | **Version:** 2.0.0 | **Files:** 265,000+ processed
