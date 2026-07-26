# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-25 (migrated 3 Done items to `docs/changelog/2.2.0/CHANGELOG.md`; resolved the census-gazetteer setup gap — `scripts/download_census_names.py` verified + documented in QUICK_START/CLAUDE.md; shipped the `--ocr-doctr-fallback` config flag for the P2 docTR-fallback gate, closing the OCR-bound item's last work item). Prior update 2026-07-18 (added [Repo Snapshot](#repo-snapshot--2026-07-18) — repomix token census, top-churn gitlog, and the uncommitted InteriorSignal→SceneSignal retirement inventory; added identity-detection license-back item + partial fix — `corrective lenses` keyword added to `ID_KEYWORDS` (`restrictions`/`endorsements` trialed then dropped after backtest showed insurance-doc collision), front/back fixtures, 23 tests pass; added `redact_pii.py` barcode/alphabetic-PII blind-spot item — OCR-token redaction silently no-ops on ID barcodes + health terms; added trained graphic-vs-photograph probe item — opaque AI graphics/logos leak past the cheap `GraphicDetectionSignal` gate (code path since closed by `c327877` — `graphic` scene-probe class wired end-to-end, pending corpus + retrain); corrected `PHOTO_PROPERTY_CONFIDENCE` item post-f6488b9 — two-signal case resolved, residual is probe-absence only; probe now health-checked; fixed person-name false positive — ambiguous Census given names (summer/spring/autumn/winter, month names, virtue words) were auto_accepted when paired with a Census surname; new `_AMBIGUOUS_GIVEN_NAMES` hard rule + 41-test suite; closed `redact_pii.py` barcode item — cv2 barcode+QR detection, `--redact-terms` flag, `barcode_unredacted` manifest field, non-zero exit, 27-test suite).

## Open Items

### Identity detection misses driver-license *backs* (front-side keyword list)

`IdentityDocumentSignal` / the legacy `_classify_identification_document` both delegate to `detect_identity_document` (`src/scoring/signals/identity_document.py:95`), which fires only when `ocr_text` contains one of the `ID_KEYWORDS` (`:44`). The original 14 keywords were all *front-side* terms ("passport", "driver license", "date of birth", "surname"…). A photographed **license back** carries none of them — its OCR text is class/restriction/endorsement fields plus barcodes — so it was never detected and fell through to MIME/`neither` instead of `personal/identification`.

**Surfaced 2026-07-18** while handling a real Texas license back (`PXL_20220607_234355242.MP.jpg`): OCR text was "CLASS: C-Single… / HAZMAT / REST: A - With corrective lenses / END: NONE / Directive to physician / Emergency Contact / Allergic reaction to drugs / TEXAS ROADSIDE ASSISTANCE" — zero `ID_KEYWORDS` hits. (Same file that exposed the `redact_pii.py` barcode blind spot above.)

**Partially fixed 2026-07-18:** added one license-back keyword to `ID_KEYWORDS` — `"corrective lenses"` (near-unique license restriction) — appended last so any front-side keyword still wins the reported-`matched_keyword` slot. (`"restrictions"` and `"endorsements"` were trialed then **dropped** after the backtest below showed they collide with insurance-document language; only `corrective lenses` was kept.) Two fixtures + tests added (`test_signal_identity_document.py`: `DRIVER_LICENSE_TEXT` front, `LICENSE_BACK_TEXT` back); 23 tests pass. Flows to both engines via the shared core.

**Status:** Open — partial. Residual gaps below.
**Priority:** P3
**Source:** manual license handling during scene-probe corpus seeding, 2026-07-18

