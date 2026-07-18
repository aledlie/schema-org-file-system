# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-17 (added diverse-source robustness + shadow healthcare-detection regression items from the ~/Desktop audit and ~/Downloads shadow pass).

## Open Items

### Person-graph edge hygiene

Leaky denylist (prune and dead-path tooling shipped 2026-07-12).

**Status:** Open — gaps 1 and 3 closed (prune tooling, `--prune-missing`); gap 2 remains.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

One remaining gap handles false-positive "people" in the symlink view.

1. **`get_all_people_with_files` denylist is leaky.** False-positive "people" (event/org names) still pass the org/keyword denylist — e.g. `Morning Train` (from `Burning_Flipside_Map.pdf`) — and would create spurious `Person/{Name}/` folders on `person-view --apply` unless pruned first.

   *Fix planned (2026-07-13):* layered local-only confidence gate at write time (`nameparser` shape → `probablepeople` CRF → Census gazetteer, weighted composite) with three-way routing (auto-accept / `pending_review` queue via a new `organize-files review-people` CLI / reject), `review_status`+`validation_scores` columns on `people`, and an `additionalProperty` JSON-LD sidecar. External KB validation rejected (notability gap — see the Wikidata item below). Full phased design: [`docs/plans/PERSON_NAME_VALIDATION_PLAN.md`](plans/PERSON_NAME_VALIDATION_PLAN.md).

2. **`review_status` should be a SQLAlchemy `Enum` column type.** The valid values now live in `Person.REVIEW_STATUSES` (a plain tuple) and are enforced only by hand-rolled `if status not in ...: raise ValueError` guards in `GraphStore.list_people_by_status` / `set_person_review_status`. Migrating the `String(20)` column to `sqlalchemy.Enum(*Person.REVIEW_STATUSES)` would give DB- and ORM-level validation and delete those manual checks.

   *Deferred:* it is a column-type schema change requiring a migration, for modest gain over the already-centralized tuple. Do it only when the schema is being touched for another reason.


### Wikidata SPARQL for non-person entity typing

Investigate Wikidata as a type validator for entities where notability is expected.

**Status:** Open — investigation, not committed work.
**Priority:** P3
**Source:** gap-2 web research session, 2026-07-13

Wikidata was rejected for *person* validation because personal documents are dominated by non-notable people it can never confirm. But the notability profile inverts for other entity types the system already detects, where a large share of true positives *are* notable:

- **Organizations** — validate `entity_detector.extract_company_names` output (vendors, employers) against organization classes before creating `Organization/{Name}/` folders.
- **Research publishers** — confirm publisher identity for `Research/{Publisher}/` routing (`schema_type=ScholarlyArticle`).
- **Locations** — type-check detected place names before creating Location nodes.
- **Events** — a positive event-class match is a strong *negative* signal for person/org detection (would have caught `Morning Train` if notable).

Technical notes from the research: `P31` (instance-of) checks against class QIDs (org `Q43229`+subclasses, event `Q1656682`/`Q52943`, human `Q5`); content is CC0 so results cache in SQLite indefinitely; rate limits ~5 parallel queries/IP + 60s query-time/min + mandatory identifiable User-Agent (nightly sequential batch fits easily); the ready-made reconciliation endpoint `wikidata.reconci.link` (W3C Reconciliation API v0.2, `query + type hint → ranked scored candidates`) is the lower-effort integration path vs raw SPARQL. Investigation should size: hit rate on the real `companies` table, wrong-entity collision risk, and whether a "no match" fallback stays cheap. Keep any implementation as an optional nightly enrichment — the core pipeline must remain offline-capable.

### Logo/icon/graphic detection needs a non-CLIP signal

CLIP zero-shot labels cannot reliably identify minimal brand graphics (logos, app icons, flat illustrations); they land in `Uncategorized`.

**Status:** Open — investigation, not committed work.
**Priority:** P3
**Source:** content-organize dry-run on `~/Documents/Organization/InventoryAI`, 2026-07-14

Minimal brand graphics carry no EXIF/text metadata and defeat the CLIP vocab in `src/analyzers/image_analyzer.py` (`_ALL_CATEGORIES`), so they fall through to `Uncategorized`. Adding `logo`/`icon`/`graphic` labels to the vocab was prototyped and **rejected** — the measurements show CLIP cannot do this:

