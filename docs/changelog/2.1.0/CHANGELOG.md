# Changelog

## [Unreleased]

### Added

- **`person-view` command** (`organize-files person-view`, `src/storage/person_view_generator.py::PersonViewGenerator`) — Regenerates `~/Documents/Person/{Name}/` as a *derived symlink view* from `file→person` graph edges rather than a filing target. Idempotent: removes only existing symlinks and aborts (`PersonViewRealFileError`) if a real file is found under the view root, so it never deletes data. Dry-run by default; `--apply` to write (`549228f`)
- **`migrate-person` command** (`organize-files migrate-person`, `src/storage/person_migration.py`) — Filesystem-walk-driven migration of existing on-disk `Person/` files into `Personal/{subcat}/`, choosing the subcat from the deepest nested doc-class folder and falling back to a name-dir → `contacts` heuristic. Skips OS junk files (`.DS_Store`, `Thumbs.db`, AppleDouble); `resolve_collision` before every `shutil.move` (never silent-overwrite). Dry-run by default; writes `person-migrate-manifest.json` enabling manifest-backed `--rollback` (`26de0f1`, `f1eaf9e`, `cb1aec0`)
- **`index-people` command** (`organize-files index-people`) — Attaches `person→file` graph edges for already-migrated files without moving them; a filename fallback attributes resume-named people when OCR/content detection is absent (`5698449`, `86843e8`)
- **Reverse person→file graph queries** (`graph_store.py::get_all_people_with_files`, `get_files_by_person`) — Back the symlink view; `get_all_people_with_files` applies an org/keyword denylist to filter false-positive "people" (e.g. `Studio`, `Meeting`, `Inc`) (`44a29c2`)
- **`Personal/` doc-class subcategories** — Added `Contacts` (resumes/CVs/vCards, rescued from `uncategorized`), plus `Journal`, `Events`, `Legal`, and `Records` to the folder maps in both organizers and `content_classifier.py` (`44a29c2`, `6ef71ed`)

### Changed

- **`person` demoted from a filing category to a graph relationship (Option C)** — Classification now emits only a *document class* (`personal`, `medical`, `legal`, …); person attribution lives entirely in `file→person` graph edges. The shared `scripts/shared/filename_classifier.py` and both organizers' `classify_by_person`/`_identify_person_from_id_ocr` now return `("personal", <subcat>, …)` instead of `("person", …)`, eliminating the PDF-vs-image divergence where the same resume classified inconsistently by file type. `Person/{Name}/` is now a regenerable symlink view (see `person-view`), not a mutually-exclusive destination (`44a29c2`)
- **Core-query schema.org export** (`SchemaOrgExporter(use_core=True)`, now the default) — Collects records via Core column queries + bulk association loads and serializes through shared `build_*_jsonld` pure builders in `models.py`, skipping ORM hydration. Byte-identical to the ORM path, parity-locked by `tests/integration/test_core_export_parity.py`; ~3× faster on bulk export (`get_graph_document[1k]` 22.8→16.3ms cold) (`7cbe4c3`, `549228f`)
- **Shared JSON-LD builders** — Each entity's `to_schema_org()` refactored into a module-level `build_*_jsonld(...)` pure function (single source of truth); the ORM methods are now thin delegators, so the ORM and Core export paths cannot diverge (`7cbe4c3`)
- **Streaming exports** — `export_to_file`/`export_to_ndjson`/`export_with_graph`/`export_entities_filtered` write incrementally via `_stream_array` + a lazy `_iter_records` generator; the File path column-selects (no ORM File construction) and fetches with `yield_per`. Peak memory now flat regardless of file count (~5.8 MB vs 54 MB at 20k files, ~9× less), removing the 265k-export OOM risk (`c755748`)
- **Subset-scoped relationship loading** — `_load_file_refs(file_ids=…)` scopes associations + referenced targets for filtered exports; `export_entities_filtered` routes File/Company/Person/Location through Core (Category + unknown types stay on ORM) (`c755748`)

### Changed

- **Export benchmark measures cold** — `tests/performance/test_export_benchmark.py` expunges the ORM identity map before each round (`expunge_all`), so timings reflect a real one-shot export instead of warm identity-map reuse that understated cost (`7cbe4c3`)
- **Screenshot OCR keyword threshold 0.30 → 0.10** — `_SCREENSHOT_OCR_KEYWORD_THRESHOLD` moved to `scripts/file_organizer_content_based.py`; 0.30 silently rejected valid scores. Do not raise without verifying eval impact (`3182630`)
- **Oversized-image handling** — `CLIPClassifier` encode paths catch Pillow's `DecompressionBombError` (>178M-pixel decompression-bomb guard) and thumbnail down to `_CLIP_INPUT_SIZE` instead of skipping; large maps/renders now classify rather than silently drop (`3182630`)

