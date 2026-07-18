# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.
**Python:** 3.12–3.13 (3.14 blocked by macOS 26 libexpat ABI) | **Version:** 2.1.0 | **Files:** 265,000+

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
| `organize-files content` | AI-powered organization (CLIP, OCR) — the only DB-writing organizer |
| `organize-files name` / `type` | Filename-pattern / extension-based organization (DB-free by design) |
| `organize-files health` | Check system dependencies |
| `organize-files migrate-ids` | Canonical-ID database migration |
| `organize-files migrate-person` | Migrate `Person/` files → `Personal/{subcat}/` (dry-run default; `--apply`, `--rollback`) |
| `organize-files person-view` | Regenerate `Person/{Name}/` symlink view from graph edges (`--apply`; `--prune-missing`) |
| `organize-files index-people` | Attach `person→file` edges for migrated files, no moves (`--apply`; `--prune-missing`) |
| `organize-files prune-person <name-or-id>...` | Delete people + `file→person` edges, no moves (dry-run default; `--apply` backs up DB) |
| `organize-files update-site` / `timeline` | Regenerate dashboard / timeline data |
| `organize-files preprocess` | ML data preprocessing (`--input`, `--output`) |
| `organize-files evaluate` | Evaluation metrics (`--test-data`, `--output`, `--classifier {baseline,content,unified}`, `--min-support`) |

## Development Commands

```bash
uvicorn src.api.schema_org_api:app --reload   # Start REST API (FastAPI)
black src/ scripts/                            # format
flake8 src/ scripts/                           # lint
mypy src/ scripts/                             # type check
npm run docs:api                               # regenerate pdoc3 API docs (docs/api submodule)
```

**API docs:** `docs/api` is a git submodule (`integritystudio/schema-org-file-system-apidocs`) holding generated pdoc3 HTML under `docs/api/src/`. Regenerate with `npm run docs:api` (sets `PYTHONPATH=src`), then commit+push inside `docs/api` and commit the bumped gitlink in the parent. Fresh clones need `--recurse-submodules`.

## Project Structure

Full module map, data flow, and diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Pipeline internals + renamer modes: [`docs/FILE_ORGANIZATION.md`](docs/FILE_ORGANIZATION.md). Schema.org type mappings: [`docs/SCHEMA_ORG_ARCHITECTURE.md`](docs/SCHEMA_ORG_ARCHITECTURE.md).

```
├── src/                    # Core library
│   ├── cli.py              # Unified CLI entry point
│   ├── generators.py       # Schema.org metadata generation
│   ├── classifiers/        # content_classifier + entity_detector (company/person extraction)
│   ├── organizers/         # base/content/name organizers + category_config/mime_classifier
│   ├── pipeline/           # batch_processor, file_processor
│   ├── analyzers/          # image/content analyzers, EXIF/GPS extraction
│   ├── scoring/            # signal-based scorer (signals/, scorer, registry, weights)
│   ├── ml/                 # feature_extractor, data_preprocessor
│   ├── feedback/           # correction_tracker + feedback_loop
│   ├── api/                # schema_org_api (FastAPI), schema_org_models, timeline_api
│   └── storage/            # graph_store, models (to_schema_org), migrations, exporters
├── scripts/
│   ├── shared/             # clip_classification, ocr_classifier, clip_utils/cache, file_organizer, filename_classifier
│   ├── file_organizer_content_based.py  # thin CLI wrapper over src/{classifiers,analyzers,organizers,pipeline}
│   ├── rename_images.py    # Unified CLIP renamer; --profile {photo,screenshot}
│   └── redact_pii.py       # Rasterize + OCR-redact PII before adding to VCS
├── tests/                  # unit/ (~1,070), integration/, performance/, e2e/ (Playwright+OTEL)
├── _site/                  # Dashboard UI
└── results/                # Reports & database
```

**`scripts/shared/` import path:** run scripts from project root (or with `scripts/` on `sys.path`) so `from shared.x import y` resolves. The `organize-files` CLI handles this automatically.

## Classification Priority