- **Genuine logos sit at the softmax floor.** Two real logos (an animated cube app-icon GIF, an "S" logo WebP) scored 0.077–0.080 in the multiclass vocab (uniform floor = 1/13 ≈ 0.077) and P(graphic)=0.525 in a binary `graphic vs photograph` contrast — right on CLIP's decision boundary.
- **No usable operating point.** Binary threshold 0.5 catches both logos but false-positives 14/40 real photos; threshold 0.7 catches 0 logos. There is no threshold separating logos from photos.
- **The labels steal real photos.** In multiclass, a logo/icon label became the *top* match for 6/40 sampled real photos (15%) and 62/219 cached embeddings (~28%), and added ~0.02 one-directional dilution to every existing category score (softmax denominator growth) — a routing regression with no offsetting benefit.

The signal for graphics is non-visual-semantic and should come from cheap non-CLIP cues, evaluated as a pre-CLIP gate: alpha/transparency channel presence, low color-palette entropy / large flat-color regions, small distinct-color count, square or icon-standard aspect ratios, and source-domain hints in the filename (hash-style names, `cdn`/asset hosts). A purpose-trained binary photo-vs-graphic classifier is the heavier fallback. Route positives to a `Graphics/` (or `Media/Graphics/`) folder instead of `Uncategorized`. Contrast with the sibling finding that the **screenshot** label *is* CLIP-separable (binary precision 26→3 false-pos after rewording) — graphics are the harder case that CLIP alone can't solve.

### Cross-file duplication within `src/` (investigation)

The scripts↔src audit and the TimelineAPI copypasta trim both surfaced duplication that is *internal to `src/`* — out of scope for the scripts↔src cleanup but worth a dedicated pass. Investigate whether each is worth consolidating or is a deliberate layer split before changing anything.

**Status:** Open — investigation, not committed work
**Priority:** P3
**Source:** TimelineAPI copypasta trim + scripts↔src audit out-of-scope observations, 2026-07-14

Candidates found so far:

1. **Session/aggregate stats computed at two layers.** `TimelineAPI.get_cumulative_stats` (`src/api/timeline_api.py`, raw sqlite3) and `GraphStore.get_statistics` (`src/storage/graph_store.py:1215`, SQLAlchemy ORM) both aggregate total files / organized count / category + extension breakdowns over the same DB. Likely *intentional* — timeline reads lightweight raw SQL to avoid pulling the ORM (and its torch import weight) into the dashboard path — but the scopes also differ (session-scoped vs global), so confirm the split is deliberate and, if so, document it rather than merging.
2. **`Technical/` extension map overlap.** `content_organizer.py`'s extension map (~lines 240-330) overlaps `mime_classifier.py`'s extension routing — two extension→category tables that can drift.

Both candidates are recorded in the review doc's "Out-of-scope observations": [`docs/reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md`](reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md).

### `PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin

`PhotoCompositionSignal`'s home-interior flag routes to `media/interiors_other` (folder `Media/Interiors`, schema.org `Room`) but scores `PHOTO_PROPERTY_CONFIDENCE(0.7) × W_PEOPLE_PHOTO(0.65) = 0.455` — only 0.055 over an image's `mime_fallback` vote (`0.4`). That lead is below `MIN_DECISION_MARGIN(0.10)`, so an interior photo whose only signals are composition + mime routes to `LOW_CONFIDENCE_FALLBACK` instead of committing to `Media/Interiors`. The `Room` schema override is wired but effectively unreachable for the common two-signal case.

**Status:** Open — not committed work; calibration change with eval impact.
**Priority:** P3
**Source:** `Media/Interiors` / schema.org `Room` folder addition, 2026-07-17

- **Do not eyeball the bump.** Per the Phase-3 calibration process (`src/scoring/weights.py` header — "treat this module as versioned data and commit each re-tune with its backtest report"), any change to `PHOTO_PROPERTY_CONFIDENCE` (or `W_PEOPLE_PHOTO`) must be backed by a `results/file_organization.db` backtest, committed with the report.
- **Target invariant:** `PHOTO_PROPERTY_CONFIDENCE × W_PEOPLE_PHOTO − (MIME_MATCH_CONFIDENCE × W_MIME) ≥ MIN_DECISION_MARGIN`, i.e. `conf ≥ (0.4 + 0.10) / 0.65 ≈ 0.77`, so interiors commit over the mime-only floor.
- **Regression guard:** measure false positives — staged/real-estate listing photos and any non-interior images the analyzer flags `is_property_mgmt` — before raising, since a higher confidence also strengthens every interior vote against genuine content winners.
- **Legacy parity note:** the legacy `_classify_photo_composition` still routes interiors to `property_management/other`; a unified re-tune widens the shadow legacy-vs-unified disagreement for interior photos until the legacy chain is retired (Phase 5).

### Phase 5: flip base `ContentOrganizer` default to unified + retire legacy tests

