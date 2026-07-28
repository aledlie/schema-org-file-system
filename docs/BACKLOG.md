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

**Status:** Open — narrowed 2026-07-27. Corpus expanded 34 → 307 via Crello; real-world
graphic recall 0.67 → 0.76. The residual error is now a single identified subtype
(data-viz/dashboards), not general volume. See the 2026-07-27 entry at the end of this item.
**Priority:** P3
**Source:** ChatGPT shadow-scorer investigation, 2026-07-18 (`results/scoring_shadow.jsonl`; agreement-set manual review)

- **Do not chase it with more pixel heuristics.** Opaque AI-generated graphics are pixel-indistinguishable from photos by palette/size/alpha; only the learned embedding separates them.
- **Keep the cheap gate.** `GraphicDetectionSignal` correctly and cheaply catches transparent/square icon assets pre-CLIP; the probe is an *additional* heavy-tier voter for the opaque-graphic case it can't see, gated on CLIP availability with graceful no-op (same pattern as `InteriorSignal`).
- **Corpus dependency.** Needs labeled graphic/neither positives (target 150–300/class per the scene-probe README); `results/scene_labels/` is seeded and actively being labeled — a dedicated `graphic/` class dir now exists — but every class is still below target (2026-07-18 snapshot: neither 46, interior 44, exterior 21, graphic 8, place 3), so the probe is not yet trainable.
- **Regression guard.** Measure false positives on genuine photos (product still-lifes, staged interiors) before deploying — a graphic probe that over-fires would pull real photos out of `photos_*`.
- **First eval baseline (2026-07-18, `gather --label-dirs` + `eval`, 3-fold CV, n=122).** Corpus at eval time: neither 42, interior 44, exterior 21, place 3, **graphic 12**. Graphic class: **precision 1.00 / recall 0.42 / F1 0.59** — confusion row `graphic → [7 neither, 0, 0, 0, 5 graphic]` (7/12 graphics still fall back to `neither` → leak to `photos_*`, the original bug). Classic starved-minority signature: **high precision, low recall — corpus volume is the fix, not tuning.** Deploy-safety confirmed: at the default `SCENE_MIN_PROB=0.5` graphic precision holds at **1.00** across the 0.5→0.7 sweep, so a live 5-class probe would add no photo→graphics false positives (safe-but-partial: misses ~60% of graphics, no regression on them). **Headline metrics are inflated** (macro ROC-AUC 0.993 / acc 0.918): `place` n=3 is meaningless and near-duplicate images (two coffee-station photos, multiple Integrity banners) leak across CV folds — do not read as deployment-ready. **Decision: do not `train`/commit a `.joblib` yet** — an artifact activates the registry swap, and graphic recall 0.42 isn't worth shipping. Hold until `graphic/`≈150 and `place/` is real.
- **Runtime landing path — code steps done (`c327877`, 2026-07-18).** `SceneSignal` (`src/scoring/signals/scene.py`) + the artifact-gated registry swap landed in `5f6db5b`; `c327877` wired the 5th class end-to-end: `"graphic": 4` in `SCENE_CLASSES` + `_POSITIVE_NAMES` (so `gather` picks up `results/scene_labels/graphic/`), runtime mapping `SCENE_CATEGORY["graphic"] → ("media", "graphics_other")` (resolves to `Media/Graphics/Other`, the same target `GraphicDetectionSignal` emits), `SCENE_SCHEMA["graphic"] → ImageObject`, `_INT_CLASS_NAMES[4]`. Back-compat: a pre-graphic 4-class artifact still loads — `SceneSignal` ignores classes absent from `SCENE_CATEGORY`, so nothing misroutes before retraining. 16/16 scene tests pass (new test pins graphic-argmax → `media/graphics_other`).
- **Trained and shipped (2026-07-18, supersedes the "do not train yet" hold above).** Corpus was expanded the same day (Places365 sampling for place/exterior/interior + Business-folder graphics + Media-filtered `--db-neither`) to 835 rows — neither 118, interior 178, exterior 158, place 347, graphic 33 — clearing the hold's `place`-is-fake blocker. Final 5-fold eval: accuracy 0.92; graphic **P 0.73–0.82 / R 0.60–0.67 / F1 ~0.70**. User decision: **train now, accept conservative graphic recall** — the miss mode is benign (a missed graphic gets no scene vote and falls through to `GraphicDetectionSignal` + other signals, i.e. today's behavior). `scene_probe.joblib` trained + committed (`6f61449`); swap completion followed (interior.py deleted, `photo_composition` interior vote retired, `scene_probe` health feature, W_SCENE backtest: −20% flips 4 / +20% flips 0 on the 202-row replay). **Still open here: graphic recall.** Corpus volume from *pure* graphics (logos, posters, flat illustrations — local sources are tapped out; a public logo/infographic dataset is the realistic path), and a labeling-policy call on promo-panels-with-embedded-UI (semantically graphics, visually half-screenshot — currently the main graphic↔neither confusion).