Layered pipeline (see [`docs/FILE_ORGANIZATION.md`](docs/FILE_ORGANIZATION.md#4b-classification-priority-contentorganizerdetect_file_category-srcorganizerscontent_organizerpy)):

**Default engine:** `organize-files content` now defaults to the **unified** weighted-signal scorer (`--scorer unified`; weights/signals in `src/scoring/`). The numbered chain below is the **legacy** engine — still selectable via `--scorer legacy` (also the base `ContentOrganizer` default, kept so Phase-0 unit tests pin the chain); `--scorer shadow` runs legacy placement while logging unified decisions for comparison.

1. **Organization** — client/vendor/invoice/company names
2. **Personal Documents** — resume/CV/vCard (`contacts`), employment, identification, certificates (OCR). Person attribution is a graph relationship (`GraphStore.add_file_to_person`), not a filing category — see `docs/changelog/2.1.0/PERSON_TAXONOMY_OPTION_C_PLAN.md`
3. **Legal/Contract** — contracts, agreements, terms
4. **Financial** — invoice/billing/statement/receipt filenames → `Financial/{Invoices,Statements,Other}`; checked before the event-date heuristic (events need month+day adjacency; a bare year does not qualify)
5. **Research Paper** — arXiv/SSRN/DOI → `Research/{Publisher}/` (`schema_type=ScholarlyArticle`)
6. **E-commerce** → 7. **Software UI** → 8. **Game Assets** (200+ patterns) → 9. **Filepath** (incl. `parent_folder=Games`) → 10. **Content Analysis** (OCR+CLIP) → 11. **MIME Type** fallback

## Output Folders

```
~/Documents/
├── Organization/{CompanyName}/    # Vendor/partner files
├── Personal/{Contacts,Employment,Identification,Certificates,Journal,Events,Legal,Records,Other}/
├── Person/{PersonName}/           # Derived symlink view (organize-files person-view), not a filing target
├── GameAssets/  Financial/  Technical/  Media/
```

## Environment

| Variable | Description |
|----------|-------------|
| `FILE_SYSTEM_SENTRY_DSN` / `--sentry-dsn` | Sentry error tracking (Doppler) / CLI override |
| `FILE_ORGANIZE_MODE` | `in-place` (image renamer default) or `folder` (screenshot renamer default) |
| `OCR_EASYOCR_LANGS` | Comma-separated ISO codes for easyocr (default `en`); resolved at Reader-construction time — set before first OCR use |

## Dependencies

Requires Python 3.12 or 3.13 (3.14 broken on macOS 26; `pyproject.toml` declares `>=3.8` but 3.12/3.13 are tested).

```bash
python3.13 -m venv venv && source venv/bin/activate
pip install -e ".[all]" && brew install tesseract poppler
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| HEIC fails | `pip install pillow-heif` |
| No OCR | `pip install 'python-doctr[torch]'` |
| No AI | `pip install torch open-clip-torch` (or `pip install -e ".[ai]"`) |
| `pyexpat` / `_XML_SetAllocTrackerActivationThreshold` on macOS 26 | brew's `python@3.13/3.14` link a newer `libexpat` than macOS ships. `brew install expat`, then `install_name_tool -change /usr/lib/libexpat.1.dylib /opt/homebrew/opt/expat/lib/libexpat.1.dylib $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` and `codesign --force --sign - $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` |

## REST API

FastAPI app at `src/api/schema_org_api.py`. Entity types: `files`, `categories`, `companies`, `people`, `locations`.

| Endpoint | Description |
|----------|-------------|
| `GET /api/{entity}/{id}/schema-org` | Single entity as JSON-LD |
| `GET /api/{entity}/schema-org/bulk` | Filtered list as `{"@context":…,"@graph":[…]}` |
| `GET /api/{companies\|people\|locations}/schema-org/by-name/{name}` | Lookup by name |
| `GET /api/schema-org/export` / `/graph` | Full `@graph` document / full graph |
| `GET /schema/context` | Standalone JSON-LD `@context` |
| `GET /health` | Service health check |

## Testing

```bash
pytest tests/unit/           # ~1,070 unit tests
pytest tests/integration/    # schema.org export pipeline
pytest tests/performance/ --benchmark-only -m "not slow"
pytest tests/e2e/            # Playwright E2E
```

## Gotchas

- **Oversized images** — Pillow's >178M-pixel bomb guard raises `DecompressionBombError` during `img.load()` (called inside `thumbnail()`). `CLIPClassifier._thumbnail_oversized` temporarily sets `Image.MAX_IMAGE_PIXELS = None` before the thumbnail call and restores it after, so oversized images are downscaled to `_CLIP_INPUT_SIZE` and classify instead of erroring out. Not thread-safe (global mutation), but the organizer pipeline is single-threaded for image classification.
- **CLIP embedding cache** — `.cache/clip_embeddings_v2/` (fp32 `.npy` per image); `rm -rf` to reset.
- **FileOrganizer modes** — `rename_images.py --profile {photo,screenshot}`; mode default comes from the profile (`photo`=in-place, `screenshot`=folder), overridable via `--mode` / `FILE_ORGANIZE_MODE`.
- **Unified CLIP+OCR API** — `classify_with_ocr_fallback()` in `scripts/shared/clip_classification.py` is the shared entry point; returns `CLIPResult(category, confidence, all_scores)`. Both renamers call it.
- **Screenshot OCR keyword threshold** — `_SCREENSHOT_OCR_KEYWORD_THRESHOLD = 0.10` in `src/organizers/content_organizer.py` (re-exported by `scripts/file_organizer_content_based.py`) — do not raise without verifying eval impact.
- **Generator API** — no fluent builders; build schemas via `set_property(name, value, PropertyType)` or `add_person`/`add_organization`/`set_dates`.
- **Golden snapshot tests** — `tests/unit/golden/generate_schema/*.json` are recorded baselines; re-record with `UPDATE_GOLDEN=1 pytest tests/unit/test_generate_schema_golden.py`, do not hand-edit.
- **Storage timestamps** — use `from ._time import utcnow` (naive UTC), not `datetime.utcnow()`; DateTime columns are tz-naive — no tz-aware datetimes without a column migration.
- **Core-query export** — `SchemaOrgExporter` defaults to `use_core=True`, serializing via the shared `build_*_jsonld` pure functions in `models.py` (each `to_schema_org()` delegates) — **edit the builders, not the methods**. Exports **stream** (`_stream_array` + lazy `_iter_records`; File path column-selects + `yield_per`) — don't reintroduce a full `records` list. Relationship-order parity relies on natural association-row order — no `ORDER BY` in `_load_file_refs`. Locked by `tests/integration/test_core_export_parity.py`.
- **Parallel agents — worktree rule** — never run background/parallel Claude agents in the primary checkout; each must use its own git worktree (`EnterWorktree`). Concurrent agents in the shared checkout silently clobber each other. A `pre-commit` hook warns on shared directories.
- **easyocr on Apple Silicon** — no usable MPS backend; Reader always loads on CPU on macOS arm64 (CUDA-only guard in `ocr_easyocr._use_gpu()` is intentional). Call `prewarm_reader()` before a batch loop; `clear_reader()` to reclaim memory.
- **Screenshot renamer OCR** — `--profile screenshot` routes `_detect_number` through `extract_screenshot_text` (easyocr preferred, docTR fallback); `--profile photo` uses docTR directly. Naming prefers a title-like OCR line (`title_snippet_from_lines`: first 3 lines, 10–50 chars, 40-char cap) → `Screenshot_<title>`, else the CLIP label.
- **EXIF/GPS extraction** — `extract_exif_data`/`extract_gps_coordinates` (`src/analyzers/image_metadata.py`) fall back to piexif when PIL yields nothing or surfaces `GPSInfo` as a bare offset; `_convert_to_degrees` handles piexif pairs and modern-Pillow floats. EXIF locations create `file→location` edges via `get_metadata_summary()`; reverse geocoding falls back to county when Nominatim lacks city/town/village.
- **PII redaction (`scripts/redact_pii.py`)** — rasterizes PDFs/images to flat PNGs (kills text layer + metadata), then OCR-blacks digit/email/date/name tokens. Alphabetic PII (street/third-party names) is NOT caught — outputs are flagged `review_recommended` in `manifest.json` and need human review before `git add`. Run: `python scripts/redact_pii.py <path>... --output DIR [--name TERM]`.
- **Person-graph edge hygiene** — `GraphStore.remove_person_edge` drops a single edge; `--prune-missing` (`prune_missing_person_edges`) drops edges whose file path is gone. `get_all_people_with_files` denylist is leaky (event/org names create spurious `Person/{Name}/` folders on `person-view --apply` — prune first). See [`docs/BACKLOG.md`](docs/BACKLOG.md#person-graph-edge-hygiene).
- **Graph persistence is content-only** — only `organize-files content` (BatchProcessor → FileProcessor → `GraphStore`) writes to the graph store and records `organization_sessions`/`files.session_id` (what the timeline groups by). `type`/`name` are DB-free by design. Sole `GraphStore.add_file` callers: content `FileProcessor` and `person_migration`. See [`docs/FILE_ORGANIZATION.md`](docs/FILE_ORGANIZATION.md) §5.
