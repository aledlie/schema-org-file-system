# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-18 (added identity-detection license-back item + partial fix — `corrective lenses` keyword added to `ID_KEYWORDS` (`restrictions`/`endorsements` trialed then dropped after backtest showed insurance-doc collision), front/back fixtures, 23 tests pass; added `redact_pii.py` barcode/alphabetic-PII blind-spot item — OCR-token redaction silently no-ops on ID barcodes + health terms; added trained graphic-vs-photograph probe item — opaque AI graphics/logos leak past the cheap `GraphicDetectionSignal` gate; corrected `PHOTO_PROPERTY_CONFIDENCE` item post-f6488b9 — two-signal case resolved, residual is probe-absence only; probe now health-checked; fixed person-name false positive — ambiguous Census given names (summer/spring/autumn/winter, month names, virtue words) were auto_accepted when paired with a Census surname; new `_AMBIGUOUS_GIVEN_NAMES` hard rule + 41-test suite).

## Open Items

### Wikidata SPARQL for non-person entity typing

**Status:** Done — 2026-07-18. Implemented `src/storage/wikidata_enricher.py` (W3C Reconciliation API v0.2 client with SQLite KV cache), `scripts/enrich_wikidata.py` (nightly batch script), `src/storage/wikidata_migration.py` (adds `companies.wikidata_qid` physical column), and `organize-files migrate-wikidata` / `organize-files enrich-wikidata` CLI commands. Company.generate_wikidata_url(qid) fixed (was returning a broken name-derived URL). 22 unit tests added. Core pipeline unchanged — enrichment is opt-in nightly-only. Phase 2 remaining: wire QID into JSON-LD sameAs output (requires surfacing KV cache data through build_company_jsonld or adding an ORM migration path).
**Priority:** P3
**Source:** gap-2 web research session, 2026-07-13

### `PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin

`PhotoCompositionSignal`'s home-interior flag routes to `media/interiors_other` (folder `Media/Interiors`, schema.org `Room`) at `PHOTO_PROPERTY_CONFIDENCE(0.7) × W_PEOPLE_PHOTO(0.65) = 0.455`. The failure mode as originally filed — 0.455 vs `mime_fallback` 0.400, a 0.055 lead below `MIN_DECISION_MARGIN(0.10)` → `LOW_CONFIDENCE_FALLBACK` — **no longer exists**: the same-category margin fix (`f6488b9`, 2026-07-17) measures margin only against cross-category rivals, and both votes map to `media/*` (`interiors_other` vs `photos_other`), so the two-signal case commits cleanly (`runner_up=None`, `margin=0.455`; confirmed live 2026-07-18).

**Actual residual gap** (bug-detective, 2026-07-18): when `results/interior_probe.joblib` is absent, `PhotoCompositionSignal` is the sole interior voter at 0.455 weighted, and any **cross-category** rival scoring ≥ 0.355 (= 0.455 − 0.10) forces `low_margin` → fallback. Concrete tipping points: `ClipVisionSignal` (W 0.70) at confidence ≥ 0.507; `TextContentSignal` (W 0.80) at ≥ 0.444. Confirmed live: three-signal case with CLIP at 0.55 confidence → `low_margin`, margin 0.07.

**Status:** Open (narrowed 2026-07-18) — only reachable when the interior-probe artifact is absent.
**Priority:** P3
**Source:** `Media/Interiors` / schema.org `Room` folder addition, 2026-07-17; re-analyzed by bug-detective 2026-07-18

