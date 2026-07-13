# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.

## Quick Start

```bash
# First-time setup
python3.13 -m venv venv && source venv/bin/activate
pip install -e ".[all]" && brew install tesseract poppler

# Daily use
source venv/bin/activate
organize-files content --source ~/Downloads --dry-run --limit 100
organize-files health                    # Should report 9/9 features
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `organize-files content` | AI-powered organization (CLIP, OCR) |
| `organize-files name` | Filename pattern organization (no AI) |
| `organize-files type` | Extension-based organization |
| `organize-files health` | Check system dependencies |
| `organize-files migrate-ids` | Run database migration |
| `organize-files migrate-person` | Migrate `Person/` files → `Personal/{subcat}/` (dry-run default; `--apply`, `--rollback`) |
| `organize-files person-view` | Regenerate `Person/{Name}/` symlink view from graph edges (`--apply`; `--prune-missing` drops dead-path edges first) |
| `organize-files index-people` | Attach `person→file` graph edges for migrated files, no moves (`--apply`; `--prune-missing` drops dead-path edges after) |
| `organize-files prune-person` | Delete people + their `file→person` edges from the graph, no file moves (dry-run default; `--apply` backs up the DB first) |
| `organize-files update-site` | Update dashboard data |
| `organize-files timeline` | Generate timeline visualization data |
| `organize-files preprocess` | ML data preprocessing (`--input`, `--output`) |
| `organize-files evaluate` | Run evaluation metrics (`--test-data`, `--model`, `--classifier {baseline,content}`) |

## Development Commands

```bash
# Start REST API (FastAPI)
uvicorn src.api.schema_org_api:app --reload

# Lint, format, typecheck
black src/ scripts/           # format
flake8 src/ scripts/          # lint
mypy src/ scripts/            # type check
```

## Project Structure

```
├── src/                    # Core library
│   ├── cli.py              # Unified CLI entry point
│   ├── generators.py       # Schema.org metadata generation
│   ├── error_tracking.py   # Sentry integration
│   ├── classifiers/        # content_classifier + entity_detector (company/person extraction)
│   ├── organizers/         # File organizers (base, content, name) + category_config/mime_classifier
│   ├── pipeline/           # Batch processing pipeline (batch_processor, file_processor)
│   ├── analyzers/          # Image/content analyzers
│   ├── utils/              # Shared utilities
│   ├── api/
│   │   ├── schema_org_api.py    # FastAPI JSON-LD REST endpoints
│   │   └── schema_org_models.py # Pydantic request/response models
│   └── storage/
│       ├── graph_store.py       # SQLAlchemy graph with canonical IDs
│       ├── models.py            # ORM models with to_schema_org()
│       ├── schema_org_exporter.py   # Bulk export (JSON, NDJSON, @graph)
│       ├── schema_org_context.py    # JSON-LD @context document generation
│       └── schema_org_base.py       # Shared base types
├── scripts/
│   ├── shared/                          # Shared utilities
│   │   ├── clip_classification.py       # Unified CLIP+OCR pipeline (classify_with_ocr_fallback, CLIPResult)
│   │   ├── ocr_classifier.py            # OCR fallback logic (classify_by_ocr, apply_ocr_fallback)
│   │   ├── clip_utils.py                # CLIPClassifier singleton (ViT-B-32)
│   │   ├── clip_cache.py                # Embedding cache (.cache/clip_embeddings_v2/)
│   │   ├── file_organizer.py            # FileOrganizer (mode=in-place|folder, drives both renamers)
│   │   └── ...                          # file_ops, filename_utils, constants, status, confidence_gate
│   ├── file_organizer_content_based.py  # Main AI organizer (thin CLI wrapper over src/{classifiers,analyzers,organizers,pipeline})
│   ├── rename_images.py                 # Unified CLIP renamer; --profile {photo,screenshot} selects vocab/mode
│   ├── image_content_analyzer.py        # Image content analysis
│   ├── redact_pii.py                    # Rasterize + OCR-redact PII from docs before adding to VCS
│   └── relabel_test_set.py              # Re-label evaluation test set against current classifier
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
2. **Personal Documents** - resume/CV/vCard (`contacts`), employment, identification, certificates (OCR-enhanced). Person attribution is a graph relationship (`GraphStore.add_file_to_person`), not a filing category — see `docs/changelog/2.1.0/PERSON_TAXONOMY_OPTION_C_PLAN.md`.
3. **Legal/Contract** - contracts, agreements, terms
4. **Research Paper** - arXiv/SSRN/DOI prefixes route to `Research/{Publisher}/` with `schema_type=ScholarlyArticle`
5. **E-commerce/Shopping** - product listings, carts
6. **Software UI** - app interfaces, dashboards
7. **Game Assets** - 200+ patterns, sprites, textures, audio
8. **Filepath Matching** - directory structure patterns (includes `parent_folder=Games` fallback)
9. **Content Analysis** - OCR text and CLIP vision
10. **MIME Type Fallback** - file extension

