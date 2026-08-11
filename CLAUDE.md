# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.
**Python:** 3.12–3.14, pyenv builds (brew pythons blocked on macOS 26 by libexpat ABI) | **Version:** 2.1.0 | **Files:** 265,000+

## Quick Start

```bash
# First-time setup (pyenv-built Python — see Dependencies)
python3.14 -m venv venv && source venv/bin/activate
pip install -e ".[all]" && brew install tesseract poppler
python scripts/download_census_names.py   # surnames.txt gazetteer (gitignored; person detection needs it)

# Daily use
source venv/bin/activate
organize-files content --source ~/Downloads --dry-run --limit 100
organize-files health                    # Should report 12/12 features
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `organize-files content` | AI-powered organization (CLIP, OCR) — the only DB-writing organizer |
| `organize-files name` / `type` | Filename-pattern / extension-based organization (DB-free by design) |
| `organize-files find-duplicates` | Report near-duplicate files (re-encoded/resized/PDF-vs-image copies) — read-only, no moves or DB writes. `--threshold`, `--max-neighbors`, `--no-pdfs`, `--limit`, `--output` |
| `organize-files health` | Check system dependencies |
| `organize-files migrate-ids` | Canonical-ID database migration |
| `organize-files migrate-person` | Migrate `Person/` files → `Personal/{subcat}/` (dry-run default; `--apply`, `--rollback`) |
| `organize-files person-view` | Regenerate `Person/{Name}/` symlink view from graph edges (`--apply`; `--prune-missing`) |
| `organize-files index-people` | Attach `person→file` edges for migrated files, no moves (`--apply`; `--prune-missing`) |
| `organize-files prune-person <name-or-id>...` | Delete people + `file→person` edges, no moves (dry-run default; `--apply` backs up DB) |
| `organize-files reconcile` | Resync the graph with disk, no file moves (dry-run default; `--apply` backs up DB): `--set-category FILE CAT` retarget one edge, `--prune-missing` drop rows whose paths are all gone, `--backfill-categories` attach edges to rows that have none |
| `organize-files migrate-category-identity` | Make `categories.full_path` the unique identity (was `name`); realigns `canonical_id` |
| `organize-files migrate-file-counts` | Drop the `file_count` cache columns + create the four `file_*` association indexes the derived count needs (dry-run via `--dry-run`) |
| `organize-files update-site` / `timeline` | Regenerate dashboard / timeline data |
| `organize-files preprocess` | ML data preprocessing (`--input`, `--output`) |
| `organize-files evaluate` | Evaluation metrics (`--test-data`, `--output`, `--classifier {baseline,content,unified}`, `--min-support`) |

## Development Commands

```bash
uvicorn src.api.schema_org_api:app --reload   # Start REST API (FastAPI)
make lint                                      # style gate: black --check + flake8 over src/ scripts/ tests/ (also `npm run lint`)
make format                                    # black in place, then report the findings black cannot fix (also `npm run format`)
make schema-check                              # assert scripts/d1/schema.sql matches the models (also `npm run schema:check`)
make d1-schema                                 # regenerate it after ANY src/storage/models.py change (also `npm run schema:generate`)
mypy src/ scripts/                             # type check (not in the gate — see below)
npm run docs:api                               # regenerate pdoc3 API docs (docs/api submodule)
make calibrate                                 # scoring calibration harness (backfill -> backtest -> grid -> sweeps -> goldens); stages: make clip-backfill|backtest|weight-grid|threshold-sweeps|golden
BUDGET=250 make weight-search                  # nevergrad joint weight+threshold search; NOT part of `calibrate` (exploratory, budget-priced). Reports a proposal only — never writes weights.py
```

**The style gate is CI-enforced, and its version bounds are load-bearing.** `.github/workflows/checks.yml` (job `lint`) runs the same two commands as `make lint` on every push and PR, installing from `requirements-lint.txt` rather than `pip install -e ".[dev]"` — the base deps pull torch via `python-doctr`, which a lint job has no use for. The `<27` bound on black is not caution: **black changes its stable style once a year at the first release of a new major**, so an unpinned install would eventually demand a reformat of correctly-formatted code and fail the gate on an untouched tree. Keep `requirements-lint.txt` and the `dev` extra in `pyproject.toml` in step. `mypy` is deliberately *not* in the gate — it needs the full dependency set (and therefore torch) to resolve imports, so it stays a local/pre-merge check; a stray `no-any-return` is instead caught by the Stop hook.

**Profiling the classification hot path:** `scripts/profile_pipeline.py` cProfiles the unified scorer over a dir/file set and prints wall + per-file, a grouped hotspot summary (OCR-CNN / image-decode / face / CLIP), top-N functions, and OCR-invocation + gate-skip counts. Use it for before/after comparisons of any classification-cost change (OCR gating, signal reordering). Companion `scripts/eval_ocr_gate.py` evaluates the CLIP OCR gate (`--ocr-clip-topk`) on a folder-labeled corpus, sweeping top-k/margin for recall vs OCR-skip.

```bash
PYTHONPATH=src:scripts:. python scripts/profile_pipeline.py --source ~/Documents/Media/Photos --limit 50
PYTHONPATH=src:scripts:. python scripts/profile_pipeline.py --source DIR --ocr-clip-topk 3   # gate on
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
│   ├── similarity/         # near-dupe: SSCD descriptors + faiss index (worker.py = process isolation)
│   └── storage/            # graph_store, models (to_schema_org), migrations, exporters
├── scripts/
│   ├── shared/             # clip_classification, ocr_classifier, clip_utils/cache, file_organizer, filename_classifier
│   ├── file_organizer_content_based.py  # thin CLI wrapper over src/{classifiers,analyzers,organizers,pipeline}
│   ├── rename_images.py    # Unified CLIP renamer; --profile {photo,screenshot}
│   └── redact_pii.py       # Rasterize + OCR-redact PII before adding to VCS
├── tests/                  # unit/ (~2,407), integration/ (~192), performance/, e2e/ (Playwright+OTEL)
├── _site/                  # Dashboard UI
└── results/                # Reports & database
```

**`scripts/shared/` import path:** run scripts from project root (or with `scripts/` on `sys.path`) so `from shared.x import y` resolves. The `organize-files` CLI handles this automatically.

## Unified Scoring

`organize-files content` classifies via the **unified weighted-signal scorer** (`src/scoring/`: 19 signal modules in `signals/`, weights in `weights.py`, orchestration in `scorer.py`). All applicable signals run in cost-tier waves (cheap → mid → heavy, with early exit); the highest aggregated `(category, subcategory)` wins, with margin/confidence thresholds routing weak decisions to `uncategorized`. The legacy 10-tier first-match-wins chain and shadow mode were **removed in Phase 5** (UNIFIED_SCORING_PLAN §6); the extracted per-tier `classify_*` methods remain on `ContentOrganizer` as directly-testable shims over their signals. Signal coverage includes: organization/person entity detection (person attribution is a graph relationship — `GraphStore.add_file_to_person` — not a filing category, see `docs/changelog/2.1.0/PERSON_TAXONOMY_OPTION_C_PLAN.md`), legal, financial (`Financial/{Invoices,Statements,Other}`), research publishers (arXiv/SSRN/DOI → `Research/{Publisher}/`, `ScholarlyArticle`), game assets, filepath, screenshot OCR, CLIP vision, scene probe, media heuristics, and a deliberately weak MIME fallback. See [`docs/FILE_ORGANIZATION.md`](docs/FILE_ORGANIZATION.md) and `docs/architecture/UNIFIED_SCORING_PLAN.md`.

## Output Folders

```
~/Documents/
├── Organization/{CompanyName}/    # Vendor/partner files
├── Events/{EventName}/            # Event docs (flyers/maps/programs); name from EventContentSignal, schema.org Event
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