- **Primary mitigation (implemented 2026-07-18):** keep `results/interior_probe.joblib` trained and present — `InteriorSignal` (W 0.85) contributes ~0.84 at probe P≈0.99, and the two interior votes sum ~1.30 for `media/interiors_other`, far above any tipping point. Probe availability is now reported by `organize-files health` (`interior_probe` feature): missing/unreadable artifacts surface with a retrain hint instead of silently degrading.
- **Corrected re-tune formula (if a bump is still pursued):** compute against cross-category rivals, not MIME (same-category, irrelevant since `f6488b9`). Beating `TextContentSignal` at 0.65 confidence requires `PHOTO_PROPERTY_CONFIDENCE ≥ (0.52 + 0.10) / 0.65 ≈ 0.95` — not achievable without also raising `W_PEOPLE_PHOTO`; treat any confidence bump as marginal hardening only, not a fix.
- **Do not eyeball the bump.** Per the Phase-3 calibration process (`src/scoring/weights.py` header — "treat this module as versioned data and commit each re-tune with its backtest report"), any change to `PHOTO_PROPERTY_CONFIDENCE` (or `W_PEOPLE_PHOTO`) must be backed by a `results/file_organization.db` backtest, committed with the report.
- **Regression guard:** measure false positives — staged/real-estate listing photos and any non-interior images the analyzer flags `is_property_mgmt` — before raising, since a higher confidence also strengthens every interior vote against genuine content winners.
- **Legacy parity note:** the legacy `_classify_photo_composition` still routes interiors to `property_management/other`; a unified re-tune widens the shadow legacy-vs-unified disagreement for interior photos until the legacy chain is retired (Phase 5).

### `redact_pii.py` leaks barcodes + alphabetic sensitive terms (OCR-token redaction is insufficient for IDs / health screenshots)

`scripts/redact_pii.py` rasterizes an input to a flat PNG, then `redact_raster` (`scripts/redact_pii.py:93-121`) runs docTR OCR and blacks out only the recognized **word tokens** whose text matches `is_pii_token` (`:58-65`) — i.e. `_TOKEN_PII` (`:47-55`: 3+ digit runs, emails, SSN/phone, `\d{1,2}[/-]\d{1,2}[/-]\d{2,4}` dates) or a `--name` term. Anything that is not an OCR-detected word, or is alphabetic and not a supplied name, is never considered for redaction. The module docstring warns only about alphabetic street/third-party names; the true blind spots are broader and include a class of documents (government IDs) where redaction silently fails while *appearing* to succeed.

**Symptom:** `redact_pii.py <file> --output DIR` reports `OK ... redacted` and writes a manifest flagged `review_recommended`, but the output still contains recoverable PII. The tool gives no indication which sensitive elements it could not see.

**Reproduced 2026-07-18** (seeding `results/scene_labels/neither/` from real personal files; every output visually reviewed at full res):

1. **Barcodes pass through 100% intact — the critical gap.** A Texas driver's-license back (`PXL_20220607_234355242.MP.jpg`) has a PDF417 2D barcode that encodes the *entire* identity (name, address, license #, DOB) plus a 1D Code-128 document number. docTR is a text-recognition model; it does not detect barcodes as words, so the `for word in line.words` loop (`:106`) never visits them and `redact_raster` draws zero boxes over them. The one-pass output looked "redacted" (a few digit tokens boxed) while the barcode — which round-trips to full PII via any scanner app — was completely untouched. **For any ID / passport / boarding pass / insurance card, OCR-token redaction is not a safe control.**
2. **Alphabetic sensitive terms survive.** A SNPedia variant screenshot (`Screenshot 2026-06-09 at 6.52.15 PM.png`) kept "Increased (2.5x) risk for **Graves' disease**" (×3) and the `Medical Conditions: Graves' disease` tag fully readable after redaction. `_TOKEN_PII` has no alphabetic branch, and a health condition is not a `--name` term, so `is_pii_token` returns False for every one of those words. The rsID and numeric fields *were* boxed — depersonalizing the row — but the health association (the actually-sensitive content) remained.
3. **Rotated text is missed.** The license `DOB: 01/09/1954` is printed rotated 90°. docTR's default detector did not return it as a word (orientation-sensitive), so the date branch of `_TOKEN_PII` never fired even though the string matches it. OCR-token redaction inherits every OCR recall gap (rotation, low contrast — cf. the P2 docTR-gate 1/7 faint-text miss in the OCR-bound item).

**Mitigation actually used this session:** manual second pass — `PIL.ImageDraw.rectangle` black boxes over the barcode regions / rotated DOB / disease-name text, each output re-read at full resolution to confirm zero residual PII before use. The VIN-only Edmunds screenshot (`Screenshot 2026-07-15 at 1.34.47 PM.png`, VIN = digit run) redacted cleanly in one pass — the tool is fine when *all* PII is digit/email/date shaped and axis-aligned.

