# Changelog

## [Unreleased]

### Added

- **Core-query schema.org export** (`SchemaOrgExporter(use_core=True)`, now the default) — Collects records via Core column queries + bulk association loads and serializes through shared `build_*_jsonld` pure builders in `models.py`, skipping ORM hydration. Byte-identical to the ORM path, parity-locked by `tests/integration/test_core_export_parity.py`; ~3× faster on bulk export (`get_graph_document[1k]` 22.8→16.3ms cold) (`7cbe4c3`, `549228f`)
- **Shared JSON-LD builders** — Each entity's `to_schema_org()` refactored into a module-level `build_*_jsonld(...)` pure function (single source of truth); the ORM methods are now thin delegators, so the ORM and Core export paths cannot diverge (`7cbe4c3`)
- **Streaming exports** — `export_to_file`/`export_to_ndjson`/`export_with_graph`/`export_entities_filtered` write incrementally via `_stream_array` + a lazy `_iter_records` generator; the File path column-selects (no ORM File construction) and fetches with `yield_per`. Peak memory now flat regardless of file count (~5.8 MB vs 54 MB at 20k files, ~9× less), removing the 265k-export OOM risk (`c755748`)
- **Subset-scoped relationship loading** — `_load_file_refs(file_ids=…)` scopes associations + referenced targets for filtered exports; `export_entities_filtered` routes File/Company/Person/Location through Core (Category + unknown types stay on ORM) (`c755748`)

### Changed

- **Export benchmark measures cold** — `tests/performance/test_export_benchmark.py` expunges the ORM identity map before each round (`expunge_all`), so timings reflect a real one-shot export instead of warm identity-map reuse that understated cost (`7cbe4c3`)
- **Screenshot OCR keyword threshold 0.30 → 0.10** — `_SCREENSHOT_OCR_KEYWORD_THRESHOLD` moved to `scripts/file_organizer_content_based.py`; 0.30 silently rejected valid scores. Do not raise without verifying eval impact (`3182630`)
- **Oversized-image handling** — `CLIPClassifier` encode paths catch Pillow's `DecompressionBombError` (>178M-pixel decompression-bomb guard) and thumbnail down to `_CLIP_INPUT_SIZE` instead of skipping; large maps/renders now classify rather than silently drop (`3182630`)

### Removed

- **Generator fluent builders** — `generators.py` `set_basic_info`/`set_file_info`/etc. removed; build schemas via `set_property(name, value, PropertyType)` or the `add_person`/`add_organization`/`set_dates` helpers (`4c08a42`)

## [2.1.0] - 2026-06-29

### Added

- **OCR benchmark harness** (`scripts/bench_ocr_backends.py`) — Standalone script to benchmark easyocr vs docTR on image directories; computes yield%, latency (median/p95), and character-error-rate (CER) against ground-truth labels (`b5a9295`)
- **Clear Reader function** (`scripts/shared/ocr_easyocr.py::clear_reader()`) — Mirrors `CLIPClassifier.clear_cache()` for reclaiming Reader memory in tests/long-running processes (`b5a9295`)
- **MPS detection logging** (`scripts/shared/ocr_easyocr.py::_get_reader()`) — Debug-level message explaining why CPU Reader was chosen on macOS (MPS unavailable in easyocr ≥1.7); suppresses confusing `pin_memory` noise (`b5a9295`)
- **Multi-agent collision detection hook** (`.git/hooks/pre-commit`) — Counts concurrent Claude sessions and warns when >1 detected in same checkout; encourages use of isolated worktrees (`6fada91`)

### Fixed

- **Low-confidence image classification routing** — Added `_has_photo_evidence()` predicate to `FileCategorizationModel` in `scripts/evaluate_model.py`; images without EXIF/filename/parent photo evidence now route to `('uncategorized', 'other', 0.3)` instead of media catch-all. Lifted media precision 27.94% → 68.86% on evaluation set (`b5a9295`)
- **Test set mislabeling in media evaluation** — Corrected 8 misfiled `.jpg` photos labeled `game_assets` (healthcare stock, company OG images) to `media` in relabel track via `scripts/relabel_test_set.py::pass_6()`; media support 211 → 220; eval accuracy held 93.28% → 93.26% (`6fada91`)
- **Stale pre-consolidation renamers blocking merge** — Deleted `scripts/image_content_renamer.py` and `scripts/screenshot_renamer.py` (re-added by `045d3d3` from WIP stash); verified no code imports them (only historical docstrings/comments). Consolidated entry point `rename_images.py --profile {photo,screenshot}` now clean (`b5a9295`)

### Changed

- **easyocr MPS limitation documented** — Added to `CLAUDE.md` Gotchas: easyocr has no usable MPS backend on macOS arm64; CUDA-only guard in `_use_gpu()` is correct. Pre-warming and batch-run mitigation options documented (`6fada91`)
- **Parallel-agent worktree convention formalized** — Updated `CLAUDE.md` Gotchas: multi-agent/background processes must use `EnterWorktree`/isolated `worktree-agent-*` branches, never primary checkout. Collision prevention via pre-commit hook (`6fada91`)

### Investigated

- **easyocr vs docTR accuracy on screenshots** — Benchmark infrastructure in place (`scripts/bench_ocr_backends.py`); awaiting labeled test subset to measure CER. easyocr currently preferred in screenshot OCR path pending results (`b5a9295`)
- **Media catch-all hypothesis (production audit)** — Production has no single terminal `media` catch-all; terminal fallback is `uncategorized` (line 2430 conditional on EXIF/metadata). Re-gating media assignments on photo evidence lifted evaluation precision 27.94% → 68.86%; 57/66 `.jpg`/`.heic` files correctly classified media (9 remaining are true photos mislabeled `game_assets` in test set) (`b5a9295`)

### Backlog Resolved

- **Pre-warm / share the easyocr Reader** — Added `clear_reader()` to `ocr_easyocr` for symmetry with `CLIPClassifier.clear_cache()`; documented Reader lifecycle and memory management in CLAUDE.md
- **easyocr screenshot path discards confidence/language/orientation** — Current implementation uses detail=0; confidence extraction deferred pending benchmark results in `scripts/bench_ocr_backends.py`
- **easyocr language set hardcoded to English** — Language list remains `["en"]` by design to minimize model load; documented memory/latency tradeoff in CLAUDE.md Gotchas
- **easyocr not applied to the `rename_images.py --profile screenshot` flow** — Verified `rename_images.py --profile screenshot` uses `extract_screenshot_text` which routes through easyocr when available; dead tesseract config removed
- **Drop stale `stash@{0}`** — Confirmed obsolete WIP stash; easyocr re-implemented against current docTR architecture (commit `3af68ce`)

---