- **Corpus expanded from Crello, 2026-07-27 — and the headline number is misleading.**
  `scripts/download_crello_graphics.py` pulled **273** flat-design previews from
  `cyberagent/crello` across 14 `format` subtypes (logo, poster, flyer, ad creative,
  certificate, coupon…), filtered to templates with no `ImageElement` (those embed
  photographs) and one per `cluster_index` (near-duplicate variants would leak across CV
  folds). Class went **34 → 307**, inside the 150–300 target band. Aggregate 5-fold CV:
  graphic **P 0.73 → 0.97, R 0.67 → 0.96, F1 0.70 → 0.97**; overall accuracy 0.90 → 0.93.
  **Do not read that as a 0.97.** Per-source recall: **Crello 272/273 = 0.996**,
  **hand-collected 25/33 = 0.758**. Crello templates are near-trivially separable, so
  they inflate the aggregate; the honest real-world gain is **0.67 → 0.76**.
  Images are gitignored (`graphic/crello_*`) — CyberAgent conditions use on the
  VistaCreate ToS and does not redistribute source files, so the script is the
  reproduction path (same arrangement as `download_census_names.py`).
- **The residual error is one coherent subtype, not general scarcity.** 7 of the 8 missed
  hand-collected graphics are `biz_dashboard_*` images and the 8th is an
  "AI Market Map" infographic — all flat-design **data-viz**, all routed to `neither`.
  Visually confirmed: these are non-photographic flat vector charts, so `graphic` is the
  correct label and the probe is genuinely wrong. Crello supplies posters/logos/ads and
  almost no data-viz, which is exactly why it didn't fix them. **Next increment should
  target dashboards/infographics/charts, not more posters.** InfographicVQA is the ideal
  content match but is research/education-only (blocked — see
  `~/.claude/.../memory/dataset-license-constraints.md`); **DomainNet `infograph`**
  (51,605 images, one-line TFDS pull) is the license-viable candidate, pending
  verification of DomainNet's terms at ai.bu.edu.
- **This also sharpens the promo-panel labeling call.** The dashboards are the hybrid case
  in concrete form: flat data-viz rendered inside product UI. The README's boundary rules
  currently point both ways — "data-viz → `graphic`" and "UI screenshots → `neither`".
  Enrico's published precedent (no promotional category; onboarding/value-prop panels
  labeled as functional UI) argues for `neither`; the graphic class's *purpose* — stop
  non-photographic imagery leaking to `photos_*` — argues for `graphic`. Decide and write
  it into the boundary rules, because 8 of the corpus's hardest images turn on it.
- **Encoding confound found and fixed (`scripts/normalize_scene_corpus.py`).** The corpus
  had class partly recoverable from file metadata alone: `place/` was 100% JPEG at 256px
  (Places365), hand-collected `graphic/` mostly PNG at ~1536px. A logistic regression on
  encoding metadata *only* (format, dimensions, aspect, size, bytes-per-pixel — no pixels)
  scored **0.561 vs a 0.327 majority baseline, lift +0.234**. Normalizing every class
  through one encoder (JPEG q90, longest side 256 — above CLIP's 224 input, so nothing the
  model sees is lost) cuts it to **0.411, lift +0.084**. Ablation shows the remainder is
  aspect ratio (+0.139 alone) and compressibility (+0.072); **aspect cannot reach the probe
  because CLIP center-crops to square**, and compressibility is genuine content signal
  (flat design compresses better than photographs). Re-eval on the normalized tree holds
  graphic recall at 297/306, confirming the Crello gain is content, not encoding artifact.
  Output tree is gitignored and regenerable.

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

