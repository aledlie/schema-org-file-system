# Changelog

## [2.3.0] - 2026-08-11

### Added

- **Near-duplicate detection: faiss index over SSCD descriptors — shipped 2026-08-10** — `organize-files find-duplicates` detects re-encoded/resized/cropped copies of the same image. Built on `facebookresearch/faiss` (MIT, brute-force `IndexFlatIP` at target scale) and self-supervised SSCD descriptors (frozen TorchScript artifact, no install needed). Read-only report (no moves, no graph writes). Residuals: (1) faiss and torch cannot coexist in-process on macOS (bundled `libomp.dylib` collision) — solved via subprocess isolation in `src/similarity/worker.py`; (2) no `reconcile` integration or scale measurement yet. 30 tests in `src/similarity/`.

- **SSCD descriptors as copy-detection input — shipped 2026-08-10** — `src/similarity/descriptors.py` implements the descriptor half of near-dupe detection. `torch.jit.load`-compatible TorchScript checkpoints (`sscd_disc_mixup.torchscript.pt`, 94 MB, ~45 ms/image). Batching requires `skew_320` transform (square 320×320); PDFs rasterized first-page-only (100 dpi). Validates against synthetic pairs at 0.998 confidence. Descriptor cache is distinct from CLIP embeddings (512-d, both `L2`-normalized); changing the transform invalidates it. HEIC support requires per-module `register_heif_opener()` call (residual blind spot, fixed after handoff). Threshold `DEFAULT_SIMILARITY_THRESHOLD=0.85` unvalidated on real data.

- **nevergrad for joint weight search in the calibration harness — shipped 2026-08-11** — `scripts/weight_search.py` / `make weight-search` optimizes the joint space of 19 priors + 2 thresholds under a fixed evaluation budget. Measured result: **searched and found nothing**. Across `NGOpt` (seeds 0/1/2), `CMA`, `TwoPointsDE` at budgets 120–250, train non-media agreement never moved off the shipped 59/164, and every best-found candidate was flat or −1 on the holdout. Read as corroboration of the 2026-07-26 calibration, not as a broken tool. Encoding: hard constraints for known invariants (`W_ORG > W_PERSON > W_LEGAL`, etc.); train/holdout split stable via `hashlib.sha1` across subprocesses (not `hash()`). 17 tests; deliberately NOT in `make calibrate` (exploratory, budget-priced).

### Fixed

- **`package.json` version stale and `test:unit` script missing — fixed 2026-08-11** — `package.json:3` declared 1.3.0 while `pyproject.toml` and `CLAUDE.md` carry 2.1.0. Fixed in `04a9ba7`: version bumped to 2.1.0 and `"test:unit": "pytest tests/unit/"` added (Playwright scripts kept as `test:e2e` family). The version field is cosmetic today but actively misleading; either sync it to source-of-truth versions or delete it.

- **HEIC never reaches OCR — decode path fixed 2026-08-11** — Both easyocr (`cv2.imread` fails on HEIC containers) and docTR (`DocumentFile.from_images` raises ValueError) read files themselves instead of using PIL's `register_heif_opener()`, so every `.heic` lost its text layer. Fixed in `e9fb0a8` + `41ee326` + `1c32fe7`: decode once via PIL (`_load_rgb`), pass ndarray to both readers. Extensions consolidated into `HEIC_HEIF_EXTENSIONS` (constants.py). 10 tests in `tests/unit/test_ocr_heic_decode.py`. Residuals: (1) recall never measured on text-bearing HEICs (gate interaction unconfirmed); (2) docTR path gated on `_PREPROCESS_AVAILABLE`, so HEIC still raises without preprocessing deps.

---