- **Unrestricted backs still undetectable.** A license back with *no* restriction/endorsement (only barcodes + "NONE") has no keyword hook at all — OCR-keyword detection fundamentally can't see it. Robust license-back detection needs a **barcode/PDF417 presence cue** (cf. the `redact_pii.py` item — a PDF417 is itself a strong ID signal) or a trained ID-image probe, not more keywords.
- **`"restrictions"` / `"endorsements"` trialed and dropped (backtest 2026-07-18).** Both are generic enough to appear on insurance/contract/benefits documents and would file to `personal/identification` at `ID_KEYWORD_CONFIDENCE(0.85)`. Backtest (`results/file_organization.db`, 237 files / 58 with OCR): `corrective lenses` 0 matches, `restrictions` 0 matches, `endorsements` 2 matches — **both insurance PDFs** (`My Documents _ USAA.pdf`, `Property_Insurance.pdf`, "Declarations Page and endorsements…"), i.e. the exact collision predicted. No live false positive only because both are `DigitalDocument` and the ID signal is image-only gated (`applies_to: is_image`) — incidental protection that fails for a *photographed* insurance card. **Decision: dropped both; kept only `corrective lenses`** (clean, ID-specific, 0 collisions). If broader license-back coverage is later needed, reintroduce behind a corroborating-token requirement rather than as bare keywords. Corpus is small (spot-check, not comprehensive).
- **`ID_KEYWORDS` is now front+back mixed.** If the reported `matched_keyword` is ever used to sub-classify (front vs back), the flat list won't distinguish them — would need tagging.

### Trained graphic-vs-photograph probe (opaque full-bleed graphics leak to `photos_*`)

`GraphicDetectionSignal` (`src/scoring/signals/graphic_detection.py`) is a cheap pre-CLIP pixel gate tuned for **transparent, small, square icon assets**: its four additive heuristics are `has_alpha` (+0.40), `is_square_icon` (square & ≤512px, +0.30), `small_palette` (≤64 colors in a 64² thumbnail, +0.25), and `asset_path` (parent dir in the asset-folder set, +0.15), needing ≥ `_MIN_RASTER_CONFIDENCE(0.35)` to vote. It has **no capability for opaque, high-res, flat-design graphics** — logos on a solid background and text marketing posters, exactly what ChatGPT/AI image tools emit. Those score ≈ 0 on all four cues (no alpha, >512px, anti-aliased gradients/text push distinct colors >64, parent folder is `ChatGPT` not an asset dir), fall below 0.35, and leak through to the `photos_chatgpt` filename fallback (or `photos_other`).

**Reproduced (shadow run, 2026-07-18)** on `~/Documents/Media/Photos/ChatGPT`, visually verified:
- `ChatGPTImageNov10,2025,02_32_53PM.png` — "InventoryAI" brand logo (1024², opaque navy) → misfiled `photos_chatgpt` (both engines agreed; both wrong).
- `ChatGPTImageAug30,2025,03_41_57PM.png` — "GOT A VISION FOR A HEALTHIER AUSTIN?" text poster (1536×1024, opaque cream) → misfiled `photos_chatgpt`.
- Contrast: `ChatGPTImageNov10,2025,02_32_56PM.png` (busy 2×2 icon grid) *did* route to `graphics_other` — so detection currently fires only on busy multi-icon layouts, not single logos or text posters. Inconsistent by construction.

The durable fix mirrors the interior-detection precedent (`docs/reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md`): replace/augment the pixel heuristics with a **trained linear probe over the frozen `ViT-B-32` embeddings the pipeline already caches** — a `graphic` (or binary graphic-vs-photograph) class — exactly as `InteriorSignal` (`src/scoring/signals/interior.py`, `results/interior_probe.joblib`) did for the zero-shot interior gate. CLIP embeddings *do* separate graphics from photographs even though CLIP zero-shot labels don't (the whole reason `GraphicDetectionSignal` avoided CLIP). Landing chosen and shipped: a dedicated `graphic` class (index 4) in the scene probe (`scripts/prototype_scene_probe.py`, corpus `results/scene_labels/`) — see the runtime bullet below; the logo + poster above are ideal `graphic/` positives (boundary rules: `results/scene_labels/README.md`, graphic-vs-photograph split added `38ddfd5`).