**FIXED 2026-07-26 (`1d3b262`).** `scripts/copy_to_site.sh` no longer copies
`results/index.html` to `_site/`. The line that ran `cp results/index.html _site/`
is replaced with an explanatory warning. `_site/index.html` stays the committed
source; regenerate it with `organize-files update-site`.

**Status:** Done — fixed in `1d3b262`.
**Priority:** ~~P3~~ resolved
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

**FIXED 2026-07-26.** Identity is now `full_path`, matching
`Category.generate_canonical_id` (which already hashed `full_path`):

1. **Model** (`models.py`) — `name` lost `unique=True` (plain index), `full_path`
   gained it; `generate_canonical_id`'s parameter renamed `name` → `full_path` so
   the signature states what callers already passed.
2. **Store** (`graph_store.py`) — every lookup in `get_or_create_category` now
   keys on `full_path`: the existence check, the **parent resolution** (which
   queried `Category.name == parent_name` and could adopt an unrelated leaf as
   parent — a second latent bug), and the post-`IntegrityError` recovery. The
   handler adopts a concurrent-insert winner but otherwise **re-raises** instead
   of returning `None`.
3. **Caller** (`file_processor.py`) — a `False` from `add_file_to_category` is
   now reported instead of ignored.
4. **Migration** — `organize-files migrate-category-identity` swaps the indexes,
   realigns canonical ids, aborts (untouched) if duplicate `full_path` values
   would block UNIQUE, and reports orphaned rows. Idempotent.
5. **Backfill** — `organize-files reconcile --backfill-categories` attaches the
   missing edge derived from each file's on-disk folder via
   `build_path_to_category_map` (reversed taxonomy). Needed because a plain
   `organize-files content` re-run *cannot* repair these: a correctly-placed file
   short-circuits at `already_organized` before persistence. Entity-named folders
   (`Organization/{Name}`, `Events/{Name}`) are reported unresolved, never guessed.

Applied to the live database: all 91 taxonomy pairs now resolve (was 24 blocked),
and orphaned rows went **125 → 3** (the 3 are `Events/Burning Flipside/*`,
correctly left for manual assignment). 20 tests in
`tests/unit/test_category_identity.py`.

**Status:** Done — fixed, migrated, backfilled, tested.
**Priority:** ~~P2~~ resolved
**Source:** `~/Desktop/Uncategorized` ingestion, 2026-07-26

### DB↔filesystem provenance drift (`original_path` / `current_path` integrity)

A 2026-07-26 audit of `results/file_organization.db` (495 rows) found 50 rows whose
`current_path` no longer resolved on disk. Repairing them surfaced two distinct
integrity problems, neither of which is data loss, and both of which mislead any
future reader of the DB (including the calibration oracle in
[`docs/architecture/scoring-calibration-20260726.md`](architecture/scoring-calibration-20260726.md)).

