# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-16.

## Open Items

### Unified scoring — Phase-3 calibration worklist

Weight/threshold calibration targets for the unified scorer, from the golden suite plus the first real shadow run.

**Status:** Open — engine + tooling shipped (`feat/unified-scoring`, PR #9); calibration not started.
**Priority:** P2 (gates the Phase-4 default flip)
**Source:** golden-suite findings + `~/Downloads` shadow dogfood (49 files), 2026-07-16

Baseline evidence: shadow run over `~/Downloads` scored **42/49 (85.7%) agreement** with legacy — 41 committed / 8 low-confidence, 7 disagreements, format-drift pair (`PlacementMap_Draft.pdf`/`.png`) converging on `legal/real_estate` under unified as designed. Rerun loop: `organize-files content --scorer shadow --dry-run` → `python scripts/analyze_scoring_disagreement.py`; weight sensitivity via `python scripts/backtest_scoring.py --weights-sensitivity`.

Calibration items, by observed impact:

1. **Mime commit-gap** — `W_MIME (0.3) < MIN_DECISION_CONFIDENCE (0.35)`, so mime/extension-only evidence can never commit; legacy tier-6 fallback *does* rescue these. Dominant cause of the 8 low-confidence states and both `→ uncategorized` flips in the shadow run (`ChatGPT Image *.png` lost `creative/photos`, `placement_map_600dpi.png` lost `media/graphics_other`). Fix candidates: raise `W_MIME` to ~0.4, or lower the floor — verify against the golden that pins mime-cannot-override (`tests/unit/scoring/test_signal_mime_fallback.py`).
2. ~~**Text-content keyword collisions on large HTML blobs**~~ — **DONE (`a780829`).** Root cause was substring keyword matching in `ContentClassifier` (`kw in text`), not length: `property` scored 1.0 on `promethease.html` purely from `lease`⊂"re**lease**" and `rent`⊂"pa**rent**"/"cu**rrent**". Fixed with word-boundary-aware matching (`_keyword_alt`; one alternation regex per category for single-scan perf on huge extractions). Verified: golden `genetics_report_no_longer_substring_misroutes` (property/leases → medical/records) + real-file re-shadow (`property` gone from the distribution entirely). Side-benefit: the CV low-margin gap (item #3) partly resolved — `reference` no longer matches "refe**rences**", so contacts stops splitting with a spurious employment vote (golden `cv_without_filename_rule_commits_contacts`). Two *new* residuals surfaced, both distinct from the substring bug:
   - **Raw-HTML page-chrome noise** — on the real file the pipeline extracts the raw 8 MB HTML source (not the JS-decompressed genotypes), whose boilerplate/disclaimer text now scores `business/other`. The legacy filepath tier routed `.html` to `technical/web`; consider letting `FilepathSignal` (or an HTML tag-strip in extraction) outweigh keyword noise for markup files.
   - **Genuine-word polysemy** — even with word boundaries, real standalone words collide across domains: "reference allele"/"DNA repair" legitimately hit the `reference` (employment) and `repair` (property/maintenance) keywords. Not fixable by boundary matching; needs per-category evidence thresholds or a genetics/genomics category (the taxonomy has no home for such reports).
3. **Same-category subcat competition splits margins** — `personal/contacts` (personal_doc 0.81) vs `personal/employment` (text_content 0.71) lands margin ≈0.098 < `MIN_DECISION_MARGIN` (0.10) → fallback bucket, even though the *category* is undisputed. Pinned by golden `cv_without_filename_rule_is_low_margin`. Consider computing margin at category level (or aggregating subcat votes within a category) before the margin gate.
4. **Insurance-document vocabulary gap** — USAA policy PDF: legacy `organization/financial` (company-driven) vs unified `legal/real_estate` (lease/property keywords in policy text). Neither taxonomy has an insurance home; decide the intended routing and add vocabulary or a golden.
5. **Legacy naming traps inherited by both engines** (fix in the unified path during calibration; legacy keeps parity until Phase 5):
   - sprite regex `^[a-z]+_\d+$` catches camera/scanner names (`IMG_2043`, `scan_0023`) → `game_assets/sprites`;
   - "Hyphenated asset" filename rule catches any 3-token hyphenated `.png` (`invoice-page-march.png`) → `game_assets/sprites` at full confidence;
   - filename game rule always answers `sprites` where the keyword tier's discriminator says `textures` (golden `texture_without_document_text_stays_game`);
   - the `.mp3` "Audio file" rule (→ `audio_other`) always outranks `media_heuristic`'s podcast/music refinement (golden `media_audio_filename_rule_wins`).
   Candidate mechanism for all four: extend the `FILENAME_WEAK_RESULTS` graduation in `src/scoring/signals/filename_pattern.py` (shipped for `media/photos_other`) to other weak catch-all rules, and/or tighten the source regexes in `shared/filename_classifier.py` (OQ #5 decomposition).
6. **Grid-search calibration proper** (plan §6 Phase 3 / OQ #3) — replay against labeled data (`organize-files evaluate --classifier unified`, `scripts/backtest_scoring.py --labels`), tune `src/scoring/weights.py`, and commit each re-tune with its backtest report as `docs/architecture/scoring-calibration-YYYYMMDD.md`. Gate for the default flip: ≥98% agreement on currently-correct cases, ≥80% fix rate on the §1 residual audit set.

### Timeline data pinned to committed JSON — needs a populated DB

`_site/timeline_data.json` is a stale committed snapshot; the current DB has no sessions to regenerate it from.

**Status:** Open — workaround in place (restored committed JSON).
**Priority:** P4
**Source:** timeline doc-consolidation session, 2026-07-16

`organize-files timeline` reads `organization_sessions` from `results/file_organization.db` and writes `_site/timeline_data.json` (fixed `OUTPUT_PATH`; only `--db-path` is configurable). Running it 2026-07-16 produced an **empty** document (0 sessions / 0 files): the current DB is a fresh/test state with `organization_sessions` = 0 rows (199 `files` rows, all `NULL session_id`). The committed `timeline_data.json` (**15 sessions / 41,614 files**) was restored from git so `timeline.html` still renders real data.

To move off the pinned snapshot: point at a DB that has real `organization_sessions` rows (run live/dry-run organization passes that record sessions, or restore the source DB that produced the committed JSON), then `organize-files timeline` to regenerate. Until then the committed JSON is the source of truth and must not be overwritten by a run against the empty DB. Schema + CLI reference: [`docs/TIMELINE.md`](TIMELINE.md#data-structure-reference).

### Person-graph edge hygiene

Leaky denylist (prune and dead-path tooling shipped 2026-07-12).

**Status:** Open — gaps 1 and 3 closed (prune tooling, `--prune-missing`); gap 2 remains.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

One remaining gap handles false-positive "people" in the symlink view.

1. **`get_all_people_with_files` denylist is leaky.** False-positive "people" (event/org names) still pass the org/keyword denylist — e.g. `Morning Train` (from `Burning_Flipside_Map.pdf`) — and would create spurious `Person/{Name}/` folders on `person-view --apply` unless pruned first.

   *Fix planned (2026-07-13):* layered local-only confidence gate at write time (`nameparser` shape → `probablepeople` CRF → Census gazetteer, weighted composite) with three-way routing (auto-accept / `pending_review` queue via a new `organize-files review-people` CLI / reject), `review_status`+`validation_scores` columns on `people`, and an `additionalProperty` JSON-LD sidecar. External KB validation rejected (notability gap — see the Wikidata item below). Full phased design: [`docs/plans/PERSON_NAME_VALIDATION_PLAN.md`](plans/PERSON_NAME_VALIDATION_PLAN.md).

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

### AI-runtime path test coverage for content_organizer and file_processor

Missing unit test coverage for AI-runtime paths required to reach 80% overall coverage.

**Status:** Done — commits 232ef52, 3d5ee56 (also fixed organizer._persist_to_graph_store → self)
**Priority:** P2
**Source:** coverage observation, 2026-07-13

Coverage run 2026-07-13 (`pytest tests/unit tests/integration --cov=src`): overall 73% vs the 80% target. The uncovered mass is concentrated in AI-runtime paths that existing tests deliberately mock out: `src/organizers/content_organizer.py` 50% of 633 stmts, `src/pipeline/file_processor.py` 34% of 264 stmts, `src/pipeline/batch_processor.py` 50% of 134 stmts. `tests/unit/test_pipeline.py` already covers FileProcessor/BatchProcessor construction and non-AI flow (18 tests); the gap is the classification-dependent branches. Closing it requires:

1. **`file_processor.py` AI paths** — exercise the per-file classification flow (CLIP/OCR result handling, confidence gating, schema generation) with stubbed classifiers rather than skipping those branches
2. **`content_organizer.py` AI paths** — existing tests mock classifiers at low level; need higher-level tests that drive the full categorization pipeline with stubbed (non-CLIP) classifiers to verify routing logic and fallback behavior without GPU/ML dependencies
3. **`batch_processor.py`** — verify batch error resilience and progress/report flow without hitting real classifiers

Test design approach: Stub the expensive classifiers (`CLIPClassifier.encode`, `ocr_classifier.classify`) with deterministic mock implementations that return known scores, then drive realistic file-organization scenarios (e.g., mixed content types with classifier disagreement, OCR fallback triggering, confidence-gate rejections).


### Non-AI-path coverage tail + developer docs (migrated from retired TEST_AND_REFACTOR_PLAN.md)

**Status:** Partially done — commit 8eaf056 brought `validator.py` 28% → 100% and overall to 82%; commits a1248b6 + 1ed4b64 added 85 tests for `src/integration.py` (~23% → ~95%) and `src/error_tracking.py` (~50% → ~80%).
**Priority:** P3
**Source:** coverage measurement + doc-TODO migration, 2026-07-14

The 2026-07-14 coverage run (`pytest tests/unit tests/integration --cov=src`) measured **79% overall** (7,365 stmts) — hitting the plan's Month-1 75% bar but short of its 80%/85% goals. 2026-07-14 session raised this to **82%**. Remaining gaps in non-AI glue:

- `src/cost_integration.py` 0% (import fails without `cost_roi_calculator` on top-level path; test requires env setup or import refactor) · `src/utils/tracking.py` 26% (stubs unreachable in normal test env) · `src/api/schema_org_api.py` 64%.

One documentation TODO also carries over from the retired plan (never done):

1. **Docstring pass** — the plan's "update all docstrings" step landed only partially.

Storage layer (90%), generators+base (91%), enrichment (98%), and validator (100%) already meet their targets.


### scripts/ ↔ src/ duplication cleanup (53 confirmed findings)

Full copypasta audit of `scripts/` against the canonical `src/` library found 53 verified duplications across 7 zones.

**Status:** Open — 37 of 53 resolved; ~16 open (type-organizer loop, `filename_classifier` keyword/entity/legal tables, sprite/font regexes, OCR probe, classify_by_ocr scoring loop, analyze_report summary sections).
**Priority:** P2 (top items are active correctness drift; bulk is P3/P4 consolidation)
**Source:** multi-agent scripts↔src duplication audit, 2026-07-14

Full findings with line-level evidence, divergence notes, and per-item recommendations: [`docs/reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md`](reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md).

Priority order from the review:

1. ~~**Timeline exporter split-brain** — `scripts/generate_timeline_data.py` and the orphaned `src/api/timeline_api.py` both write `_site/timeline_data.json` with incompatible document schemas; consolidate or delete the dead src path.~~ **DONE (`4437a25`)** — the entire Timeline zone (7 findings) was consolidated; `scripts/generate_timeline_data.py` is now a thin launcher over the `TimelineAPI` class. See the resolution note in the review doc.
5. Remaining ~19 items (type-organizer scan/summary loop, `filename_classifier` keyword/entity tables) opportunistically when the owning script is touched.

Resolved so far (2026-07-14–15): items 1–4 from the original priority list plus `file_iri` single-sourcing (`src/storage/models.py`), `financial_doc_keywords` billing inconsistency fix (`scripts/shared/filename_classifier.py`), and KIE constants single-sourcing — `KIE_MIN_CONFIDENCE` + `KIE_VENDOR/AMOUNT/DATE_CLASSES` now single-homed in `kie_schema_mapping.py`, imported by `content_classifier.py`; removes the silent-drift risk from two private 0.5 copies. See the review doc for per-finding resolution notes.

Resolved 2026-07-15 (3 additional):
- **`_DOCUMENT_LABEL_MAP` key validation** (`relabel_test_set.py`): imports `DOCUMENT_PATTERNS` from `shared.constants`, asserts all map keys are present, adds `is_document` prefilter so pass 5's word-boundary regex is skipped when the feature extractor already determined the filename contains no document pattern (backward-compat: missing key defaults to run).
- **`CAMERA_VENDOR_PREFIX_PATTERNS`** (`shared.constants`): extracts the four camera-vendor prefix regexes (`^img_\d+`, `^pxl_\d+`, `^dsc_?\d+`, `^dcim_\d+`) into `shared.constants.CAMERA_VENDOR_PREFIX_PATTERNS`; `filename_utils._GENERIC_FILENAME_PATTERNS` unpacks them (no behavior change), `name_organizer.camera_photos` uses them via `re.IGNORECASE` (also picks up the `dsc_?` optional-underscore fix that was only in `filename_utils`).
- **Migration banner** (`src/storage/migration.py`): adds `run_migration_with_banner()` wrapper that owns the header/footer separator, title, and completion message; `src/cli.py:cmd_migrate` and `scripts/file_organizer_content_based.py` both delegate to it, removing the verbatim 5-line duplicate.


### Cross-file duplication within `src/` (investigation)

The scripts↔src audit and the TimelineAPI copypasta trim both surfaced duplication that is *internal to `src/`* — out of scope for the scripts↔src cleanup but worth a dedicated pass. Investigate whether each is worth consolidating or is a deliberate layer split before changing anything.

**Status:** Open — investigation, not committed work
**Priority:** P3
**Source:** TimelineAPI copypasta trim + scripts↔src audit out-of-scope observations, 2026-07-14

Candidates found so far:

1. **Session/aggregate stats computed at two layers.** `TimelineAPI.get_cumulative_stats` (`src/api/timeline_api.py`, raw sqlite3) and `GraphStore.get_statistics` (`src/storage/graph_store.py:1215`, SQLAlchemy ORM) both aggregate total files / organized count / category + extension breakdowns over the same DB. Likely *intentional* — timeline reads lightweight raw SQL to avoid pulling the ORM (and its torch import weight) into the dashboard path — but the scopes also differ (session-scoped vs global), so confirm the split is deliberate and, if so, document it rather than merging.
2. **`Technical/` extension map overlap.** `content_organizer.py`'s extension map (~lines 240-330) overlaps `mime_classifier.py`'s extension routing — two extension→category tables that can drift.

Both candidates are recorded in the review doc's "Out-of-scope observations": [`docs/reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md`](reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md).

### `generate_schema` fidelity losses vs the retired legacy implementation

Two divergences found while re-pointing the golden snapshot tests from the legacy `scripts/file_organizer.py` to the live `FileProcessor.generate_schema` look like losses rather than intent — investigate and either restore or bless.

**Status:** Done — commit 5a698e7
**Priority:** P2
**Source:** legacy-retirement session (golden re-record diff review), 2026-07-13

Migration context: the goldens originally pinned `scripts/file_organizer.py`'s `generate_schema` (per-type generator branches). When the pipeline layer moved into `src/`, the live implementation (`src/pipeline/file_processor.py:115`) kept only three branches — ImageObject, document types (DigitalDocument/Article/ScholarlyArticle/Report), and a generic fallback. The legacy script and its tests were deleted 2026-07-13; the re-recorded goldens (`tests/unit/golden/generate_schema/`, incl. `fallback_video_object.json`) now pin the current behavior, so resolving this either way will intentionally trip a snapshot.

1. **ImageObject lost `width`/`height`.** The legacy branch read PIL dimensions (`set_dimensions`); the live one doesn't. Dimensions may still reach the graph via the image-metadata path, but they're gone from the per-file JSON-LD.
2. **The type collapse.** VideoObject, AudioObject, SoftwareSourceCode, Dataset, Person, and Organization all fall to a bare `DocumentGenerator()` fallback that emits `@type: DigitalDocument` with only `name` + `description` (the legacy fallback at least had `encodingFormat`/`contentSize`/`url`). This is not hypothetical: `content_organizer.py:1054` still emits VideoObject/AudioObject and `category_config.py` maps whole subcategories to Organization — and `_persist_to_graph_store` stores `schema.get("@type")`, so **videos organized today are recorded in the graph as DigitalDocument**. The vCard parsing (`worksFor`, PostalAddress, name parts) also has no live equivalent; if it is restored, the deleted `_enrich_person_from_vcard`/`_enrich_organization_from_file` implementations and their tests are recoverable from git history (pre-2026-07-13).

### `scripts/shared/__init__.py` eager CLIP/OCR imports make every `shared.X` import heavy

**Status:** Done — commit 9f69983
**Priority:** P3
**Source:** format-classifier consolidation session, 2026-07-14

`scripts/shared/__init__.py` eagerly imports `clip_cache`, `clip_utils` (`CLIPClassifier`), and `ocr_classifier` at package-import time, so *any* `from shared.X import ...` drags in torch + open_clip (~1.8s, several hundred MB of RSS) even for lightweight helpers. This penalizes callers that need no ML — notably `organize-files type` (extension-only, deterministic), which imports `shared.file_ops` and pays the full ML-stack load before doing any work. Fix by making the heavy re-exports lazy (PEP 562 `__getattr__` in `shared/__init__.py`) or dropping `clip_*`/`ocr_*` from `__init__` so they are imported only via their submodules; first confirm no consumer relies on eager `from shared import CLIPClassifier`-style access. Pre-existing (not introduced by the consolidation work); surfaced while measuring the type command's import weight.


### Defensive `_getexif()` fix for non-EXIF image formats

**Status:** Done — commit `229a011`, 2026-07-14
**Priority:** P3
**Source:** image_metadata.py defensive handling, 2026-07-14

`ImageMetadataParser.extract_exif_data` directly called `image._getexif()`, which raises `AttributeError` on formats without EXIF (GIF, PNG, WebP without EXIF). Fixed by probing with `getattr(image, "_getexif", None)` before calling so those formats degrade cleanly. The same commit added `extract_text_metadata()` for GIF/PNG textual chunks with a PNG "Creation Time" datetime fallback. Covered by `tests/unit/test_image_metadata.py` (48 tests); the piexif fallback path is unaffected.