**Status:** Open — code path complete (`c327877`, 2026-07-18): `graphic` is wired end-to-end as the 5th scene-probe class, inert until a 5-class `scene_probe.joblib` is trained and committed. Remaining work is data-only (corpus labeling + retrain). Cheap gate stays as a fast-path for true icon assets.
**Priority:** P3
**Source:** ChatGPT shadow-scorer investigation, 2026-07-18 (`results/scoring_shadow.jsonl`; agreement-set manual review)

- **Do not chase it with more pixel heuristics.** Opaque AI-generated graphics are pixel-indistinguishable from photos by palette/size/alpha; only the learned embedding separates them.
- **Keep the cheap gate.** `GraphicDetectionSignal` correctly and cheaply catches transparent/square icon assets pre-CLIP; the probe is an *additional* heavy-tier voter for the opaque-graphic case it can't see, gated on CLIP availability with graceful no-op (same pattern as `InteriorSignal`).
- **Corpus dependency.** Needs labeled graphic/neither positives (target 150–300/class per the scene-probe README); `results/scene_labels/` is seeded and actively being labeled — a dedicated `graphic/` class dir now exists — but every class is still below target (2026-07-18 snapshot: neither 46, interior 44, exterior 21, graphic 8, place 3), so the probe is not yet trainable.
- **Regression guard.** Measure false positives on genuine photos (product still-lifes, staged interiors) before deploying — a graphic probe that over-fires would pull real photos out of `photos_*`.
- **First eval baseline (2026-07-18, `gather --label-dirs` + `eval`, 3-fold CV, n=122).** Corpus at eval time: neither 42, interior 44, exterior 21, place 3, **graphic 12**. Graphic class: **precision 1.00 / recall 0.42 / F1 0.59** — confusion row `graphic → [7 neither, 0, 0, 0, 5 graphic]` (7/12 graphics still fall back to `neither` → leak to `photos_*`, the original bug). Classic starved-minority signature: **high precision, low recall — corpus volume is the fix, not tuning.** Deploy-safety confirmed: at the default `SCENE_MIN_PROB=0.5` graphic precision holds at **1.00** across the 0.5→0.7 sweep, so a live 5-class probe would add no photo→graphics false positives (safe-but-partial: misses ~60% of graphics, no regression on them). **Headline metrics are inflated** (macro ROC-AUC 0.993 / acc 0.918): `place` n=3 is meaningless and near-duplicate images (two coffee-station photos, multiple Integrity banners) leak across CV folds — do not read as deployment-ready. **Decision: do not `train`/commit a `.joblib` yet** — an artifact activates the registry swap, and graphic recall 0.42 isn't worth shipping. Hold until `graphic/`≈150 and `place/` is real.
- **Runtime landing path — code steps done (`c327877`, 2026-07-18).** `SceneSignal` (`src/scoring/signals/scene.py`) + the artifact-gated registry swap landed in `5f6db5b`; `c327877` wired the 5th class end-to-end: `"graphic": 4` in `SCENE_CLASSES` + `_POSITIVE_NAMES` (so `gather` picks up `results/scene_labels/graphic/`), runtime mapping `SCENE_CATEGORY["graphic"] → ("media", "graphics_other")` (resolves to `Media/Graphics/Other`, the same target `GraphicDetectionSignal` emits), `SCENE_SCHEMA["graphic"] → ImageObject`, `_INT_CLASS_NAMES[4]`. Back-compat: a pre-graphic 4-class artifact still loads — `SceneSignal` ignores classes absent from `SCENE_CATEGORY`, so nothing misroutes before retraining. 16/16 scene tests pass (new test pins graphic-argmax → `media/graphics_other`).
- **Trained and shipped (2026-07-18, supersedes the "do not train yet" hold above).** Corpus was expanded the same day (Places365 sampling for place/exterior/interior + Business-folder graphics + Media-filtered `--db-neither`) to 835 rows — neither 118, interior 178, exterior 158, place 347, graphic 33 — clearing the hold's `place`-is-fake blocker. Final 5-fold eval: accuracy 0.92; graphic **P 0.73–0.82 / R 0.60–0.67 / F1 ~0.70**. User decision: **train now, accept conservative graphic recall** — the miss mode is benign (a missed graphic gets no scene vote and falls through to `GraphicDetectionSignal` + other signals, i.e. today's behavior). `scene_probe.joblib` trained + committed (`6f61449`); swap completion followed (interior.py deleted, `photo_composition` interior vote retired, `scene_probe` health feature, W_SCENE backtest: −20% flips 4 / +20% flips 0 on the 202-row replay). **Still open here: graphic recall.** Corpus volume from *pure* graphics (logos, posters, flat illustrations — local sources are tapped out; a public logo/infographic dataset is the realistic path), and a labeling-policy call on promo-panels-with-embedded-UI (semantically graphics, visually half-screenshot — currently the main graphic↔neither confusion).