### Fixed

- **`add_relationship` silently drops its `metadata` parameter** — `GraphStore.add_relationship` assigned to the SQLAlchemy-reserved `metadata` attribute instead of the model's `extra_data` column, so relationship metadata was never persisted. The parameter is renamed to `extra_data` and wired to the model's `extra_data` JSON column in both create and update paths; the upsert path only overwrites stored `extra_data` when a new value is provided. Round-trip + upsert-preservation tests added in `tests/unit/test_graph_store_operations.py::TestRelationshipOperations`.

### Removed

- **`person` category routing branches** — Deleted the `category=="person"` destination branches and the standalone `"person"` folder map in both organizers (`get_destination_path`); person-labeled files now route through the `personal` folder map while person names continue flowing to the graph unchanged (`44a29c2`)
- **Generator fluent builders** — `generators.py` `set_basic_info`/`set_file_info`/etc. removed; build schemas via `set_property(name, value, PropertyType)` or the `add_person`/`add_organization`/`set_dates` helpers (`4c08a42`)

### Backlog Resolved (from 2026-07-12 session)

- **Person-graph edge hygiene — prune tooling** — `GraphStore.remove_person_edge(file_id, person)` drops a single edge; `GraphStore.prune_person(name_or_id, dry_run=...)` deletes a person plus all its edges (clearing dependents' merge pointers, never touching files on disk), exposed as `organize-files prune-person <name-or-id>...` — dry-run by default, `--apply` backs up the DB (+ WAL/SHM sidecars) first. Tests: `tests/unit/test_graph_store_prune.py`.
- **Person-graph edge hygiene — prune missing edges** — `GraphStore.prune_missing_person_edges(dry_run=...)` drops edges whose file path (current_path, falling back to original_path) no longer exists on disk, keeping File and Person rows. Exposed as `--prune-missing` on both `organize-files person-view` (prunes before regenerating the view) and `organize-files index-people` (prunes after indexing); honors each command's `--apply`/dry-run flag. Tests: `tests/unit/test_graph_store_prune.py`.
- **[P1 / SECURITY] Scrub driver's-license PII from git history** — Executed `git filter-repo --invert-paths` to remove real DL biometric photos (`460014_alyshia_mledlie_p{1,2}.png`) from history; history rewritten; verified with `git rev-list --all --objects` that blobs no longer exist. Replacement specimen generated via `scripts/generate_specimen_id.py` (fabricated data, no biometric PII).
- **Core-query export path in SchemaOrgExporter** — `SchemaOrgExporter(use_core=True)` now the default; byte-identical to ORM path; parity locked by `tests/integration/test_core_export_parity.py`; measured 3.2× faster than ORM (relationships add cost but stay far below per-object ORM hydration). Streaming exports (`export_to_file`, `export_to_ndjson`, etc.) write incrementally via `_stream_array` + lazy `_iter_records`; column-selects (no ORM File construction); peak memory now flat (~5.8 MB) regardless of file count.
- **Test set class imbalance in model evaluation** — Root cause was not sample starvation but classifier routing bugs (filename-keyword collisions, weak OCR gates). Fixed via `_ocr_document_override` and OCR-when-CLIP-weak logic; `evaluate_model.py` now supports `--min-support` and `macro_avg_supported` metric (excludes low-support classes from averages). Specimen ID coverage added via synthetic DL generator.
- **Implement Option C — demote `person` from category to relationship** — `person` no longer emitted as top-level category; all returns remapped to `personal/{subcat}`. `Person/{Name}/` is now a regenerable symlink view via `organize-files person-view` (idempotent, driven by `file→person` edges). Filesystem migration (`organize-files migrate-person`) and graph-edge attachment (`organize-files index-people`) complete; 27/33 real files attributed (5 people in Person view).
- **Person-view population** — `organize-files index-people` derives person attribution from migration manifest and writes graph edges without relocating files; filename fallback (CamelCase, resume-only, stopword-filtered) recovered 1 additional person; 8 stale rows from P1 PII scrub correctly skipped.
- **Reconcile `person` vs `personal` category convention** — Superseded by Option C implementation above; convention codified in `CLAUDE.md` Classification Priority.
- **Migrate storage timestamps to timezone-aware datetimes** — Won't do (documented rationale in backlog item). SQLite has no native tz type; flipping to aware without a read-side coercer would break SQLite/ORM comparison chains. Defer only if/when backend switches to tz-aware store (e.g. Postgres).

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
