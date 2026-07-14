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

**Status:** Open
**Priority:** P2
**Source:** coverage observation, 2026-07-13

Coverage run 2026-07-13 (`pytest tests/unit tests/integration --cov=src`): overall 73% vs the 80% target. The uncovered mass is concentrated in AI-runtime paths that existing tests deliberately mock out: `src/organizers/content_organizer.py` 50% of 633 stmts, `src/pipeline/file_processor.py` 34% of 264 stmts, `src/pipeline/batch_processor.py` 50% of 134 stmts. `tests/unit/test_pipeline.py` already covers FileProcessor/BatchProcessor construction and non-AI flow (18 tests); the gap is the classification-dependent branches. Closing it requires:

1. **`file_processor.py` AI paths** — exercise the per-file classification flow (CLIP/OCR result handling, confidence gating, schema generation) with stubbed classifiers rather than skipping those branches
2. **`content_organizer.py` AI paths** — existing tests mock classifiers at low level; need higher-level tests that drive the full categorization pipeline with stubbed (non-CLIP) classifiers to verify routing logic and fallback behavior without GPU/ML dependencies
3. **`batch_processor.py`** — verify batch error resilience and progress/report flow without hitting real classifiers

Test design approach: Stub the expensive classifiers (`CLIPClassifier.encode`, `ocr_classifier.classify`) with deterministic mock implementations that return known scores, then drive realistic file-organization scenarios (e.g., mixed content types with classifier disagreement, OCR fallback triggering, confidence-gate rejections).


### scripts/ ↔ src/ duplication cleanup (53 confirmed findings)

Full copypasta audit of `scripts/` against the canonical `src/` library found 53 verified duplications across 7 zones.

**Status:** Open
**Priority:** P2 (top items are active correctness drift; bulk is P3/P4 consolidation)
**Source:** multi-agent scripts↔src duplication audit, 2026-07-14

Full findings with line-level evidence, divergence notes, and per-item recommendations: [`docs/reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md`](reviews/SCRIPTS_SRC_DUPLICATION_AUDIT.md).

Priority order from the review:

1. **Timeline exporter split-brain** — `scripts/generate_timeline_data.py` and the orphaned `src/api/timeline_api.py` both write `_site/timeline_data.json` with incompatible document schemas; consolidate or delete the dead src path.
2. **`regenerate_schemas.py` metadata-dropping drift** — its copied schema builder's `preserve_keys` omits `identifier`/`sameAs`/`publisher`/`description`, so regeneration silently strips ScholarlyArticle/CLIP metadata that `FileProcessor.generate_schema` now emits.
3. **Game keyword tables split-brained** — `GAME_AUDIO/MUSIC/FONT_KEYWORDS` duplicated between `scripts/shared/constants.py` and `content_organizer.py` with fixes on *both* sides (src still has the `'cast'`→`'podcast'` false positive the script fixed); single-home like `GAME_SPRITE_KEYWORDS`.
4. **`scripts/d1/schema.sql` stale ORM mirror** — missing `files` columns (`ocr_confidence`, `detected_language`, `kie_fields`) and the entire `merge_events` table; generate from `Base.metadata` instead of hand-maintaining.
5. Remaining ~40 items (type-organizer taxonomy drift, `filename_classifier` keyword overlaps, `DEFAULT_DB_PATH` ×11 call sites, small helper copies) opportunistically when the owning script is touched.

Subsumes the pre-existing item below (generator import list) into the same cleanup effort.

Zones 1 (timeline) and the three game-keyword findings in the keyword zone are now **resolved** (`a2146fe`, `1d495ed`, `cc06190`) — see the review doc's resolution notes.

### TimelineAPI post-consolidation cleanups (code-review follow-ups)

Low-severity findings from the code review of the timeline consolidation that were verified real but deliberately deferred; each is pre-existing (inherited verbatim from the old script) or optional.

**Status:** Open — deferred, low value
**Priority:** P4
**Source:** code-reviewer pass on the TimelineAPI consolidation, 2026-07-14

1. **Always-empty first-session delta fields.** `TimelineAPI.calculate_session_changes` (`src/api/timeline_api.py`) returns `new_categories: []` and `category_changes: []` only in the `previous is None` branch — always empty, never populated, and absent from the non-first branch (asymmetric key set). The frontend (`_site/run_timeline.html`) does not read them. Verbatim from the pre-consolidation script; removing them diverges from the snapshot-parity baseline, so fold into a future change that intentionally re-records that baseline.
2. **3N+1 DB connections per document.** `TimelineAPI.generate_document` opens a fresh `shared.db_utils.db_connection` for each of the three per-session enrichments plus one for cumulative stats — 3N+1 connection cycles for N sessions. Pre-existing from the script and negligible at realistic session counts; if it ever matters, thread one connection through the enrichment methods.
3. **No test for a present-but-schemaless DB.** The missing-DB path is now guarded and tested (`1d495ed`), but a DB file that exists yet lacks the `organization_sessions`/`files`/`categories` tables still raises a raw `sqlite3.OperationalError`. Add a test (and optionally a friendlier error) if this becomes a real failure mode.

### `regenerate_schemas.py` mirrors the src generator import list

**Status:** Open
**Priority:** P4
**Source:** scripts↔src code-duplication audit, 2026-07-13

`scripts/regenerate_schemas.py:27-37` re-lists the seven generator classes that `src/__init__.py:13-20` already exports, importing them from `generators` via a `sys.path` insert. Harmless today; importing from the `src` package (`from src import DocumentGenerator, ...`) would remove the parallel list. Fold into any future touch of the script rather than picking up standalone.

### `generate_schema` fidelity losses vs the retired legacy implementation

Two divergences found while re-pointing the golden snapshot tests from the legacy `scripts/file_organizer.py` to the live `FileProcessor.generate_schema` look like losses rather than intent — investigate and either restore or bless.

**Status:** Open — investigation
**Priority:** P2
**Source:** legacy-retirement session (golden re-record diff review), 2026-07-13

Migration context: the goldens originally pinned `scripts/file_organizer.py`'s `generate_schema` (per-type generator branches). When the pipeline layer moved into `src/`, the live implementation (`src/pipeline/file_processor.py:115`) kept only three branches — ImageObject, document types (DigitalDocument/Article/ScholarlyArticle/Report), and a generic fallback. The legacy script and its tests were deleted 2026-07-13; the re-recorded goldens (`tests/unit/golden/generate_schema/`, incl. `fallback_video_object.json`) now pin the current behavior, so resolving this either way will intentionally trip a snapshot.

1. **ImageObject lost `width`/`height`.** The legacy branch read PIL dimensions (`set_dimensions`); the live one doesn't. Dimensions may still reach the graph via the image-metadata path, but they're gone from the per-file JSON-LD.
2. **The type collapse.** VideoObject, AudioObject, SoftwareSourceCode, Dataset, Person, and Organization all fall to a bare `DocumentGenerator()` fallback that emits `@type: DigitalDocument` with only `name` + `description` (the legacy fallback at least had `encodingFormat`/`contentSize`/`url`). This is not hypothetical: `content_organizer.py:1054` still emits VideoObject/AudioObject and `category_config.py` maps whole subcategories to Organization — and `_persist_to_graph_store` stores `schema.get("@type")`, so **videos organized today are recorded in the graph as DigitalDocument**. The vCard parsing (`worksFor`, PostalAddress, name parts) also has no live equivalent; if it is restored, the deleted `_enrich_person_from_vcard`/`_enrich_organization_from_file` implementations and their tests are recoverable from git history (pre-2026-07-13).