### Content pipeline is OCR-bound (gate OCR on text-likelihood)

Profiling `organize-files content` (unified scorer, dry-run) on 2026-07-17 showed the workflow is **~85% OCR-bound** (`torch.conv2d` in the easyocr CRAFT + docTR detection CNNs ≈ 67% of self-time; CLIP is negligible). This session shipped P2/P3/P5 (docTR-fallback gate, screenshot double-OCR dedup, CLIP text-embedding memoization) — conv2d call count dropped 1189→528 (−56%). All planned work items are shipped; the item stays listed only to monitor the P2 gate's faint-text recall tradeoff in live use.

**Status:** Done pending monitoring — P1 shipped 2026-07-18 (gate on by default at K=3); P2 gate shipped, and its escape hatch (`--ocr-doctr-fallback`) shipped 2026-07-25. Remaining: watch for faint-text misses in live runs; no code work open.
**Priority:** P3
**Source:** content-classification profiling + P2/P3/P5 optimization session, 2026-07-17

1. **Gate OCR on text-likelihood (P1) — Done.** `OCR_CLIP_GATE_TOPK = 3` constant added to `src/scoring/weights.py`; gate enabled by default at K=3 in `ContentOrganizer`, `ContentBasedFileOrganizer`, and the CLI. Opt out with `--ocr-clip-topk 0` (or `ocr_clip_topk=None`); `FileContext._skip_ocr_by_clip_gate` treats `K=0`/`None` as disabled. Eval: K=3 → 100% text recall, ~35% of photos skip OCR. Gate fails open when CLIP is unavailable. 15 unit tests added to `tests/unit/scoring/test_context.py::TestClipOcrGate`. Reusable tooling: `scripts/profile_pipeline.py` (hot-path profiler) + `scripts/eval_ocr_gate.py` (folder-labeled gate eval).

2. **P2 docTR-fallback gate — recall tradeoff to monitor.** The shipped gate (`extract_ocr_with_confidence`: skip the docTR fallback when easyocr cleanly finds no text) was eval'd over 7 text images at varying difficulty: **1/7 recall loss — very-low-contrast text** (easyocr's detector found nothing; docTR would have caught it). Clean, dark-mode, and rotated text were all gate-safe. So P2 trades a rare miss on near-invisible text for eliminating the docTR fallback. For a screenshot/photo-dominated 265k-file library this is very likely a net win, but it is a real behavior change — put it behind a config flag or revert if faint-text recall matters. **Config flag shipped 2026-07-25:** `--ocr-doctr-fallback` (store_true, default off = gate on; constant `OCR_FORCE_DOCTR_FALLBACK` in `src/scoring/weights.py`) forces the docTR pass after a clean easyocr negative. Plumbed `force_doctr_fallback` through `extract_ocr_with_confidence`, `TextExtractor`, `ContentOrganizer` (all 3 call sites incl. the FileContext `ocr_provider`), `ContentBasedFileOrganizer`, `ContentInputs`, and the CLI — same pattern as `--ocr-clip-topk`. 5 gate tests in `tests/unit/test_shared.py::TestDoctrFallbackGate`; CLI-inputs contract + integration suites pass.