Requires Python 3.12–3.14 (`pyproject.toml` declares `requires-python = "<=3.14"`; the current venv runs pyenv-built 3.14.0). On macOS 26, use a **pyenv-built** interpreter — pyenv links expat statically, avoiding the libexpat ABI break that hits brew's `python@3.13/3.14` (see Troubleshooting).

```bash
python3.14 -m venv venv && source venv/bin/activate
pip install -e ".[all]" && brew install tesseract poppler
```

Extras: `ai` (torch/open-clip/easyocr/opencv), `docs` (pdf/docx/xlsx), `ml` (scikit-learn), `names`, `geo`, `monitoring` (Sentry), `similarity` (faiss-cpu — near-dupe index; additive to `ai`, which supplies the torch the SSCD descriptors need), and `dev` (pytest/black/flake8/mypy + nevergrad for `make weight-search`). `all` = everything but `dev`.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| HEIC fails | `pip install pillow-heif` |
| No OCR | `pip install 'python-doctr[torch]'` |
| No AI | `pip install torch open-clip-torch` (or `pip install -e ".[ai]"`) |
| `pyexpat` / `_XML_SetAllocTrackerActivationThreshold` on macOS 26 | brew's `python@3.13/3.14` link a newer `libexpat` than macOS ships; pyenv-built interpreters are unaffected (static expat) — prefer those. To patch a brew python: `brew install expat`, then `install_name_tool -change /usr/lib/libexpat.1.dylib /opt/homebrew/opt/expat/lib/libexpat.1.dylib $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` and `codesign --force --sign - $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` |

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
pytest tests/unit/           # ~2,427 unit tests (also: npm run test:unit)
pytest tests/integration/    # schema.org export pipeline
pytest tests/performance/ --benchmark-only -m "not slow"
pytest tests/e2e/            # Playwright E2E (npm run test:e2e)
```

## Gotchas

- **Oversized images** — Pillow's >178M-pixel bomb guard raises `DecompressionBombError` during `img.load()` (called inside `thumbnail()`). `CLIPClassifier._thumbnail_oversized` temporarily sets `Image.MAX_IMAGE_PIXELS = None` before the thumbnail call and restores it after, so oversized images are downscaled to `_CLIP_INPUT_SIZE` and classify instead of erroring out. Not thread-safe (global mutation), but the organizer pipeline is single-threaded for image classification.
- **CLIP embedding cache** — `.cache/clip_embeddings_v2/` (fp32 `.npy` per image); `rm -rf` to reset.
- **faiss and torch cannot coexist in one process (macOS)** — both bundle `libomp.dylib`; the second to initialise aborts with `OMP: Error #15`, and the abort fires on faiss's **first parallel region** (`IndexFlat.search`), not at import — so it survives a smoke test and dies on real work. Import order, `OMP_NUM_THREADS=1` and `faiss.omp_set_num_threads(1)` all fail to help, and `KMP_DUPLICATE_LIB_OK=TRUE` **segfaults** (exit 139) rather than degrading. `src/similarity/` therefore runs the faiss stage in a subprocess (`worker.py`); `__init__.py` is lazy (PEP 562), availability is probed with `importlib.util.find_spec`, and the unit tests group *through* the worker — an in-process faiss call under pytest kills the run once any module has imported torch. Regression guard: `TestProcessIsolation::test_runs_with_torch_already_loaded`.
- **Near-duplicate descriptors are SSCD, not CLIP** — `.cache/sscd_descriptors_v1/` (512-d, same shape as the CLIP cache, **not interchangeable**). CLIP embeddings are semantic, so a CLIP-keyed dupe report pairs two *different* event flyers; SSCD is trained for "same image, re-encoded/resized/cropped". Model is a TorchScript checkpoint auto-downloaded to `.cache/sscd_models/` on first use — use the `sscd_disc_*` weights, never `sscd_imagenet_*` (research-only dataset lineage). Preprocessing is upstream's `skew_320`, not the headline `small_288`: aspect-preserving resize yields ragged tensors that `torch.stack` rejects, which surfaces as a whole batch reported "could not be encoded". Changing the transform invalidates the cache — bump `DESCRIPTOR_CACHE_DIR`.
- **FileOrganizer modes** — `rename_images.py --profile {photo,screenshot}`; mode default comes from the profile (`photo`=in-place, `screenshot`=folder), overridable via `--mode` / `FILE_ORGANIZE_MODE`.
- **Unified CLIP+OCR API** — `classify_with_ocr_fallback()` in `scripts/shared/clip_classification.py` is the shared entry point; returns `CLIPResult(category, confidence, all_scores)`. Both renamers call it.
- **Screenshot OCR keyword threshold** — `_SCREENSHOT_OCR_KEYWORD_THRESHOLD = 0.10` in `src/organizers/content_organizer.py` (re-exported by `scripts/file_organizer_content_based.py`) — do not raise without verifying eval impact.
- **Generator API** — no fluent builders; build schemas via `set_property(name, value, PropertyType)` or `add_person`/`add_organization`/`set_dates`.
- **Golden snapshot tests** — `tests/unit/golden/generate_schema/*.json` are recorded baselines; re-record with `UPDATE_GOLDEN=1 pytest tests/unit/test_generate_schema_golden.py`, do not hand-edit.
- **Storage timestamps** — use `from ._time import utcnow` (naive UTC), not `datetime.utcnow()`; DateTime columns are tz-naive — no tz-aware datetimes without a column migration.
- **Core-query export** — `SchemaOrgExporter` defaults to `use_core=True`, serializing via the shared `build_*_jsonld` pure functions in `models.py` (each `to_schema_org()` delegates) — **edit the builders, not the methods**. Exports **stream** (`_stream_array` + lazy `_iter_records`; File path column-selects + `yield_per`) — don't reintroduce a full `records` list. Relationship-order parity relies on natural association-row order — no `ORDER BY` in `_load_file_refs`. Locked by `tests/integration/test_core_export_parity.py`.
- **Parallel agents — worktree rule** — never run background/parallel Claude agents in the primary checkout; each must use its own git worktree (`EnterWorktree`). Concurrent agents in the shared checkout silently clobber each other. A `pre-commit` hook warns on shared directories. **The same hazard applies to concurrent *interactive* sessions, which this rule long failed to name — and there the clobber arrives at commit time, not edit time.** Demonstrated 2026-08-11: `/git-commit-smart` blanket-staged a clean-looking tree and swept 8 files of another live session's work into `58f7659`, under a message describing only the 5-line test fix that actually belonged to the committing session. Nothing was lost (it is all in git), but the authorship boundary and the message are wrong in history. **In a shared checkout, commit by explicit path (`git add <path>`) — never `git add -A`/`-a`, and never a tool that stages the whole tree.** The skill's own shared-checkout warning fires *after* the commits exist, so it annotates rather than prevents. See [`docs/BACKLOG.md`](docs/BACKLOG.md).
- **HEIC reaches OCR only as pixels, never as a path** — `register_heif_opener()` teaches *PIL* to open HEIC and nothing else, so both readers used to fail on their own decode: easyocr's CRAFT detector calls `cv2.imread` (returns `None` → `'NoneType' object has no attribute 'shape'`) and docTR's `DocumentFile.from_images` raises `ValueError: unable to read file`. Both were silent — the pipeline logged and continued CLIP-only, so every `.heic` lost `screenshot_ocr`/`text_content`/`kie_structured` as voters. Fixed 2026-08-11 by decoding via PIL and handing an array down: `_readtext_input` (`ocr_easyocr.py`) and the HEIC branch of `_run_image_ocr` (`ocr_classifier.py`). Extensions come from `HEIC_HEIF_EXTENSIONS` (`scripts/shared/constants.py`) — one source, aliased `_HEIC_EXTENSIONS` in both modules. The docTR branch previously had a spurious `_PREPROCESS_AVAILABLE` gate that re-introduced the `DocumentFile.from_images` fallthrough when preprocessing deps were absent; removed in `7899442` — the decode uses `_load_rgb` (PIL only), so gating on preprocessing availability was incorrect. **One open residual:** recall was never measured on text-bearing HEICs, because the CLIP OCR gate (`--ocr-clip-topk`, K=3) can skip OCR before either reader is reached — needs a HEIC-specific labelled corpus.
- **easyocr on Apple Silicon** — no usable MPS backend; Reader always loads on CPU on macOS arm64 (CUDA-only guard in `ocr_easyocr._use_gpu()` is intentional). Call `prewarm_reader()` before a batch loop; `clear_reader()` to reclaim memory.
- **Screenshot renamer OCR** — `--profile screenshot` routes `_detect_number` through `extract_screenshot_text` (easyocr preferred, docTR fallback); `--profile photo` uses docTR directly. Naming prefers a title-like OCR line (`title_snippet_from_lines`: first 3 lines, 10–50 chars, 40-char cap) → `Screenshot_<title>`, else the CLIP label.
- **EXIF/GPS extraction** — `extract_exif_data`/`extract_gps_coordinates` (`src/analyzers/image_metadata.py`) fall back to piexif when PIL yields nothing or surfaces `GPSInfo` as a bare offset; `_convert_to_degrees` handles piexif pairs and modern-Pillow floats. EXIF locations create `file→location` edges via `get_metadata_summary()`; reverse geocoding falls back to county when Nominatim lacks city/town/village.
- **PII redaction (`scripts/redact_pii.py`)** — rasterizes PDFs/images to flat PNGs (kills text layer + metadata), detects and covers barcodes/QR codes via cv2 (non-zero exit + `barcode_unredacted: true` in manifest when a barcode is detected but not localised), then OCR-blacks digit/email/date/name tokens. Alphabetic PII (street/third-party names, health conditions) requires `--redact-terms TERM` (repeatable, case-insensitive substring match per OCR word); multi-word terms must be split. Rotated text and low-contrast text can still be missed. All raster outputs are flagged `review_recommended`. Run: `python scripts/redact_pii.py <path>... --output DIR [--name TERM] [--redact-terms TERM]`.
- **Person-graph edge hygiene** — `GraphStore.remove_person_edge` drops a single edge; `--prune-missing` (`prune_missing_person_edges`) drops edges whose file path is gone. `get_all_people_with_files` denylist is leaky (event/org names create spurious `Person/{Name}/` folders on `person-view --apply` — prune first). See [`docs/BACKLOG.md`](docs/BACKLOG.md#person-graph-edge-hygiene).
- **Graph persistence is content-only** — only `organize-files content` (BatchProcessor → FileProcessor → `GraphStore`) writes to the graph store and records `organization_sessions`/`files.session_id` (what the timeline groups by). `type`/`name` are DB-free by design. Sole `GraphStore.add_file` callers: content `FileProcessor` and `person_migration`. See [`docs/FILE_ORGANIZATION.md`](docs/FILE_ORGANIZATION.md) §5.
- **Python 3.14 argparse colour breaks CLI-output asserts — but not via `FORCE_COLOR`** — argparse colourizes help/usage/error text, so plain-substring asserts (`"usage: organize-files" in out`) can fail. Route any test asserting on CLI/argparse output through the `run_cli` helper in `tests/integration/test_cli.py`, which monkeypatches `NO_COLOR=1` — that overrides every colour source and is the durable guard. **Correction (2026-07-27):** this entry previously claimed the shell profile exports `FORCE_COLOR=3`. It does not — `FORCE_COLOR` appears in zero commits across all refs in `~/dotfiles`, is unset in a login+interactive zsh and in the tool env, is absent from iTerm's plist, and piped `argparse --help` output is ANSI-free. So `env -u FORCE_COLOR` on tool output is a placebo; if piped output ever carries ANSI, use `NO_COLOR=1` or `PYTHON_COLORS=0`. See the shell-gotchas section in `~/.claude/CLAUDE.md`.
- **DB backup filenames sort neither by name nor by mtime** — `results/file_organization.db.bak-*` mixes plain `bak-<%Y%m%d_%H%M%S>` with labelled forms (`bak-refile-20260726_165917`), and `r` > digits, so newest-by-name picks the *older* file. Newest-by-mtime is worse: `shutil.copy2` preserves the source mtime, so a fresh backup inherits the live DB's old timestamp, and the `-wal`/`-shm` sidecars sort ahead of the DB itself. Reference a backup by its exact name, or parse the trailing timestamp. Also note `mode=ro` URIs fail (`unable to open database file`) on a WAL-mode copy with no `-shm` — copy it aside and open normally.
- **Scoring weights are calibrated — don't move without evidence** — `src/scoring/weights.py` priors and `MIN_DECISION_{CONFIDENCE,MARGIN}` were re-tuned 2026-07-26 to a measured local optimum (`docs/architecture/scoring-calibration-20260726.md`). Any change must run `make calibrate` (fix/break/neutral vs stored decisions) and hold the golden suite. Known invariants: `W_ORG > W_PERSON > W_LEGAL`; `W_MIME < MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN`; `W_FILENAME` has no downward headroom. The three invariants are also encoded as constraints in `scripts/weight_search.py:constraint_violations` — update both.
- **`make weight-search` searched the joint space and found nothing (2026-08-11)** — nevergrad over 19 priors + both thresholds, across `NGOpt`/`CMA`/`TwoPointsDE` at budgets 120–250: train non-media agreement never moved off the shipped 59/164, and every best candidate was flat or **−1** on the holdout slice. Corroborates the 2026-07-26 calibration; the binding constraint is the corpus (164 non-media labelled rows, biased oracle), not the optimiser — more labels beat more budget. Two traps if you extend it: **`--seed` is a no-op under the default `NGOpt`** (a meta-optimiser that picks a deterministic local algorithm from the shipped init — seeds 0/1/2 are byte-identical; vary `--optimizer` instead), and nevergrad's **default mutation sigma is 1.0 regardless of bounds**, which dwarfs these bands (W_MIME spans 0.24) and clips nearly every mutation to the boundary — sigma is sized to span/6, and `set_mutation` must precede `set_bounds` or you get a spurious "bounds are 0.32 sigma away" warning against the sigma it is about to replace.
- **Never use `hash()` for anything persisted or compared across runs** — string hashing is randomised per process (`PYTHONHASHSEED`). It silently reshuffled `weight_search.py`'s train/holdout split on every run, so two runs reported *different baselines off different row sets* and the generalisation check compared nothing. Use `hashlib`; regression-tested across subprocesses in `test_weight_search.py::test_split_is_stable_across_processes`.
- **Backtest replay oracle** — `files.image_classification` (CLIP scores) is written only by `scripts/backfill_clip_scores.py`, never by production; re-run it after new content runs. The replay classifies under `original_path` (pre-move), so `SceneSignal` needs the harness's context-path→`current_path` map to find cached embeddings. Stored decisions are a biased oracle (manual corrections, pre-unified placements) — trust the non-media slice; media-row disagreements may be fidelity artifacts. Some stored labels are simply wrong — inspect actual rows (`winning_signals`, OCR text) before "fixing" a signal for a disagreement.
- **Category identity is `full_path`, not `name`** — `name` repeats across parents (`other` under 15 categories), so `full_path` carries the UNIQUE index and is what `Category.generate_canonical_id` hashes. `get_or_create_category` keys every lookup (existence, parent, IntegrityError recovery) on `full_path` and **raises** rather than returning `None`; `add_file_to_category`'s `False` return must never be ignored. Before 2026-07-26 `name` was UNIQUE, which silently dropped category edges for 26% of rows — existing databases need `organize-files migrate-category-identity`, then `organize-files reconcile --backfill-categories` to repair orphaned rows (a plain `content` re-run can't: correctly-placed files short-circuit at `already_organized` before persistence).
- **`reconcile --backfill-categories` derives from disk, so duplicate documents legitimately split across categories** — the backfill answers "where does this file *sit*", never "what is this file". `resolve_taxonomy_folder` matches the file's folder exactly, then strips trailing segments in a loop until an ancestor is in the taxonomy, so entity-named folders resolve at any depth (`Events/{Name}/2026/maps` → `Events`, `Media/Interiors/{Prop}/{Room}` → `Media/Interiors`); a parent reached *by stripping* that declares no subcategory files under the generic bucket (`Events/*` → `events/other`) while an exact match keeps the bare category (a file directly in `Events/` stays `events`). **Consequence, and it is intended:** two copies of one document in two trees get two different categories — `Documents/Events/Burning Flipside/PlacementMap.pdf` → `events/other` and `Documents/Personal/Events/PlacementMap_300dpi.png` → `personal/events`. Both edges are true, so a category query returns a subset of the logical document family. That is filing, not drift — do **not** "fix" it in the backfill by inferring intent; move the file and re-run if you want them merged. Same reasoning for `Organization/{Name}` → `organization/vendors`: the taxonomy declares `Organization/` as the vendor/partner root, so the pair follows the folder. Folders with no taxonomy ancestor are reported unresolved and never guessed.
- **`file_count` is derived — and its index is load-bearing** — `Category`/`Company`/`Person`/`Location` `.file_count` is a correlated `COUNT` over the association table (`models._edge_count_property`), not a stored column; it was a hand-maintained cache until 2026-07-27 and drifted whenever a write bypassed the call sites. Read it normally (`entity.file_count`); **do not** reintroduce a counter, and note assignment is a silent no-op. Two things will bite: (1) the `ix_file_*_{entity}_id` indexes are required, not optional — dropping one takes a full category read from **7 ms to 20 s** at the 265k-file target (2,860×), and `create_all` will *not* add them to a database whose tables already exist, so existing DBs need `organize-files migrate-file-counts`; (2) `correlate_except(assoc_table)` is required in the subquery, or loading an entity *through* the association table (a lazy-load of `File.categories`) raises `InvalidRequestError: returned no FROM clauses due to auto-correlation`.
- **Scene-probe corpus images are third-party — never commit them** — `results/scene_labels/graphic/` is tracked (own images), but `crello_*` is gitignored: CyberAgent conditions the Crello dataset on the VistaCreate ToS and does not redistribute source templates, so the corpus is reproduced by `scripts/download_crello_graphics.py`, not by git (same arrangement as `download_census_names.py` and the surname gazetteer). `scripts/normalize_scene_corpus.py` equalizes encoding across classes before training — the corpus otherwise leaks class through format/resolution (`place/` was 100% JPEG at 256px, hand-collected `graphic/` mostly PNG at ~1536px; metadata-only accuracy 0.561 vs a 0.327 baseline) — and writes a gitignored derived tree.
- **`scripts/d1/schema.sql` is generated — and now CI-enforced** — `make d1-schema` (`python scripts/d1/generate_schema.py`) renders it from `Base.metadata`. This used to rest on discipline alone and was found stale across three model changes on 2026-07-27 (the category index swap, the `people` validation columns, `file_categories.signal_evidence`); `tests/unit/test_d1_schema_drift.py` now regenerates in memory and diffs against the committed file, run locally by `make schema-check` and in the `schema-drift` job of `.github/workflows/checks.yml`. **Change a model, run `make d1-schema`, commit the SQL** — a failure names the first differing line. That job installs `requirements-schema-check.txt` (SQLAlchemy + pydantic + pytest, no torch), which is deliberately *unpinned*: a SQLAlchemy DDL change should surface as a regenerate-and-commit, not be hidden behind a pin.