**Status:** Done (2026-07-18, commit 0da8c22) — default flip + test re-pin complete.
**Priority:** P3
**Source:** Phase-4 default flip, 2026-07-17 (see [`UNIFIED_SCORING_PLAN.md`](architecture/UNIFIED_SCORING_PLAN.md) Phase 5)

`ContentOrganizer.__init__` now defaults to `SCORER_DEFAULT` (= `SCORER_UNIFIED`). All seven `ContentOrganizer(...)` constructions in `tests/unit/test_content_organizer.py` pass `scorer=SCORER_LEGACY` explicitly. `test_dispatch.py::test_default_is_legacy` renamed to `test_default_is_unified`. Split-brain comment removed from `src/scoring/types.py`.

Still remaining from Phase 5 (not part of this item):
- **Retire the legacy chain** — remove the legacy `_classify_*` paths and the `legacy`/`shadow` scorer modes per UNIFIED_SCORING_PLAN Phase 5 (separate, larger refactor).

### Content pipeline is OCR-bound (gate OCR on text-likelihood)

Profiling `organize-files content` (unified scorer, dry-run) on 2026-07-17 showed the workflow is **~85% OCR-bound** (`torch.conv2d` in the easyocr CRAFT + docTR detection CNNs ≈ 67% of self-time; CLIP is negligible). This session shipped P2/P3/P5 (docTR-fallback gate, screenshot double-OCR dedup, CLIP text-embedding memoization) — conv2d call count dropped 1189→528 (−56%). Two items remain.

**Status:** Open — P1 not started; P2 gate shipped (recall tradeoff to monitor).
**Priority:** P3 (P1 is the largest remaining perf win)
**Source:** content-classification profiling + P2/P3/P5 optimization session, 2026-07-17

1. **Gate OCR on text-likelihood (P1 — biggest remaining win).** easyocr's CRAFT detector still runs on every image because `IdentityDocumentSignal.applies_to` is just `is_image`. Gating OCR on text-likelihood would cut the bulk of the remaining cost, but it changes classification (an ID doc can be a photo) and needs an eval.

2. **P2 docTR-fallback gate — recall tradeoff to monitor.** The shipped gate (`extract_ocr_with_confidence`: skip the docTR fallback when easyocr cleanly finds no text) was eval'd over 7 text images at varying difficulty: **1/7 recall loss — very-low-contrast text** (easyocr's detector found nothing; docTR would have caught it). Clean, dark-mode, and rotated text were all gate-safe. So P2 trades a rare miss on near-invisible text for eliminating the docTR fallback. For a screenshot/photo-dominated 265k-file library this is very likely a net win, but it is a real behavior change — put it behind a config flag or revert if faint-text recall matters.


### Content organizer misclassifies diverse/screenshot sources (review-gate + robustness gaps)

A live `organize-files content --source ~/Desktop --limit 10` (unified scorer) on mixed real-world desktop content committed most files to wrong folders and surfaced several distinct gaps. Every file was verified by eye; the batch was fully rolled back afterward. The organizer is reliable on homogeneous sources (e.g. ChatGPT property renders) but not on heterogeneous user directories.

**Status:** Open — items 2 and 4 shipped (2026-07-18); items 1, 3, 5 remain open. Item 1 gates safe use on real user directories.
**Priority:** P2 (item 1)
**Source:** `~/Desktop` content-run audit + full rollback, 2026-07-17