### `copy_to_site.sh` clobbers `_site/index.html` with a stale `results/` copy

Every `organize-files content` run ends with "✓ Updated _site directory with latest
HTML files", which runs `scripts/copy_to_site.sh` → `cp results/index.html
_site/index.html` (line 23). `results/index.html` is an older snapshot, so the copy
**silently deletes newer dashboard content**. Observed 2026-07-26: a content run
removed the "Residence Galleries" feature card (13 lines) from `_site/index.html`
while `_site/residence_gallery.html` itself still existed — i.e. the page was
orphaned from navigation. Reverted by hand (`git checkout -- _site/index.html`).

The copy direction is backwards for `index.html`: `_site/` is the maintained
artifact (committed, e.g. `7ef99a5`), `results/` is scratch output. Either stop
copying `index.html` at all, regenerate it from the same source that produces the
`_site` version, or make the copy additive. Until then, check
`git diff _site/` after any content run.

**Status:** Open — observed and reverted; root cause identified, not fixed.
**Priority:** P3 (cosmetic/navigation; no data affected, caught by `git diff`)
**Source:** `~/Desktop/Uncategorized` ingestion, 2026-07-26

### `categories.name` UNIQUE silently drops category edges for 26% of files

`categories.name` carries a **UNIQUE index** (`ix_categories_name`), but
`CONTENT_CATEGORY_PATHS` reuses leaf names across parents — `other` appears under
**15** different categories, plus `records` (3), `events`, `insurance`, `photos`,
`clients`, `audio`, `web`, `meeting_notes` (2 each). Only the first row to claim a
leaf name can exist; every later `(category, subcategory)` sharing that leaf hits
an `IntegrityError` in `get_or_create_category`, whose handler rolls back and
returns `session.query(...).filter(full_path == ...).first()` — **`None`**, because
the row that owns the name has a *different* `full_path`. `add_file_to_category`
then hits `if category is None: return False` (`graph_store.py:405`) and the caller
in `_persist_to_graph_store` never checks the return value, so **the file is
persisted with no category edge at all and nothing is logged**.

Measured 2026-07-26: **125 of 488 file rows (26%) have zero category edges** while
being physically organized correctly on disk. They are invisible to category
queries, the dashboard category breakdown, category edges in the JSON-LD export,
and the backtest oracle (`_stored_pair` returns `(None, None)`, so they are skipped
from agreement entirely). 24 taxonomy pairs are currently unsatisfiable, including
`medical/other`, `technical/other`, `personal/legal`, `personal/records`,
`financial/insurance`, `education/research`, `media/photos`, and `zouk/events`.

Two concrete instances already hit this session: `Burning_Flipside_Map.pdf`
organized to `Events/Burning Flipside/` on disk but kept a stale
`legal/real_estate` edge because `events/other` could not be created; and two
bloodwork PDFs found with `cats: None` during the medical audit.

**Fix direction (needs a decision, not yet chosen):** category identity should be
`full_path`, not `name` — either drop `ix_categories_name` in favour of a UNIQUE
index on `full_path` (matching `generate_canonical_id`, which already hashes
`full_path` — see [[category-canonical-id-scheme]]), or store namespaced names.
Either way `get_or_create_category` should stop swallowing the collision, and
`_persist_to_graph_store` should treat a `False` return from
`add_file_to_category` as an error rather than ignoring it. A re-categorization
pass can then backfill the 125 orphaned rows without touching any file.

**Status:** Open — diagnosed, not fixed. No file data is affected; only graph edges.
**Priority:** P2 (silent data-integrity loss; recoverable by backfill once fixed)
**Source:** `~/Desktop/Uncategorized` ingestion, 2026-07-26

### DB↔filesystem provenance drift (`original_path` / `current_path` integrity)

A 2026-07-26 audit of `results/file_organization.db` (495 rows) found 50 rows whose
`current_path` no longer resolved on disk. Repairing them surfaced two distinct
integrity problems, neither of which is data loss, and both of which mislead any
future reader of the DB (including the calibration oracle in
[`docs/architecture/scoring-calibration-20260726.md`](architecture/scoring-calibration-20260726.md)).

**Status:** Open — 7 genuinely-dead rows pruned 2026-07-26 (`reconcile --prune-missing`);
the 43-row reverted-run set and the 25-row staging-dir set are documented here, untouched.
**Priority:** P3
**Source:** DB path audit, 2026-07-26 (same session as the sprite naming-trap fix)

1. **Reverted organize run leaves rows claiming destinations that never persisted (43 rows).**
   A batch run on **2026-06-27 04:07:41** moved 43 files from `~/Desktop/Uncategorized`
   (42) and `~/Desktop` (1) into `~/Documents/...`, persisted them with
   `status=ORGANIZED`, and the moves were later **reverted** — the files are back at
   their `original_path` and byte-size identical to their DB records (43/43 verified),
   while every `current_path` points at a Documents path that does not exist.
   Persistence is gated on `if not dry_run` (`file_processor.py`), so this is *not* a
   dry-run artifact: the moves really happened and were undone afterwards.
   `GraphStore.prune_missing_files` correctly refuses to touch these (it requires
   *both* paths gone), so they survive every prune and permanently misreport where
   those 43 files live. Options when someone picks this up: repair
   `current_path` → `original_path` (record reality, and revisit `status`), or re-run
   `organize-files content` over `~/Desktop/Uncategorized` so the rows become true.
   The latter is attractive because these 43 are exactly the corpus that motivated the
   weak-shape sprite fix — 19 of them are photos the DB still labels
   `game_assets/sprites`, which the fixed classifier now routes to `media/photos_*`.
2. **Agent temp-staging dirs must never be the organize source (25 rows).**
   25 rows record `original_path` inside
   `~/.claude/jobs/e184540b/tmp/interior_apply_stage/` — an agent job's temp staging
   directory, which still exists but is empty. 23 of the 25 files are fine on disk;
   2 were among 6 unrecoverable `Media/Interiors` renders pruned on 2026-07-26. For
   all 25 the recorded provenance is an ephemeral path, and the true pre-staging
   origin is unrecoverable, so there is no honest repair — only this rule: **an agent
   run must not organize files out of a temp/staging dir into the production graph
   store**, because `original_path` then permanently records a path that ceases to
   exist and provenance is destroyed. Stage into a durable location, or organize from
   the user's real source directory.

## Repo Snapshot — 2026-07-18

Recorded from the `npm run repomix` regeneration (`docs/repomix/`, gitignored) and `git status` on the primary checkout. Everything under "Uncommitted working tree" below is **not yet committed** — reconcile the affected open items when that work lands.

### Token census (`docs/repomix/token-tree.txt`)

- Full repo pack (`repomix.xml`) ≈ **983k tokens**; compressed ≈ 604k; git-ranked ≈ 931k; docs-only ≈ 131k.
- `src/` ~550k, but ~332k of that is one data dir — `src/classifiers/data/census_names/` (`surnames.txt` alone 315k tokens; `given_names.txt` 16k). Hand-written `src/` code is ≈ 218k.
- Other buckets: `tests/` ~252k (unit ~200k, of which `tests/unit/scoring/` signal tests ~43k), `scripts/` ~117k (`shared/` ~41k; `filename_classifier.py` 15.4k is the largest script module), `docs/` ~110k (largest single doc: `reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md` 24.2k).
- Largest source files: `organizers/content_organizer.py` 16.5k, `storage/models.py` 12.4k, `storage/graph_store.py` 12.2k, `cli.py` 8.5k, `cost_roi_calculator.py` 7.6k. Largest test: `test_content_organizer.py` 16.3k.
- `surnames.txt` added to `.gitignore` and untracked (`git rm --cached`, staged) 2026-07-18. The file stays on disk locally, but once the deletion commits, **fresh clones will lack it** — `person_name_validator` depends on it at runtime, so setup needs `scripts/download_census_names.py` (or equivalent) to materialize it. **Resolved 2026-07-25:** the script exists and is committed (`e50ae06`), documented in QUICK_START.md §1 and the CLAUDE.md Quick Start, and verified to reproduce the shipped gazetteer exactly (162,254 Census rows → 92,357 surnames at `SURNAME_MIN_COUNT=200`; the script's stale "~25k" comment was corrected). `person_name_validator` degrades gracefully when the file is absent (`_load_gazetteer` → None) and `organize-files health` reports the `gazetteer` layer.

### Top-churn git history (`docs/repomix/gitlog-top20.txt`)

- `6f61449` (2026-07-18) — added 16 images to `results/scene_labels/graphic/` (graphic-class corpus labeling for the scene probe; see the graphic-probe item).
- `eceb166` (2026-07-17) — touched `census_names/surnames.txt`; `5f7f563` (2026-07-01) — removed a license image (biometric PII) from `results/test_set_augmentation/`.
- Six older commits (2025-12 → 2026-02) are all `_site/` dashboard churn (`metadata.json` regenerations, `metadata_viewer_backup.html` a11y fix).
- Note: both 2026-07 `refactor:` commits are auto-typed wrong — they are data/corpus changes, not refactors.

### Uncommitted working tree — InteriorSignal → SceneSignal retirement in flight

`git status` 2026-07-18: 10 modified + 2 staged deletions (12 files, +373/−508):

- **Deleted (staged):** `src/scoring/signals/interior.py`, `tests/unit/scoring/test_signal_interior.py` — `InteriorSignal` retired. `SceneSignal` already registers unconditionally in committed `registry.py` (no-ops when the artifact is absent).
- `scripts/backtest_scoring.py` — the artifact-gated `SceneSignal`/`InteriorSignal` sweep-row swap collapsed to a plain `("W_SCENE", W_SCENE, "scene")` row.
- `src/health_check.py` + `tests/unit/test_health_check.py` — `interior_probe` health feature replaced by `scene_probe` (checks `results/scene_probe.joblib`; retrain hint now points at `prototype_scene_probe.py`).
- `src/pipeline/file_processor.py` + `tests/unit/test_pipeline.py` — `_IMAGE_SCHEMA_TYPES` widened to every SceneSignal @type (`House`, `Place`, `Accommodation` join the Room family) so scene photos keep image metadata instead of falling through to `DigitalDocument`.
- `tests/unit/scoring/test_signal_photo_composition.py` — records that `PhotoCompositionSignal`'s interior (`is_property_mgmt`) vote was **retired 2026-07-18**; interior detection now belongs to SceneSignal exclusively.
- `tests/unit/scoring/test_registry.py` — `TestSceneSwap` replaced by `TestSceneSlot` (unconditional registration; artifact pinned absent for hermeticity only).
- Also touched: `src/organizers/content_organizer.py` (formatting only), `tests/unit/test_content_organizer.py`, `tests/unit/scoring/test_signal_scene.py`.

**On disk but untracked:** `results/scene_probe.joblib` (34k, trained 2026-07-18 18:37). Scene-label corpus is far past the counts recorded in the graphic-probe item: interior 178, exterior 158, place 347, neither 73, graphic 34 (item snapshot was 44/21/3/46/8–12).

**Open items affected when this lands:**
- **Trained graphic-vs-photograph probe** — the "data-only" gap has largely closed (graphic corpus 34 and climbing; a 5-class `scene_probe.joblib` exists untracked). The item's "do not commit an artifact without eval + backtest" guard still applies.


