# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-18 (added [Repo Snapshot](#repo-snapshot--2026-07-18) — repomix token census, top-churn gitlog, and the uncommitted InteriorSignal→SceneSignal retirement inventory; added identity-detection license-back item + partial fix — `corrective lenses` keyword added to `ID_KEYWORDS` (`restrictions`/`endorsements` trialed then dropped after backtest showed insurance-doc collision), front/back fixtures, 23 tests pass; added `redact_pii.py` barcode/alphabetic-PII blind-spot item — OCR-token redaction silently no-ops on ID barcodes + health terms; added trained graphic-vs-photograph probe item — opaque AI graphics/logos leak past the cheap `GraphicDetectionSignal` gate (code path since closed by `c327877` — `graphic` scene-probe class wired end-to-end, pending corpus + retrain); corrected `PHOTO_PROPERTY_CONFIDENCE` item post-f6488b9 — two-signal case resolved, residual is probe-absence only; probe now health-checked; fixed person-name false positive — ambiguous Census given names (summer/spring/autumn/winter, month names, virtue words) were auto_accepted when paired with a Census surname; new `_AMBIGUOUS_GIVEN_NAMES` hard rule + 41-test suite; closed `redact_pii.py` barcode item — cv2 barcode+QR detection, `--redact-terms` flag, `barcode_unredacted` manifest field, non-zero exit, 27-test suite).

## Open Items

### `PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin

`PhotoCompositionSignal`'s home-interior flag routes to `media/interiors_other` (folder `Media/Interiors`, schema.org `Room`) at `PHOTO_PROPERTY_CONFIDENCE(0.7) × W_PEOPLE_PHOTO(0.65) = 0.455`. The failure mode as originally filed — 0.455 vs `mime_fallback` 0.400, a 0.055 lead below `MIN_DECISION_MARGIN(0.10)` → `LOW_CONFIDENCE_FALLBACK` — **no longer exists**: the same-category margin fix (`f6488b9`, 2026-07-17) measures margin only against cross-category rivals, and both votes map to `media/*` (`interiors_other` vs `photos_other`), so the two-signal case commits cleanly (`runner_up=None`, `margin=0.455`; confirmed live 2026-07-18).

**Actual residual gap** (bug-detective, 2026-07-18): when `results/interior_probe.joblib` is absent, `PhotoCompositionSignal` is the sole interior voter at 0.455 weighted, and any **cross-category** rival scoring ≥ 0.355 (= 0.455 − 0.10) forces `low_margin` → fallback. Concrete tipping points: `ClipVisionSignal` (W 0.70) at confidence ≥ 0.507; `TextContentSignal` (W 0.80) at ≥ 0.444. Confirmed live: three-signal case with CLIP at 0.55 confidence → `low_margin`, margin 0.07.