**Status:** Open — real data-loss-of-privacy risk; the tool's "OK redacted" + git-add gate implies more safety than it delivers on IDs/health images.
**Priority:** P2 (privacy) — a redaction tool that silently no-ops on a driver's-license barcode is worse than no tool, because it manufactures false confidence before `git add`.
**Source:** manual PII-scrub of 3 files for the scene-probe `neither/` corpus, 2026-07-18. See memory `redact-pii-barcode-blindspot`.

- **Barcode detection + full-cover.** Before/after OCR, run a barcode locator (e.g. `pyzbar`/`zxing`, or OpenCV `BarcodeDetector`) and black out every detected symbol's bounding box. If a barcode is detected but cannot be localized precisely, fail loud (non-zero exit + manifest `barcode_unredacted: true`) rather than emit a "redacted" file.
- **Fail-loud for high-risk documents.** When the flattened image is ID-shaped (aspect ~1.6, detected "DL"/"USA"/state keywords, or any barcode present), refuse to mark the output clean without a human-confirmed manual pass — don't just append to the `review_recommended` list that callers ignore.
- **Alphabetic PII pass.** Optional NER (or a `--redact-terms` medical/condition list) so health conditions and org/third-party names can be caught without hand-typing each into `--name`.
- **OCR recall hardening.** Enable docTR orientation handling / multi-rotation passes so rotated fields (DOB) are detected; document that low-contrast text can still be missed.
- **Regression guard / self-test.** Add a fixture ID image with a known barcode + rotated DOB and assert the redacted output fails a barcode-decode and an OCR-of-DOB check — locks the fix and prevents silent regressions.

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

The durable fix mirrors the interior-detection precedent (`docs/reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md`): replace/augment the pixel heuristics with a **trained linear probe over the frozen `ViT-B-32` embeddings the pipeline already caches** — a `graphic` (or binary graphic-vs-photograph) class — exactly as `InteriorSignal` (`src/scoring/signals/interior.py`, `results/interior_probe.joblib`) did for the zero-shot interior gate. CLIP embeddings *do* separate graphics from photographs even though CLIP zero-shot labels don't (the whole reason `GraphicDetectionSignal` avoided CLIP). Natural home: fold a `graphic`/`neither` class into the in-progress 4-class scene probe (`scripts/prototype_scene_probe.py`, corpus `results/scene_labels/`), whose `neither/` reject class already lists "logos … product shots"; the logo + poster above are ideal `neither/` (or a dedicated `graphic/`) positives.

**Status:** Open — not a weight-tuning issue; a missing capability. Cheap gate stays as a fast-path for true icon assets.
**Priority:** P3
**Source:** ChatGPT shadow-scorer investigation, 2026-07-18 (`results/scoring_shadow.jsonl`; agreement-set manual review)

- **Do not chase it with more pixel heuristics.** Opaque AI-generated graphics are pixel-indistinguishable from photos by palette/size/alpha; only the learned embedding separates them.
- **Keep the cheap gate.** `GraphicDetectionSignal` correctly and cheaply catches transparent/square icon assets pre-CLIP; the probe is an *additional* heavy-tier voter for the opaque-graphic case it can't see, gated on CLIP availability with graceful no-op (same pattern as `InteriorSignal`).
- **Corpus dependency.** Needs labeled graphic/neither positives (target 150–300/class per the scene-probe README); `results/scene_labels/{place,neither}/` are currently empty, so the probe is not yet trainable.
- **Regression guard.** Measure false positives on genuine photos (product still-lifes, staged interiors) before deploying — a graphic probe that over-fires would pull real photos out of `photos_*`.
- **Runtime landing path (updated 2026-07-18).** The scene-probe runtime now exists: `SceneSignal` (`src/scoring/signals/scene.py`) + the artifact-gated registry swap landed. If the graphic class rides the scene probe, the remaining training work is: (1) add a `graphic` label to `SCENE_CLASSES` in `scripts/prototype_scene_probe.py`; (2) hand-label `results/scene_labels/graphic/` alongside the pending positive classes; (3) retrain → eval threshold sweep → commit `scene_probe.joblib` with its backtest; (4) map the class in `scene.py`'s `SCENE_CATEGORY`/`SCENE_SCHEMA` (→ `media/graphics_other`). Until step 4, `SceneSignal` safely ignores unknown classes in `meta.classes` — a 5-class artifact can ship before the mapping without misrouting anything.

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