## Output Folders

```
~/Documents/
├── Organization/{CompanyName}/    # Vendor/partner files
├── Personal/{Contacts,Employment,Identification,Certificates,Journal,Events,Legal,Records,Other}/  # Doc-class filing
├── Person/{PersonName}/           # Derived symlink view (regenerated from graph edges,
│                                  # not a filing target) — organize-files person-view
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
| `OCR_EASYOCR_LANGS` | Comma-separated ISO language codes for easyocr (e.g. `en,fr,es`); defaults to `en`. Resolved at Reader-construction time — set it before first OCR use. |
| `--sentry-dsn` | CLI override |

## Dependencies

Requires Python 3.13 (3.14 broken on macOS 26 — see Troubleshooting).

```bash
python3.13 -m venv venv && source venv/bin/activate
pip install -e ".[all]" && brew install tesseract poppler
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| HEIC fails | `pip install pillow-heif` |
| No OCR | `pip install 'python-doctr[torch]'` |
| No AI | `pip install torch transformers` |
| `pyexpat` / `_XML_SetAllocTrackerActivationThreshold` on macOS 26 | brew's `python@3.13`/`@3.14` bottles link against newer `libexpat` than macOS ships. Fix: `brew install expat`, then `install_name_tool -change /usr/lib/libexpat.1.dylib /opt/homebrew/opt/expat/lib/libexpat.1.dylib $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` and `codesign --force --sign - $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` |

## Schema.org Reference

See [`docs/SCHEMA_ORG_ARCHITECTURE.md`](docs/SCHEMA_ORG_ARCHITECTURE.md) for type mappings, IRI generation, JSON-LD context, per-entity `to_schema_org()` implementations, and relationship rules.

## REST API