**Status:** Done — 2026-07-18. Resolved by retirement, not re-tune (MEDIA_EXTERIORS_PLAN decision #5): `PhotoCompositionSignal` no longer votes interiors at all — its `is_property_mgmt` branch (and `PHOTO_PROPERTY_CONFIDENCE`) were removed with the SceneSignal swap completion. Interior detection is now exclusively the trained scene probe (`scene.py`, artifact committed + health-checked as `scene_probe`), so the under-committing fixed-confidence vote this item tracked no longer exists. Historical analysis below kept for the record.
**Priority:** P3
**Source:** `Media/Interiors` / schema.org `Room` folder addition, 2026-07-17; re-analyzed by bug-detective 2026-07-18; closed by SceneSignal swap completion 2026-07-18

- **Primary mitigation (implemented 2026-07-18):** keep `results/interior_probe.joblib` trained and present — `InteriorSignal` (W 0.85) contributes ~0.84 at probe P≈0.99, and the two interior votes sum ~1.30 for `media/interiors_other`, far above any tipping point. Probe availability is now reported by `organize-files health` (`interior_probe` feature): missing/unreadable artifacts surface with a retrain hint instead of silently degrading.
- **Corrected re-tune formula (if a bump is still pursued):** compute against cross-category rivals, not MIME (same-category, irrelevant since `f6488b9`). Beating `TextContentSignal` at 0.65 confidence requires `PHOTO_PROPERTY_CONFIDENCE ≥ (0.52 + 0.10) / 0.65 ≈ 0.95` — not achievable without also raising `W_PEOPLE_PHOTO`; treat any confidence bump as marginal hardening only, not a fix.
- **Do not eyeball the bump.** Per the Phase-3 calibration process (`src/scoring/weights.py` header — "treat this module as versioned data and commit each re-tune with its backtest report"), any change to `PHOTO_PROPERTY_CONFIDENCE` (or `W_PEOPLE_PHOTO`) must be backed by a `results/file_organization.db` backtest, committed with the report.
- **Regression guard:** measure false positives — staged/real-estate listing photos and any non-interior images the analyzer flags `is_property_mgmt` — before raising, since a higher confidence also strengthens every interior vote against genuine content winners.
- **Legacy parity note:** the legacy `_classify_photo_composition` still routes interiors to `property_management/other`; a unified re-tune widens the shadow legacy-vs-unified disagreement for interior photos until the legacy chain is retired (Phase 5).

### [Done] `redact_pii.py` leaks barcodes + alphabetic sensitive terms (OCR-token redaction is insufficient for IDs / health screenshots)

`scripts/redact_pii.py` rasterizes an input to a flat PNG, then `redact_raster` (`scripts/redact_pii.py:93-121`) runs docTR OCR and blacks out only the recognized **word tokens** whose text matches `is_pii_token` (`:58-65`) — i.e. `_TOKEN_PII` (`:47-55`: 3+ digit runs, emails, SSN/phone, `\d{1,2}[/-]\d{1,2}[/-]\d{2,4}` dates) or a `--name` term. Anything that is not an OCR-detected word, or is alphabetic and not a supplied name, is never considered for redaction. The module docstring warns only about alphabetic street/third-party names; the true blind spots are broader and include a class of documents (government IDs) where redaction silently fails while *appearing* to succeed.

**Symptom:** `redact_pii.py <file> --output DIR` reports `OK ... redacted` and writes a manifest flagged `review_recommended`, but the output still contains recoverable PII. The tool gives no indication which sensitive elements it could not see.

**Reproduced 2026-07-18** (seeding `results/scene_labels/neither/` from real personal files; every output visually reviewed at full res):

1. **Barcodes pass through 100% intact — the critical gap.** A Texas driver's-license back (`PXL_20220607_234355242.MP.jpg`) has a PDF417 2D barcode that encodes the *entire* identity (name, address, license #, DOB) plus a 1D Code-128 document number. docTR is a text-recognition model; it does not detect barcodes as words, so the `for word in line.words` loop (`:106`) never visits them and `redact_raster` draws zero boxes over them. The one-pass output looked "redacted" (a few digit tokens boxed) while the barcode — which round-trips to full PII via any scanner app — was completely untouched. **For any ID / passport / boarding pass / insurance card, OCR-token redaction is not a safe control.**
2. **Alphabetic sensitive terms survive.** A SNPedia variant screenshot (`Screenshot 2026-06-09 at 6.52.15 PM.png`) kept "Increased (2.5x) risk for **Graves' disease**" (×3) and the `Medical Conditions: Graves' disease` tag fully readable after redaction. `_TOKEN_PII` has no alphabetic branch, and a health condition is not a `--name` term, so `is_pii_token` returns False for every one of those words. The rsID and numeric fields *were* boxed — depersonalizing the row — but the health association (the actually-sensitive content) remained.
3. **Rotated text is missed.** The license `DOB: 01/09/1954` is printed rotated 90°. docTR's default detector did not return it as a word (orientation-sensitive), so the date branch of `_TOKEN_PII` never fired even though the string matches it. OCR-token redaction inherits every OCR recall gap (rotation, low contrast — cf. the P2 docTR-gate 1/7 faint-text miss in the OCR-bound item).

**Mitigation actually used this session:** manual second pass — `PIL.ImageDraw.rectangle` black boxes over the barcode regions / rotated DOB / disease-name text, each output re-read at full resolution to confirm zero residual PII before use. The VIN-only Edmunds screenshot (`Screenshot 2026-07-15 at 1.34.47 PM.png`, VIN = digit run) redacted cleanly in one pass — the tool is fine when *all* PII is digit/email/date shaped and axis-aligned.

**Status:** Done 2026-07-18 — barcode detection + coverage via `cv2.barcode_BarcodeDetector` + `cv2.QRCodeDetector` added to `detect_and_cover_barcodes`; `--redact-terms` flag added for alphabetic PII (health conditions, org names); manifest records `barcode_detected`/`barcode_covered`/`barcode_unredacted`; non-zero exit when a barcode is detected but not localised; 27-test suite in `tests/unit/test_redact_pii.py`. Rotated-text OCR gap and ID-shape fail-loud heuristic remain open (documented in module docstring as known limitations). **Priority:** P2 (privacy).
**Source:** manual PII-scrub of 3 files for the scene-probe `neither/` corpus, 2026-07-18. See memory `redact-pii-barcode-blindspot`.

Residual gaps (not implemented — lower value vs. complexity):
- **ID-shape fail-loud heuristic.** Aspect-ratio + keyword check for driver-license-shaped images; deferred — barcode presence already triggers the loudest warning path.
- **Rotated text.** docTR orientation detection not enabled; documented in module docstring as a known limitation.
- **Multi-word `--redact-terms`.** Each OCR token is checked independently; multi-word terms (e.g. "graves' disease") must be split into per-word entries. Documented in test comments.

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

Profiling `organize-files content` (unified scorer, dry-run) on 2026-07-17 showed the workflow is **~85% OCR-bound** (`torch.conv2d` in the easyocr CRAFT + docTR detection CNNs ≈ 67% of self-time; CLIP is negligible). This session shipped P2/P3/P5 (docTR-fallback gate, screenshot double-OCR dedup, CLIP text-embedding memoization) — conv2d call count dropped 1189→528 (−56%). Two items remain.

**Status:** Open — P1 shipped 2026-07-18 (gate on by default at K=3); P2 gate shipped (recall tradeoff to monitor).
**Priority:** P3
**Source:** content-classification profiling + P2/P3/P5 optimization session, 2026-07-17

1. **Gate OCR on text-likelihood (P1) — Done.** `OCR_CLIP_GATE_TOPK = 3` constant added to `src/scoring/weights.py`; gate enabled by default at K=3 in `ContentOrganizer`, `ContentBasedFileOrganizer`, and the CLI. Opt out with `--ocr-clip-topk 0` (or `ocr_clip_topk=None`); `FileContext._skip_ocr_by_clip_gate` treats `K=0`/`None` as disabled. Eval: K=3 → 100% text recall, ~35% of photos skip OCR. Gate fails open when CLIP is unavailable. 15 unit tests added to `tests/unit/scoring/test_context.py::TestClipOcrGate`. Reusable tooling: `scripts/profile_pipeline.py` (hot-path profiler) + `scripts/eval_ocr_gate.py` (folder-labeled gate eval).

2. **P2 docTR-fallback gate — recall tradeoff to monitor.** The shipped gate (`extract_ocr_with_confidence`: skip the docTR fallback when easyocr cleanly finds no text) was eval'd over 7 text images at varying difficulty: **1/7 recall loss — very-low-contrast text** (easyocr's detector found nothing; docTR would have caught it). Clean, dark-mode, and rotated text were all gate-safe. So P2 trades a rare miss on near-invisible text for eliminating the docTR fallback. For a screenshot/photo-dominated 265k-file library this is very likely a net win, but it is a real behavior change — put it behind a config flag or revert if faint-text recall matters.