1. **The review gate keys on decision-confidence, which `InteriorSignal` inflates.** UI screenshots of real-estate listings committed to `Media/Interiors` (`Room`) because the interior probe votes ~0.99 (decision confidence ~0.85, margin ~0.81) even when the OCR/label confidence is 1–12%. The `low_confidence`/`low_margin` review bucket exists and *does* fire (confirmed in a `--scorer shadow` pass — one opaque PDF routed to `uncategorized/other`), but cannot catch these because the probe supplies genuine high decision-confidence to wrong content. Options: a per-signal reliability cap, or require corroboration for `InteriorSignal` on screenshot-detected inputs. Distinct from the `PHOTO_PROPERTY_CONFIDENCE` item above (that is the `PhotoCompositionSignal` property flag *under*-committing; this is the `InteriorSignal` probe *over*-committing). The scene-model swap in [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](plans/MEDIA_EXTERIORS_PLAN.md) also intersects here.

### Wikidata enrichment — verified review findings (multi-agent review of the 2026-07-18 implementation)

A five-angle multi-agent review of the Wikidata enrichment commits (`ae1ad07`…`901204d`) produced ~30 candidates; these three survived verification against the current tree (stale/refuted findings were discarded — e.g. the ORM-column crash and hit-rate denominator were already fixed pre-merge).

**Status:** Done — 2026-07-18. Fixed all three verified findings: (1) `--limit` now caps queried rows (pre-filters enriched companies before slicing); (2) `_query_api` post-parse block moved inside the try/except guard, `AttributeError`/`ValueError`/`TypeError`/`KeyError` added to catch array-body and non-numeric-score crashes; (3) `stats["columns_added"]` only increments on actual `ALTER TABLE`, not in dry-run branch. `RECONC_USER_AGENT` version unhardcoded via `importlib.metadata`. 3 new regression tests added.
**Priority:** P3
**Source:** multi-agent review of Wikidata enrichment implementation, 2026-07-18

1. **`--limit` is applied before skipping already-enriched rows** (`scripts/enrich_wikidata.py` — `companies = companies[:limit]` runs before the `existing_qid` skip). On a database whose first N rows are already enriched, `--limit N` makes zero API calls. The limit should cap *queried* companies (filter enriched rows first, or skip them in SQL).
2. **API-response parsing sits outside the error guard** (`src/storage/wikidata_enricher.py::_query_api`). The `try/except` ends after `json.loads`; a JSON array body raises `AttributeError` on `body.get("q0")`, and a non-numeric `score` raises `ValueError` from `float()`. Both crash a batch run, violating the module's documented "returns None on any error" contract. Extend the guard (or catch `ValueError`/`AttributeError`/`TypeError`) around the post-parse block.
3. **Dry-run migration reports work it didn't do** (`src/storage/wikidata_migration.py::run_wikidata_migration`). `stats["columns_added"] += 1` also increments under `dry_run=True`, so the summary prints "Columns added: 1" directly above "[DRY RUN] No changes were made", and the return dict claims a change. Count only on the actual `ALTER TABLE` branch (or rename to `columns_pending` in dry-run).

Minor cleanups noted in the same review (batch `_write_qid_to_db` into one connection; dedupe `_column_exists`/`_table_exists` across `scoring_migration.py`/`wikidata_migration.py`; unhardcode `"2.1.0"` in `RECONC_USER_AGENT`) can ride along with these fixes.

### GPS falsy-zero guard drops equator/prime-meridian coordinates in `build_file_jsonld`

`build_file_jsonld` guards the `contentLocation` block with `if f.gps_latitude and f.gps_longitude:` (`src/storage/models.py`), so a valid coordinate of exactly `0.0` (equator or prime meridian) silently drops GPS data from JSON-LD output. Should be `is not None` checks on both.

**Status:** Done — 2026-07-18. Changed guard in `build_file_jsonld` (`src/storage/models.py:884`) from `if f.gps_latitude and f.gps_longitude:` to `if f.gps_latitude is not None and f.gps_longitude is not None:`. Added `test_gps_zero_latitude_emits_content_location` in `tests/integration/test_core_export_parity.py` covering both ORM and core-query paths; updated stale fixture comment. All 8 parity tests + 75 unit tests pass.
**Priority:** P3
**Source:** multi-agent review (line-by-line diff scan angle), 2026-07-18