**Status:** Mostly resolved — 7 dead rows pruned (`reconcile --prune-missing`), 42 of
the 43 reverted-run rows re-organized and healed (item 1), and the 3 category-less
`Events/Burning Flipside/` rows now resolve via the looped entity-segment strip
(item 3, 2026-07-27). Open: the `flutter_auth.txt` straggler + the 25-row staging-dir
provenance record (items 2–3).
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
   **RESOLVED 2026-07-26** by taking that option: `organize-files content --source
   ~/Desktop/Uncategorized` re-organized 42 of the 43 (the 43rd is item 3 below).
   Because `add_file` keys on `generate_id(original_path)` and the files were back at
   their original paths, all 42 rows **updated in place** — no duplicates. The sprite
   fix held: zero files routed to `game_assets/sprites`; 36 photos went to
   `media/photos_{social,other}`, the logos to `Organization/Integrity Studio`, and
   `Burning_Flipside_Map.pdf` to `Events/Burning Flipside/`.
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
3. **Residual rows the 2026-07-26 sweep deliberately left (4 rows).**
   - `flutter_auth.txt` — the 43rd reverted-run file, sitting at `~/Desktop` **root**
     rather than `~/Desktop/Uncategorized`, so it was outside the source the re-organize
     covered. Its `current_path` still claims `Documents/Business/Planning/`. One
     `organize-files content --source ~/Desktop --limit 1`-style pass (or a `reconcile`
     path repair) closes it.
   - ~~3 rows under `Events/Burning Flipside/` have **no category edge**~~
     **FIXED 2026-07-27.** Folder lookup moved to `resolve_taxonomy_folder`
     (`graph_store.py`): exact match first, then trailing segments stripped **in a
     loop** until an ancestor is in the taxonomy, so entity-named folders resolve at
     any depth (`Events/{Name}/2026/maps` → `Events`, `Media/Interiors/{Prop}/{Room}`
     → `Media/Interiors`). A parent reached *by stripping* that declares no
     subcategory is filed under the generic bucket — `Events/*` → `events/other` —
     while an exact match keeps the bare category, so a file sitting directly in
     `Events/` still reads `events`. Live dry-run: the 3 Burning Flipside rows now
     resolve `events/other`, **0 unresolved of 3 orphaned** (was 3 unresolved).
     3 new tests in `tests/unit/test_category_identity.py` (deep nesting, exact-match
     preservation) + the existing entity test updated; 224 storage/pipeline tests pass.
     **Applied to the live DB 2026-07-27** (backup `…bak-20260727_192729`): 3 edges
     attached, **category-less rows 0 of 488** — closing the orphan count 125 → 3 → 0.
     *As-intended consequence, documented in CLAUDE.md and the method docstring:* the
     pair follows the folder and nothing else, so two copies of one document in two trees
     get two individually-correct edges (`Documents/Events/Burning Flipside/…` →
     `events/other`; `Documents/Personal/Events/…_300dpi.png` → `personal/events`), and a
     category query returns a subset of the document family. That is filing, not drift —
     the backfill must not infer which copy is canonical. Likewise
     `Organization/{Name}` → `organization/vendors` follows the taxonomy's declaration of
     that folder as the vendor/partner root.

### `file_count` caches drift silently and are exported

`Category`, `Company`, `Person` and `Location` each cache a denormalized
`file_count` that the edge-mutating methods increment and decrement by hand. Any write
that bypasses those methods leaves the cache disagreeing with the association table, and
the stale number is **exported**: it becomes `fileCount` / `mentionCount` in the JSON-LD
(`build_*_jsonld` in `models.py`) and feeds the dashboard.

Found 2026-07-26: 4 categories had drifted (`game_assets/textures` stored 4 with 0 real
edges, `financial/invoices` 4 vs 6, `personal/identification` 3 vs 4, `medical/bloodtest`
6 vs 8) — all caused by that session's own raw-SQL edge repairs (the loan-screenshot
retarget and the orphan-bloodwork categorization), which inserted and deleted
`file_categories` rows directly without touching the counters. Companies/people/locations
were clean only because nothing had hand-edited their edges.

**Repair tool shipped 2026-07-26** — `GraphStore.recount_entity_file_counts` recomputed
every entity's count as the true `COUNT(association rows)`, surfaced as
`organize-files reconcile --recount-file-counts`. Applied to the live database: 4 of 188
corrected. That was a repair tool, not a guard: the counters were still maintained by hand
on every edge write, so drift could recur.

**RESOLVED 2026-07-27 by deleting the cache** — see the next item for the decision. The
recount tool and its CLI flag are gone with the column they repaired; nothing is cached,
so nothing can drift.

**Status:** Done — superseded by the derived count; the repair tool was retired with it.
**Priority:** ~~P3~~ resolved
**Source:** verification of the 2026-07-26 agent commits

### Enforce `file_count` maintenance at every edge write

`reconcile --recount-file-counts` (previous item) repairs drift after the fact. The drift
should not be possible in the first place. Today every increment/decrement is written by
hand at the call site — **12 sites across 3 modules**, with no mechanism that fails when a
new edge-writing path forgets:

- `src/storage/graph_store.py` — 9 sites: `add_file_to_category` (+1),
  `add_file_to_company` (+1), `add_file_to_person` (+1), `add_file_to_location` (+1),
  `remove_person_edge` (−1), `prune_missing_person_edges` (−1), `set_file_category` (−1),
  and `prune_missing_files` (−1 for both category and person edges).
- `src/pipeline/file_processor.py` — 1 site: the category-replacement loop in
  `_persist_to_graph_store`.
- `src/storage/migration.py` — 2 sites: the person and location backfills.

That `file_processor.py` site was added on 2026-07-26 by the edge-replacement fix, which
is the point: a brand-new edge-writing path had to remember the decrement, and nothing
would have caught it if it hadn't. The 4 drifted counts found that day came from raw-SQL
repairs, which no amount of call-site discipline can cover.

Options, roughly in order of how much they actually guarantee:

1. **SQLite triggers on the association tables** — `AFTER INSERT`/`AFTER DELETE` on
   `file_categories`/`file_companies`/`file_people`/`file_locations` adjusting the parent's
   `file_count`. The only option that also covers **raw-SQL writes**, i.e. the observed
   cause. Costs: DDL must be attached for fresh databases (`event.listens_for(table,
   "after_create")` so `Base.metadata.create_all` installs them) *and* shipped as a
   migration for existing ones, in the established hand-rolled pattern
   (cf. `category_migration.py`); SQLite-specific, so it would need revisiting if the
   store ever moves to another backend (the D1 export already targets one — see
   `scripts/d1/schema.sql`).
2. **SQLAlchemy `after_insert`/`after_delete` events** on the association tables — removes
   all 12 call sites, portable across backends, no migration. But it is blind to writes
   that bypass the ORM, so it would *not* have prevented the drift actually observed.
   Reasonable as defence-in-depth, not as the guarantee.
3. **Drop the cache; count on read** — strictly correct and deletes the whole failure
   mode. Costs a `COUNT` per read in `build_*_jsonld`, the dashboard, and
   `get_category_tree`; note `get_category_tree` was already optimized once for N+1
   queries (`f410177`), so this needs a benchmark before adopting, and `file_count` is
   part of the exported JSON-LD contract (`fileCount`/`mentionCount`).

Recommendation: (1) for the guarantee, with (3) considered first if the read cost measures
as negligible on the 265k-file target — fewer moving parts beats a trigger that has to be
migrated into every existing database.

**Acceptance:** after an arbitrary edge-mutating workload *including a raw-SQL insert and
delete*, `organize-files reconcile --recount-file-counts` reports 0 corrections. Add that
as a test alongside the existing 6 in `tests/unit/test_graph_store_reconcile.py`, and
delete the hand-maintained call sites the chosen option makes redundant.

**FIXED 2026-07-27 — option (3): the cache is gone.**

Option (2) was implemented first (`68d8304`, eight relationship-level append/remove
listeners, all 12 call sites deleted) and then superseded: its own acceptance test only
exercised ORM operations, so it passed by construction while remaining blind to the
raw-SQL writes that caused the drift. The listeners are removed.

`file_count` is now a correlated `COUNT` over the entity's association table, evaluated by
the database in the same SELECT that loads the entity
(`models._edge_count_property`, applied to all four entities via `declared_attr`).
Every read site is unchanged — `to_dict`, `build_*_jsonld`, the dashboard and the Pydantic
API surface all still read `entity.file_count`, and `fileCount`/`mentionCount` stay in the
JSON-LD. `correlate_except(assoc_table)` is required, or the subquery's FROM is correlated
away when an entity is loaded *through* the association table.

The read cost was measured, not assumed:

| | plain SELECT | + derived count |
|---|---|---|
| live DB (129 categories / 496 edges) | 0.042 ms | 0.076 ms |
| synthetic 265k target (2,000 / 265,000) **with** index | 0.633 ms | **7.2 ms** |
| synthetic 265k target **without** index | 0.596 ms | **20,510 ms** |

