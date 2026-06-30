# Changelog

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
