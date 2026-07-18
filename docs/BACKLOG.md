# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-17 (added diverse-source robustness + shadow healthcare-detection regression items from the ~/Desktop audit and ~/Downloads shadow pass).

## Open Items

### Person-graph edge hygiene

Leaky denylist (prune and dead-path tooling shipped 2026-07-12).

**Status:** Done — all open gaps closed 2026-07-18.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

1. **`get_all_people_with_files` denylist is leaky.** ✓ Done 2026-07-18. Full validation plan (Phases 1–4) shipped: layered name validator (`person_name_validator.py`, L0 denylist + L1 nameparser shape + L2 probablepeople + L3 census gazetteer), write-time gate in `get_or_create_person`, `review_status`/`detection_confidence`/`validation_scores`/`validated_at` columns + migration, `organize-files review-people` CLI (`--status`/`--accept`/`--reject`/`--revalidate`/`--apply`), `additionalProperty` JSON-LD sidecar in `build_person_jsonld`, and `organize-files health` now reports validator layer availability. Read-time `_PERSON_NAME_DENYLIST` loop removed from `get_all_people_with_files`; status filter is now the sole gate. 30 new tests in `tests/unit/test_graph_store_review.py`.

2. **`review_status` should be a SQLAlchemy `Enum` column type.**

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

### `PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin

`PhotoCompositionSignal`'s home-interior flag routes to `media/interiors_other` (folder `Media/Interiors`, schema.org `Room`) but scores `PHOTO_PROPERTY_CONFIDENCE(0.7) × W_PEOPLE_PHOTO(0.65) = 0.455` — only 0.055 over an image's `mime_fallback` vote (`0.4`). That lead is below `MIN_DECISION_MARGIN(0.10)`, so an interior photo whose only signals are composition + mime routes to `LOW_CONFIDENCE_FALLBACK` instead of committing to `Media/Interiors`. The `Room` schema override is wired but effectively unreachable for the common two-signal case.

**Status:** Open — not committed work; calibration change with eval impact.
**Priority:** P3
**Source:** `Media/Interiors` / schema.org `Room` folder addition, 2026-07-17

- **Do not eyeball the bump.** Per the Phase-3 calibration process (`src/scoring/weights.py` header — "treat this module as versioned data and commit each re-tune with its backtest report"), any change to `PHOTO_PROPERTY_CONFIDENCE` (or `W_PEOPLE_PHOTO`) must be backed by a `results/file_organization.db` backtest, committed with the report.
- **Target invariant:** `PHOTO_PROPERTY_CONFIDENCE × W_PEOPLE_PHOTO − (MIME_MATCH_CONFIDENCE × W_MIME) ≥ MIN_DECISION_MARGIN`, i.e. `conf ≥ (0.4 + 0.10) / 0.65 ≈ 0.77`, so interiors commit over the mime-only floor.
- **Regression guard:** measure false positives — staged/real-estate listing photos and any non-interior images the analyzer flags `is_property_mgmt` — before raising, since a higher confidence also strengthens every interior vote against genuine content winners.
- **Legacy parity note:** the legacy `_classify_photo_composition` still routes interiors to `property_management/other`; a unified re-tune widens the shadow legacy-vs-unified disagreement for interior photos until the legacy chain is retired (Phase 5).

### Content pipeline is OCR-bound (gate OCR on text-likelihood)

Profiling `organize-files content` (unified scorer, dry-run) on 2026-07-17 showed the workflow is **~85% OCR-bound** (`torch.conv2d` in the easyocr CRAFT + docTR detection CNNs ≈ 67% of self-time; CLIP is negligible). This session shipped P2/P3/P5 (docTR-fallback gate, screenshot double-OCR dedup, CLIP text-embedding memoization) — conv2d call count dropped 1189→528 (−56%). Two items remain.

**Status:** Open — P1 not started; P2 gate shipped (recall tradeoff to monitor).
**Priority:** P3 (P1 is the largest remaining perf win)
**Source:** content-classification profiling + P2/P3/P5 optimization session, 2026-07-17

1. **Gate OCR on text-likelihood (P1 — biggest remaining win).** easyocr's CRAFT detector still runs on every image because `IdentityDocumentSignal.applies_to` is just `is_image`. Gating OCR on text-likelihood would cut the bulk of the remaining cost, but it changes classification (an ID doc can be a photo) and needs an eval.

2. **P2 docTR-fallback gate — recall tradeoff to monitor.** The shipped gate (`extract_ocr_with_confidence`: skip the docTR fallback when easyocr cleanly finds no text) was eval'd over 7 text images at varying difficulty: **1/7 recall loss — very-low-contrast text** (easyocr's detector found nothing; docTR would have caught it). Clean, dark-mode, and rotated text were all gate-safe. So P2 trades a rare miss on near-invisible text for eliminating the docTR fallback. For a screenshot/photo-dominated 265k-file library this is very likely a net win, but it is a real behavior change — put it behind a config flag or revert if faint-text recall matters.


### Content organizer misclassifies diverse/screenshot sources (review-gate + robustness gaps)

A live `organize-files content --source ~/Desktop --limit 10` (unified scorer) on mixed real-world desktop content committed most files to wrong folders and surfaced several distinct gaps. Items 2–5 shipped; item 1 remains open.

**Status:** Open — item 1 gates safe use on real user directories.
**Priority:** P2 (item 1)
**Source:** `~/Desktop` content-run audit + full rollback, 2026-07-17

1. **The review gate keys on decision-confidence, which `InteriorSignal` inflates.** UI screenshots of real-estate listings committed to `Media/Interiors` (`Room`) because the interior probe votes ~0.99 (decision confidence ~0.85, margin ~0.81) even when the OCR/label confidence is 1–12%. The `low_confidence`/`low_margin` review bucket exists and *does* fire (confirmed in a `--scorer shadow` pass — one opaque PDF routed to `uncategorized/other`), but cannot catch these because the probe supplies genuine high decision-confidence to wrong content. Options: a per-signal reliability cap, or require corroboration for `InteriorSignal` on screenshot-detected inputs. Distinct from the `PHOTO_PROPERTY_CONFIDENCE` item above (that is the `PhotoCompositionSignal` property flag *under*-committing; this is the `InteriorSignal` probe *over*-committing). The scene-model swap in [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](plans/MEDIA_EXTERIORS_PLAN.md) also intersects here.


