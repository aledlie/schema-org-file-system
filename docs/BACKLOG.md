# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-13.

## Open Items

### Person-graph edge hygiene

Leaky denylist (prune and dead-path tooling shipped 2026-07-12).

**Status:** Open — gaps 1 and 3 closed (prune tooling, `--prune-missing`); gap 2 remains.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

One remaining gap handles false-positive "people" in the symlink view.

1. **`get_all_people_with_files` denylist is leaky.** False-positive "people" (event/org names) still pass the org/keyword denylist — e.g. `Morning Train` (from `Burning_Flipside_Map.pdf`) — and would create spurious `Person/{Name}/` folders on `person-view --apply` unless pruned first.

   *Fix planned (2026-07-13):* layered local-only confidence gate at write time (`nameparser` shape → `probablepeople` CRF → Census gazetteer, weighted composite) with three-way routing (auto-accept / `pending_review` queue via a new `organize-files review-people` CLI / reject), `review_status`+`validation_scores` columns on `people`, and an `additionalProperty` JSON-LD sidecar. External KB validation rejected (notability gap — see the Wikidata item below). Full phased design: [`docs/plans/PERSON_NAME_VALIDATION_PLAN.md`](plans/PERSON_NAME_VALIDATION_PLAN.md).

### CLI argv re-serialization fragility

`src/cli.py` forwards subcommands by rebuilding `sys.argv` via `_args_to_argv` and re-parsing in the target script's `main()` (8 call sites: content, name, type, preprocess, evaluate, update-site, timeline, plus the script-side parsers).

**Status:** Open
**Priority:** P3
**Source:** thin-wrapper refactor session, 2026-07-13 (closes TEST_AND_REFACTOR_PLAN.md's superseded `workflow.py` item)

Outer/inner parser drift has already caused two real breakages — `organize-files name` and `organize-files type` both died on the `--sources` flag the outer CLI always forwards (fixed in `bac6306` and `773a20b`). Any new outer flag or dest rename can silently break a subcommand again.

Mitigation options when picked up:
1. Have `cmd_*` call typed entry points (e.g. `run(args)` functions on each target module) instead of argv strings, or
2. Add a parser-contract test that round-trips every subcommand's defaults through its inner parser (cheaper; `tests/integration/test_cli.py` already covers name/type/content/evaluate — extend to the remaining forwarded commands).

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

### `should_skip_file` copied into CLI-wired and legacy scripts

`ContentOrganizer.should_skip_file` (`src/organizers/content_organizer.py:1688-1710`) has two stale copies in `scripts/`.

**Status:** Open
**Priority:** P3
**Source:** scripts↔src code-duplication audit, 2026-07-13

`scripts/file_organizer_by_type.py:88-100` (wired into the CLI as `organize-files type`) carries a line-for-line copy of the skip rules (a second copy in the legacy `scripts/file_organizer.py` was deleted 2026-07-13). The copy lacks the browser save-page sidecar-folder rule (`SIDECAR_DIR_SUFFIXES`) that was added to the canonical version, so `organize-files type` still descends into `*_files/` asset folders. Action: extract the skip logic to a single shared home (e.g. `scripts/shared/file_ops.py` or a base organizer) and have all three call sites reuse it.

### Retire or delegate legacy `scripts/file_organizer.py`

The pre-refactor standalone organizer is not referenced by the CLI and duplicates logic that now lives in `src/`.

**Status:** Done — deleted 2026-07-13 (legacy-retirement session)
**Priority:** P3
**Source:** scripts↔src code-duplication audit, 2026-07-13

Deleted along with its test suite. Unique-behavior porting before deletion: the golden snapshot tests were re-pointed at `FileProcessor.generate_schema` (the live implementation), `mime_classifier` gained a direct suite (`tests/unit/test_mime_classifier.py` — it was previously only tested through the legacy class), and the exhaustive `get_schema_type_from_mime` table moved to `test_storage_models.py`. Behavior the legacy script had that the live pipeline does NOT is tracked in the "generate_schema fidelity losses" item below.

### Filename-collision handling has three divergent implementations

Duplicate-destination collisions are resolved differently depending on which organizer runs.

**Status:** Open
**Priority:** P3
**Source:** scripts↔src code-duplication audit, 2026-07-13

Three implementations coexist: timestamp suffix (`src/organizers/content_organizer.py:1680-1684`; a copy in the legacy `scripts/file_organizer.py` was deleted 2026-07-13), incrementing counter (`src/organizers/name_organizer.py:603-607`), and the existing shared utility `resolve_collision` (`scripts/shared/file_ops.py:15`). The same input file can therefore get a different collision name depending on the CLI subcommand. Action: consolidate all call sites on `resolve_collision` (or one chosen policy) so collision naming is uniform.

### `_persist_to_graph_store` wrapper signature/docstring drift risk

The thin CLI wrapper repeats the full 12-parameter signature and docstring of the `src/` implementation it delegates to.

**Status:** Open
**Priority:** P4
**Source:** scripts↔src code-duplication audit, 2026-07-13

`scripts/file_organizer_content_based.py:226-261` duplicates the signature and the "This method creates:" docstring of `src/pipeline/file_processor.py:190-215` before delegating. Delegation is the intended thin-wrapper pattern, but the copied docstring/signature will silently drift when parameters change. Action: slim the wrapper docstring to a one-line "delegates to FileProcessor._persist_to_graph_store" pointer, or forward `**kwargs`.

### OCR availability probe duplicated between wrapper and organizer

The try/except OCR dependency probe (pypdf/PIL/HEIC registration) exists in two places.

**Status:** Open
**Priority:** P4
**Source:** scripts↔src code-duplication audit, 2026-07-13

`scripts/file_organizer_content_based.py:29-47` and `src/organizers/content_organizer.py:35-58` each run their own availability probe and compute a separate `OCR_AVAILABLE`. A dependency added to one probe but not the other makes the two flags disagree. Action: single-home the probe (e.g. expose `OCR_AVAILABLE` from `shared.ocr_classifier`) and import it in both.

### Image metadata extraction in scripts/ vs src/

Image EXIF/GPS extraction in `scripts/image_renamer_metadata.py` parallels `src/analyzers/image_metadata.py`.

**Status:** Open
**Priority:** P3
**Source:** scripts↔src code-duplication audit, 2026-07-13

`scripts/image_renamer_metadata.py:79-127` implements `extract_exif_data`, `extract_datetime`, and `extract_gps_coordinates` in parallel to the canonical `src/analyzers/image_metadata.py:65-106` (note: `image_metadata.py`, not `image_analyzer.py`). The implementations have already drifted (differing signatures and return types). Action: port any script-only behavior into `src/analyzers/image_metadata.py` and make the renamer import it.

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