**The association index is load-bearing, not an optimization — 2,860× at target scale.**
`ix_file_categories_category_id` and its three siblings were declared in `models.py` but
absent from the live database, because `create_all` skips tables that already exist. So
`organize-files migrate-file-counts` creates them *and* drops the four `file_count`
columns (leaving them would keep serving stale numbers to anything reading the tables
directly). Verified on a copy of the live DB: 188/188 entities derive exactly the values
the cache held, all 185 exported counts match raw SQL, and the export path is 15.3 ms.
`scripts/d1/schema.sql` was regenerated, which also picked up three earlier model changes
nobody had regenerated (see the next item).

The acceptance criterion above is satisfied structurally rather than by a recount: a
raw-SQL insert and a raw-SQL delete are both reflected immediately, pinned by
`TestDerivedFileCount` in `tests/unit/test_graph_store_reconcile.py` (8 tests) plus 8
migration tests in `tests/unit/test_file_count_migration.py`.

**Status:** Done — cache deleted, migration shipped and verified against the live DB.
**Priority:** ~~P3~~ resolved
**Source:** follow-up to the `file_count` drift fix, 2026-07-26; resolved 2026-07-27

### `scripts/d1/schema.sql` silently drifts from the model

`scripts/d1/schema.sql` is generated from `Base.metadata` by
`scripts/d1/generate_schema.py`, and its own header says "the output file is the
authoritative D1 schema — do not hand-edit it. Edit `src/storage/models.py` instead, then
re-run this script." Nothing enforces the second half. Regenerating it on 2026-07-27 for
the `file_count` removal revealed it had been stale across **three earlier model changes**
that nobody regenerated:

- `ix_categories_full_path` was still plain and `ix_categories_name` still UNIQUE — i.e.
  the D1 schema still carried the exact index shape whose UNIQUE-on-`name` bug dropped
  category edges for 26% of rows (fixed locally 2026-07-26, never regenerated).
- `people` was missing `review_status`, `detection_confidence`, `validation_scores`,
  `validated_at` and `ix_people_review_status` (the person-validation work).
- `file_categories` was missing `signal_evidence` (UNIFIED_SCORING_PLAN §5.4).

A D1 load against that schema would have failed on the missing columns or silently
recreated the fixed UNIQUE bug in the mirror. Nothing consumes those columns today —
`workers/file-org-api` has no reference to any of them — so no live breakage resulted, but
the drift is unbounded and invisible until someone deploys.

Options: a test that regenerates into a temp file and asserts it matches the committed
copy (cheapest, catches it in CI); a pre-commit hook on `src/storage/models.py`; or
generating it at deploy time and not committing it at all. The first is the obvious fit —
the repo already has hand-rolled golden-file comparisons (`tests/unit/golden/`).

**Status:** Open — regenerated 2026-07-27, but nothing prevents the next drift.
**Priority:** P3 (no live consumer today; blocks or corrupts a future D1 deploy)
**Source:** `file_count` cache removal, 2026-07-27

### Filename rules still route images by name when content disagrees

`FilenamePatternSignal` graduates several naming traps so content evidence can outscore
them (weak-shape sprite stems, source-provenance stems, camera/scanner stems — see
`graduated_filename_confidence`). Two more traps of the same family are **not** graduated
and were observed misfiling real files during the 2026-07-26 `~/Desktop/Uncategorized`
ingestion:

1. **Person-name stems send photos to `personal/contacts`.** Four couple photos
   (`sumedh_alyshia*.jpg`) matched the shared module's "Person (Alyshia Ledlie)" rule and
   filed as `Personal/Contacts` — a folder for vCards, resumes and address records, not
   pictures of people. Visually confirmed (photobooth couple shots) and re-filed by hand
   to `media/photos_social` with their `file→person` edges kept (Option C keeps person
   attribution independent of the filing category). The classifier is unchanged, so the
   next such filename repeats it. Fix shape is known and proven: add the
   `personal/contacts` result on an **image** `schema_type` to the graduation table so
   `PhotoCompositionSignal`/`MediaHeuristicSignal`/CLIP decide, while leaving
   document-typed resumes at full confidence. Note the sibling stems that behaved
   correctly (`sumedh_teresa.jpg`, `love_sumedh.jpg`) only did so because they miss the
   curated known-person pattern — i.e. the trap fires precisely on *known* people.
