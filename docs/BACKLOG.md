# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-17 (added `review_status` SQLAlchemy `Enum` column-type item).

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

`SCORER_DEFAULT` became `unified` on 2026-07-17 (Phase-4 flip), driving the CLI `--scorer` flag and `ContentBasedFileOrganizer` — the production path, which passes `super().__init__(scorer=…)`. The base `ContentOrganizer.__init__` (`src/organizers/content_organizer.py:271`) still hardcodes `SCORER_LEGACY`. That path is **test-only**: no production code constructs `ContentOrganizer` directly, but `tests/unit/test_content_organizer.py` fixtures build `ContentOrganizer()` at the default and assert legacy 10-tier placements. Making the base track `SCORER_DEFAULT` today would cascade-break dozens of those tests, so the split-brain default was left in place and documented in the `src/scoring/types.py` comment.

**Status:** Open — deferred; larger change than the Phase-4 flag flip.
**Priority:** P3
**Source:** Phase-4 default flip, 2026-07-17 (see [`UNIFIED_SCORING_PLAN.md`](architecture/UNIFIED_SCORING_PLAN.md) Phase 5)

- **Single source of truth.** Change `ContentOrganizer.__init__(scorer: str = SCORER_LEGACY)` → `= SCORER_DEFAULT` so base construction, the CLI flag, and `ContentBasedFileOrganizer` share one default; then delete the split-brain note in `src/scoring/types.py`.
- **Re-pin the legacy-behavior tests.** `tests/unit/test_content_organizer.py` fixtures and `tests/unit/scoring/test_dispatch.py::test_default_is_legacy` build `ContentOrganizer()` at the default and expect the 10-tier chain — re-record them against unified, or make them pass `scorer=SCORER_LEGACY` explicitly to keep exercising the chain.
- **Then retire the legacy chain (full Phase 5).** Once nothing defaults to legacy, remove the legacy `_classify_*` paths and the `legacy`/`shadow` scorer modes per UNIFIED_SCORING_PLAN Phase 5; the interior re-tune's "Legacy parity note" (above) resolves when the chain is gone.