### Content organizer misclassifies diverse/screenshot sources (review-gate + robustness gaps)

A live `organize-files content --source ~/Desktop --limit 10` (unified scorer) on mixed real-world desktop content committed most files to wrong folders and surfaced several distinct gaps. Items 2–5 shipped; item 1 remains open.

**Status:** Open — item 1 gates safe use on real user directories.
**Priority:** P2 (item 1)
**Source:** `~/Desktop` content-run audit + full rollback, 2026-07-17

1. **The review gate keys on decision-confidence, which the scene probe inflates.** (Originally filed against `InteriorSignal`; the mechanism carries over unchanged to its successor `SceneSignal` — swap completed 2026-07-18.) UI screenshots of real-estate listings committed to `Media/Interiors` (`Room`) because the interior probe votes ~0.99 (decision confidence ~0.85, margin ~0.81) even when the OCR/label confidence is 1–12%. The `low_confidence`/`low_margin` review bucket exists and *does* fire (confirmed in a `--scorer shadow` pass — one opaque PDF routed to `uncategorized/other`), but cannot catch these because the probe supplies genuine high decision-confidence to wrong content. Options: a per-signal reliability cap, or require corroboration for `SceneSignal` on screenshot-detected inputs — note the 5-class probe's trained `neither`/`graphic` classes (which include many UI screenshots as negatives) already reduce, but do not eliminate, this failure mode relative to the binary interior probe.

## Repo Snapshot — 2026-07-18

Recorded from the `npm run repomix` regeneration (`docs/repomix/`, gitignored) and `git status` on the primary checkout. Everything under "Uncommitted working tree" below is **not yet committed** — reconcile the affected open items when that work lands.

### Token census (`docs/repomix/token-tree.txt`)

- Full repo pack (`repomix.xml`) ≈ **983k tokens**; compressed ≈ 604k; git-ranked ≈ 931k; docs-only ≈ 131k.
- `src/` ~550k, but ~332k of that is one data dir — `src/classifiers/data/census_names/` (`surnames.txt` alone 315k tokens; `given_names.txt` 16k). Hand-written `src/` code is ≈ 218k.
- Other buckets: `tests/` ~252k (unit ~200k, of which `tests/unit/scoring/` signal tests ~43k), `scripts/` ~117k (`shared/` ~41k; `filename_classifier.py` 15.4k is the largest script module), `docs/` ~110k (largest single doc: `reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md` 24.2k).
- Largest source files: `organizers/content_organizer.py` 16.5k, `storage/models.py` 12.4k, `storage/graph_store.py` 12.2k, `cli.py` 8.5k, `cost_roi_calculator.py` 7.6k. Largest test: `test_content_organizer.py` 16.3k.
- `surnames.txt` added to `.gitignore` and untracked (`git rm --cached`, staged) 2026-07-18. The file stays on disk locally, but once the deletion commits, **fresh clones will lack it** — `person_name_validator` depends on it at runtime, so setup needs `scripts/download_census_names.py` (or equivalent) to materialize it.

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
- **`PHOTO_PROPERTY_CONFIDENCE` re-tune** — likely obsolete: the `PhotoCompositionSignal` interior vote it tunes was retired; interior routing is SceneSignal-only.
- **Trained graphic-vs-photograph probe** — the "data-only" gap has largely closed (graphic corpus 34 and climbing; a 5-class `scene_probe.joblib` exists untracked). The item's "do not commit an artifact without eval + backtest" guard still applies.
- **Content organizer misclassification, item 1** — re-evaluate the over-commit gap against SceneSignal; the `InteriorSignal` it names no longer exists.