1. **The review gate keys on decision-confidence, which `InteriorSignal` inflates.** UI screenshots of real-estate listings committed to `Media/Interiors` (`Room`) because the interior probe votes ~0.99 (decision confidence ~0.85, margin ~0.81) even when the OCR/label confidence is 1–12%. The `low_confidence`/`low_margin` review bucket exists and *does* fire (confirmed in a `--scorer shadow` pass — one opaque PDF routed to `uncategorized/other`), but cannot catch these because the probe supplies genuine high decision-confidence to wrong content. Options: a per-signal reliability cap, or require corroboration for `InteriorSignal` on screenshot-detected inputs. Distinct from the `PHOTO_PROPERTY_CONFIDENCE` item above (that is the `PhotoCompositionSignal` property flag *under*-committing; this is the `InteriorSignal` probe *over*-committing). The scene-model swap in [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](plans/MEDIA_EXTERIORS_PLAN.md) also intersects here.
2. ~~**`DecompressionBombError` bypasses all content signals.**~~ **Done (2026-07-18, commit d192033).** `CLIPClassifier._thumbnail_oversized` now bypasses Pillow's bomb guard (`Image.MAX_IMAGE_PIXELS = None` + finally restore) so `thumbnail()` can load then downscale images > 2× the pixel limit. Applied to all three call sites in `scripts/shared/clip_utils.py` (`_preprocess_image`, `encode_images_to_numpy`, `_classify_batch_impl`).
3. **Write-path inconsistencies on the same run.** 4 files got duplicate `file_categories` rows (`sprites`+`interiors_other`); ≥3 files had recorded category ≠ destination folder (the renamer picked the folder, the scorer wrote a different category); 1 file got no `file_categories` row at all. The renamer's folder decision and the scorer's category association can disagree — reconcile to a single source of truth for destination.
4. ~~**Sprite-regex `^[a-z]+_\d+$` overreach still live.**~~ **Done (2026-07-18, commit 67fd81d).** `GameAssetSignal` now skips sprite-pattern matching for camera-roll and scanner stems (`img_\d+`, `pxl_\d+`, `dsc_\d+`, `dcim_\d+`, `scan_?\d+`) via `_is_camera_or_scan_stem`, mirroring `FilenamePatternSignal.graduated_filename_confidence`. Generic renamed-screenshot stems like `creative_1` (no camera/scanner prefix) still match; a deeper fix would require design decisions about screenshot-title detection.
5. **Sensitive-source PII hazard.** OCR'd health/genetics text (SNPedia/Promethease genomics) and a vehicle VIN landed in `files.extracted_text`/`schema_data`. Recommend `--no-db` for sensitive sources (or a redaction pass), and document the hazard in QUICK_START.

### `entity_detector` misses brand-name orgs and over-extracts cited bodies from reference sections

Surfaced as a legacy↔unified disagreement on `GeneDx_Variant_Classification_Process_June_2021.pdf` (`--scorer shadow`, `~/Downloads`): legacy → `organization/healthcare`, unified → `technical/other`. Analyzing the PDF (2026-07-17, verified by reproducing `EntityDetector.extract_company_names` on its text) shows the disagreement is a symptom of two entity-detection bugs — and that **neither placement is clearly right**, so the earlier "legacy won / OCR starved the org signal" framing was wrong. The PDF has a clean 11 k-char text layer; the logged `OCR error: unable to read file` was on the redundant raster-OCR path and did not affect org detection.

**Status:** Open — not committed work; entity-detection quality.
**Priority:** P3
**Source:** GeneDx PDF content analysis, 2026-07-17

The document is GeneDx's public "variant classification assertion criteria" (a lab methodology doc, the kind labs publish to ClinVar). `extract_company_names` returns exactly one org — `"Medical Genetics and Genomics and the Association"` — and **does not detect GeneDx at all** (8 occurrences incl. footer + `genedx.com`). Two regex-design causes (`src/classifiers/entity_detector.py`):

1. **Single-token brand names are invisible.** Every company pattern needs either a legal suffix (`LLC/Inc/Corp/…`) or the institutional pattern's ≥2 leading tokens + trailing keyword (`…Association/University/…`). A bare CamelCase brand like `GeneDx` (one token, no suffix) matches nothing. Add a known-brand lexicon or CamelCase-token path, and/or use the email domain (`genedx.com`) as an org cue.
2. **Cited orgs in reference sections become truncated false positives.** The institutional pattern anchored on `Association` in the References line *"American College of Medical Genetics and Genomics and the Association for Molecular Pathology"*; its `{1,5}` inter-token cap dropped the leading "American College of", and `[^\S\r\n]` stopped at the line wrap before "…for Molecular Pathology" — yielding the garbled `"Medical Genetics and Genomics and the Association"`. The detector has no document-structure awareness, so any org cited in a References/bibliography block is extracted as the document's own org. Consider skipping reference regions or de-ranking orgs found only in citations.

**Routing consequence:** legacy would create a spurious `Organization/{Medical Genetics and Genomics and the Association}` folder (a mangled cited standards body, not GeneDx), so unified's `Technical/Other` is arguably the safer placement here — the fix belongs in `entity_detector`, not in re-weighting the org signal. Cross-check other citation-heavy PDFs (research papers, methodology docs) for the same false-positive-org pattern before changing extraction.

**Chosen approach (2026-07-18):** full replacement plan in [`docs/plans/ORG_NER_REPLACEMENT_PLAN.md`](plans/ORG_NER_REPLACEMENT_PLAN.md) — GLiNER v2.1 (zero-shot ORG NER, Apache-2.0, bounded-window for latency) behind the existing `extract_company_names` seam, paired with `cleanco` canonicalization and a model-free scoping layer (reference-span exclusion + email-domain ownership ranking) that fixes both failure modes. Phase 0 (model-free) prototype and a GLiNER latency benchmark on real docs are being run to settle the design.


