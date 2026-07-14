# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-14.

## Open Items

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

**Status:** Partially done — commit 8eaf056 brought `validator.py` 28% → 100% and overall to 82%.
**Priority:** P3
**Source:** coverage measurement + doc-TODO migration, 2026-07-14

The 2026-07-14 coverage run (`pytest tests/unit tests/integration --cov=src`) measured **79% overall** (7,365 stmts) — hitting the plan's Month-1 75% bar but short of its 80%/85% goals. 2026-07-14 session raised this to **82%**. Remaining gaps in non-AI glue:

- `src/integration.py` 23% · `src/cost_integration.py` 0% · `src/utils/tracking.py` 26% · `src/error_tracking.py` 50% · `src/api/schema_org_api.py` 64%.

One documentation TODO also carries over from the retired plan (never done):

1. **Docstring pass** — the plan's "update all docstrings" step landed only partially.

Storage layer (90%), generators+base (91%), enrichment (98%), and validator (100%) already meet their targets.


### scripts/ ↔ src/ duplication cleanup (53 confirmed findings)

Full copypasta audit of `scripts/` against the canonical `src/` library found 53 verified duplications across 7 zones.

**Status:** Open
**Priority:** P2 (top items are active correctness drift; bulk is P3/P4 consolidation)
**Source:** multi-agent scripts↔src duplication audit, 2026-07-14

Full findings with line-level evidence, divergence notes, and per-item recommendations: [`docs/reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md`](reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md).

Priority order from the review:

1. **Timeline exporter split-brain** — `scripts/generate_timeline_data.py` and the orphaned `src/api/timeline_api.py` both write `_site/timeline_data.json` with incompatible document schemas; consolidate or delete the dead src path.
5. Remaining ~40 items (type-organizer taxonomy drift, `filename_classifier` keyword overlaps) opportunistically when the owning script is touched.

Subsumes the pre-existing generator import-list item into the same cleanup effort — all resolved in a single 2026-07-14 multi-commit session.


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