2. **`stock-vector-*` / `pngtree-*` stock-asset stems.** `stock-vector-modeling-blue-red-
   four-color-minimal-icon-set.jpeg` filed as `media/photos_other` although the stem says
   it is a vector icon set (`media/graphics_*`). Lower impact than #1 — the destination is
   at least within `media/` — but the same "filename asserts the format, content never
   checked" shape.

**FIXED 2026-07-26 (`1d3b262`).** Both traps are now graduated in
`FilenamePatternSignal.run()`:

1. `("personal", "contacts")` on `ctx.is_image` files → `FILENAME_WEAK_CONFIDENCE`
   (document-typed resumes keep full confidence). 2 new tests.
2. `game_assets/sprites` on `stock-vector-*` / `pngtree-*` stems → `("media",
   "graphics_other")` at `FILENAME_WEAK_CONFIDENCE`. 2 new tests. Constant
   `_STOCK_ASSET_STEM_PREFIXES` and helper `_is_stock_asset_stem` added.

**Status:** Done — fixed in `1d3b262`; 4 new tests.
**Priority:** ~~P2/P3~~ resolved
**Source:** `~/Desktop/Uncategorized` ingestion, 2026-07-26

### Re-organizing a file does not reconcile its graph edges

Two independent gaps in `FileProcessor.organize_file` mean the graph does not converge on
the filesystem when a file is organized a second time. Both were hit during the
2026-07-26 ingestion and worked around by hand or by new tooling.

1. **`add_file_to_category` appends; it never replaces.** Re-organizing a file adds the
   new `(category, subcategory)` edge alongside every historical one, so a file can claim
   two contradictory categories at once. After the ingestion, 21 of the 43 re-organized
   rows carried both a stale June `game_assets/sprites` edge and the correct new
   `media/photos_*` edge; they were collapsed by hand via `GraphStore.set_file_category`
   (which *does* replace) using the run's own report as the authority. This matters beyond
   tidiness: `backtest_scoring._stored_pair` reads `record.categories[0]`, so a stale
   first edge silently becomes "the" stored label in the calibration oracle. **11
   multi-edge rows outside that batch remain** (verified 2026-07-26), e.g. 8 screenshots
   holding
   `game_assets/sprites` + `media/graphics_other`, the Texas license back holding
   `game_assets/sprites` + `personal/identification`, and `HOOKS_ARCHITECTURE.md` holding
   `filepath/Technical/Documentation/alyshialedlie` + `technical/architecture`. Decide
   whether a content run should replace the category edge (probably yes, with the old
   edge preserved in `signal_evidence`) or whether multi-category is legitimate and the
   oracle should stop trusting `categories[0]`.
2. **`already_organized` short-circuits before persistence.** When `physical_path ==
   dest_path` and `force` is False, `organize_file` returns at `file_processor.py:569`
   *before* `_persist_to_graph_store`, so a file that is already in the right place can
   never gain a DB row, a category edge, or updated `signal_evidence` from a re-run. That
   is why the 125 category-less rows could not be repaired by re-running the organizer and
   needed the new `organize-files reconcile --backfill-categories` instead. `--force`
   is not a workaround: it proceeds into `shutil.move(x, x)`.

**Status:** Fixed 2026-07-26 — both gaps closed in `src/pipeline/file_processor.py`:
(1) `_persist_to_graph_store` now clears all existing `file.categories` edges before
calling `add_file_to_category`, so a re-run always produces exactly one category edge;
(2) the `already_organized` branch now calls `_persist_to_graph_store` when `not dry_run
and self.graph_store`, reconciling the DB row and its edges without moving the file;
(3) `shutil.move` is now guarded by `if physical_path != dest_path` so `force=True` on
an already-placed file no longer attempts a same-source/dest move.
Four new tests in `tests/unit/test_pipeline.py` cover all three behaviours.
**Priority:** P2 (silently corrupts the calibration oracle via `categories[0]`)
**Source:** `~/Desktop/Uncategorized` ingestion + category backfill, 2026-07-26

### Persisted-text PII redaction is medical-only and best-effort

`organize-files content` redacts `files.extracted_text` and `schema_data["text"]` for
files classified `medical` (`src/analyzers/text_redaction.py`, added 2026-07-26). Two
deliberate limits are worth revisiting rather than forgetting:

1. **Category-gated, not content-gated.** `MEDICAL_TEXT_REDACTION_CATEGORIES` is
   `{"medical"}`, so a health document the scorer files elsewhere stores raw text. This
   is not hypothetical: during the medical ingestion the scorer wanted
   `personal/contacts` for 5 of the 11 files and `uncategorized` for another — only the
   folder-truth category override kept them inside the redaction gate. Consider gating on
   *detected content* (medical vocabulary / KIE field classes) rather than the winning
   category, and extending to the other sensitive categories the QUICK_START tips call out.
2. **Only numeric/email/known-name PII is masked.** Emails, digit runs of 2+, and the
   decision's detected person names are masked; alphabetic PII outside that set —
   conditions, medications, third-party names the entity detector missed — survives
   verbatim. Same known limitation as `scripts/redact_pii.py`'s raster path, and the
   reason `--no-db` remains the guidance for genomics and similar.

Also unquantified: **how many organized files are missing from the DB entirely.** The
`Medical/` audit found 12 of 17 on-disk files untracked (filed manually or by the DB-free
`name`/`type` organizers, which persist nothing by design). No census was run over the
rest of `~/Documents`, so the true coverage of the graph is unknown.

**Partially fixed 2026-07-26 (`3b90a08`).** The category gate was widened:
- `MEDICAL_TEXT_REDACTION_CATEGORIES` → `TEXT_REDACTION_CATEGORIES` (same value `{"medical"}`);
  backward-compatible alias retained.
- New `TEXT_REDACTION_SUBCATEGORY_PAIRS = {("personal", "identification"), ("personal", "records")}`.
- New `should_redact_text(category, subcategory)` helper checks both sets.
- `_persist_to_graph_store` now uses `should_redact_text` instead of the bare category check.
- 12 tests (6 new) in `tests/unit/test_text_redaction.py`.

**Still open:** content-based gating (a medical document misclassified as
`uncategorized` still stores raw text); alphabetic PII (conditions, medications) is
not masked; untracked-file census over `~/Documents` has not been run.

**Status:** Partially fixed — category pairs extended; content-based gating and alphabetic PII remain.
**Priority:** P3
**Source:** medical text-redaction work + `Medical/` folder audit, 2026-07-26

### Lint debt: pre-existing flake8 findings

`mypy` is clean repo-wide as of 2026-07-26 (`2dbc148`), but `flake8 src/ scripts/ tests/`
reports **540 findings** across the tree (config: `.flake8`, max-line-length 100,
extend-ignore E203/W503). Every finding encountered during the type pass was verified
pre-existing (checked against `git stash`), so this is long-standing debt, not new.

By code: `E111` indentation-not-a-multiple-of-four (249), `E501` long lines (151),
`F401` unused imports (44), `E402` module-import-not-at-top (21), `E128`/`E131`
continuation-line indent (22), `F841` unused locals (15), `E114`/`E302`/`W293` (23),
plus a scatter including `E741 ambiguous variable name 'l'`
(`tests/integration/test_schema_org_export_e2e.py`).

By file, the debt is concentrated — five files hold ~55% of it:
`src/api/schema_org_models.py` (162), `scripts/d1/export_to_d1.py` (49),
`src/cost_roi_calculator.py` (30), `tests/unit/test_image_metadata.py` (28),
`scripts/image_content_analyzer.py` (26).

The `E111`/`E114` bulk is 2-space-indented code that predates the project's 4-space
convention, so `black` would fix most of it mechanically — but reformatting
`schema_org_models.py` (the Pydantic API surface) and `export_to_d1.py` in one sweep is a
large diff that should land on its own, not mixed with behaviour changes. Suggested order:
run `black` over the five concentrated files, then clear `F401`/`F841` (safe deletions),
then hand-wrap the residual `E501`s. `E402` in `scripts/profile_pipeline.py` and
`file_organizer_content_based.py` is deliberate (sys.path setup precedes imports) and
should get `# noqa: E402` rather than reordering.

**Status:** Open — never started; enumerated here so the next pass has a worklist.
**Priority:** P3 (no behaviour at stake; mechanical but a large diff)
**Source:** mypy cleanup pass, 2026-07-26

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