FastAPI app at `src/api/schema_org_api.py`. Key endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/{entity}/{id}/schema-org` | Single entity as JSON-LD |
| `GET /api/{entity}/schema-org/bulk` | Filtered list as `{"@context":…,"@graph":[…]}` |
| `GET /api/{companies\|people\|locations}/schema-org/by-name/{name}` | Lookup by name |
| `GET /api/schema-org/export` | Full `@graph` document, filterable by entity type |
| `GET /api/schema-org/graph` | Full graph, all entity types |
| `GET /schema/context` | Standalone JSON-LD `@context` document |
| `GET /health` | Service health check |

Entity types: `files`, `categories`, `companies`, `people`, `locations`.

## Gotchas

| Issue | Detail |
|-------|--------|
| Oversized images | Pillow's >178M-pixel decompression-bomb guard raises `DecompressionBombError`; `CLIPClassifier` encode paths catch it and thumbnail to `_CLIP_INPUT_SIZE`, so large maps/renders classify instead of being skipped. |
| CLIP embedding cache | Lives at `.cache/clip_embeddings_v2/` (fp32 `.npy` per image); safe to `rm -rf` to reset |
| `scripts/shared/` import path | Scripts must run from project root so `from shared.x import y` resolves; `organize-files` CLI handles this automatically |
| FileOrganizer modes | `rename_images.py` takes `--profile {photo,screenshot}`; mode default comes from the profile (`photo`=in-place, `screenshot`=folder) but can be overridden with `--mode` or `FILE_ORGANIZE_MODE` |
| Unified CLIP+OCR API | `classify_with_ocr_fallback()` in `scripts/shared/clip_classification.py` is the shared entry point; returns `CLIPResult(category, confidence, all_scores)`; both renamer tools call it |
| Screenshot OCR keyword threshold | `_SCREENSHOT_OCR_KEYWORD_THRESHOLD = 0.10` in `src/organizers/content_organizer.py` (re-exported by `scripts/file_organizer_content_based.py`) — do not raise without verifying eval impact (higher values silently reject valid scores). |
| Generator API | `generators.py` has no fluent builders — build schemas via `set_property(name, value, PropertyType)` or the `add_person`/`add_organization`/`set_dates` helpers. |
| Golden snapshot tests | `tests/unit/golden/generate_schema/*.json` are recorded baselines for `generate_schema()` output — do not hand-edit; re-record with `UPDATE_GOLDEN=1 pytest tests/unit/test_generate_schema_golden.py` |
| Storage timestamps | Use `from ._time import utcnow` (naive UTC) instead of deprecated `datetime.utcnow()`; DateTime columns are timezone-naive, so do not introduce tz-aware datetimes without a column migration |
| Pruning person edges | `organize-files prune-person <name-or-id>...` deletes a person and its `file→person` edges (dry-run default; `--apply` backs up the DB first); `GraphStore.remove_person_edge` drops a single edge. `--prune-missing` on `person-view`/`index-people` (or `GraphStore.prune_missing_person_edges`) drops edges whose file path no longer exists. The `get_all_people_with_files` denylist is still leaky (false-positive "people" like event/org names create spurious `Person/{Name}/` folders on `person-view --apply` — prune them first). See [`docs/BACKLOG.md` → Person-graph edge hygiene](docs/BACKLOG.md#person-graph-edge-hygiene). |
| Core-query export | `SchemaOrgExporter` defaults to `use_core=True`, serializing via the shared `build_*_jsonld` pure functions in `models.py` — each `to_schema_org()` is a thin delegator, so **edit the builders, not the methods**. Exports **stream** (`_stream_array` + lazy `_iter_records`; File path column-selects + `yield_per`) — don't reintroduce a full `records` list or `json.dumps` of the whole document. Relationship-order parity relies on natural association-row order — don't add `ORDER BY` to `_load_file_refs`. Parity + streaming locked by `tests/integration/test_core_export_parity.py`. |
| Parallel agents — worktree rule | **Never run background/parallel Claude agents in the primary checkout.** Each agent must operate in its own git worktree (`EnterWorktree` / `worktree-agent-*` branches). Concurrent agents in the shared checkout silently clobber each other's changes (branch switch, conflicting commits). A `pre-commit` hook warns when multiple Claude sessions share the same directory. |
| easyocr MPS (Apple Silicon) | easyocr has no usable MPS backend; the Reader always loads on CPU on macOS arm64. CUDA-only guard in `ocr_easyocr._use_gpu()` is intentional. Call `prewarm_reader()` before a batch loop to amortize model-load latency; call `clear_reader()` to reclaim Reader memory between batches or in tests. |
| Screenshot renamer OCR backend | `rename_images.py --profile screenshot` routes `_detect_number` through `extract_screenshot_text` (prefers easyocr when installed, falls back to docTR). The `--profile photo` path uses docTR directly. |
| PII redaction (`scripts/redact_pii.py`) | Rasterizes PDFs/images to flat PNGs (kills hidden text layer + metadata), then OCR-blacks tokens matching digit/email/date/name patterns. Only digit-bearing + configured-name PII is caught — **alphabetic PII (street names, third-party names) is NOT**, so rasterized outputs are flagged `review_recommended` in `manifest.json` and require human review before `git add`. Run: `python scripts/redact_pii.py <path>... --output DIR [--name TERM]`. |

## Testing

```bash
pytest tests/unit/           # ~762 unit tests
pytest tests/integration/    # schema.org export pipeline
pytest tests/performance/ --benchmark-only -m "not slow"   # benchmarks (skip 10k)
pytest tests/e2e/            # Playwright E2E
```

---
**Python:** 3.13 (3.14 blocked by macOS 26 libexpat ABI) | **Version:** 2.1.0 | **Files:** 265,000+ processed
