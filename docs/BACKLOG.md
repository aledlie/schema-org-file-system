# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-01.

## Open Items

### [P1 / SECURITY] Scrub driver's-license PII from git history before any push

**Status:** Done (2026-07-01) — `git filter-repo --invert-paths` removed both blobs; verified `git rev-list --all --objects` finds no `460014` objects and no commit references them. History rewritten (all SHAs changed); first push is a force-push.
**Priority:** P1 (biometric PII in version-control history)
**Source:** test-set augmentation, 2026-07-01
**Context:** `results/test_set_augmentation/redacted/460014_alyshia_mledlie_p1.png` and `_p2.png` are a **driver's license**. OCR-based redaction (`scripts/redact_pii.py`) blacked out digits/name but **cannot remove the biometric face photo or physical description** — non-text PII is outside the tool's reach. The files were removed from the working tree in commit `1eacc17`, but the blobs still exist in history at commit `faf8586`. `main` has **never been pushed** (origin is at `ff6e6c4`), so the PII has not left the machine — but it must be scrubbed before the first push.

**Fix (run when the checkout is quiet — history rewrite changes all SHAs; do not run with concurrent Claude sessions active):**
```
git filter-repo --invert-paths \
  --path results/test_set_augmentation/redacted/460014_alyshia_mledlie_p1.png \
  --path results/test_set_augmentation/redacted/460014_alyshia_mledlie_p2.png
```
(or drop the two files from `faf8586` via interactive rebase). Verify with `git log --all --oneline -- 'results/test_set_augmentation/redacted/460014*'` returning nothing.

**Root-cause note — `redact_pii.py` blind spots** (also in CLAUDE.md Gotchas): OCR redaction cannot remove (a) **biometric photos** (driver's license, passport), (b) **OCR-unreadable stylized text** (the certificate was excluded for a machine-invisible but human-readable name), or (c) **alphabetic PII** (addresses, third-party names). Never commit such documents on OCR-redaction alone.

### Core-query export path in SchemaOrgExporter

**Status:** Done (2026-07-12) — `SchemaOrgExporter(use_core=True)`, now the **default**. Byte-identical to the ORM path (both share the `build_*_jsonld` pure builders in `models.py`), parity-locked by `tests/integration/test_core_export_parity.py`.
**Priority:** P3 (perf)
**Source:** export-perf investigation, 2026-07-12
**Context:** ORM bulk export cost is dominated by per-entity ORM object construction, not serialization or JSON encoding (a fresh 10k-entity export ≈ 0.5–0.8s cold, ~90% of it ORM hydration). `_collect_records_core` bulk-selects columns + association tables and builds JSON-LD via the shared functions, skipping ORM instantiation.

**Prototype caveat — now RESOLVED:** the original prototype covered only the *no-relation File* path. The shipped production version handles the relationship joins/aggregation for categories/companies/people/locations **and** File image/GPS fields (plus Category parent/subcategory), with full ORM parity. As predicted, relationship loading adds cost — measured **3.2× faster** than ORM (vs the 12× column-only microbenchmark ceiling): relationships add cost but stay **far below per-object ORM hydration**.

**Follow-up perf work — DONE (2026-07-12):**
- **Streaming exports:** `export_to_file`/`export_to_ndjson`/`export_with_graph`/`export_entities_filtered` write incrementally via `_stream_array` + a lazy `_iter_records` generator; the File path selects **columns** (lightweight `Row`s, no ORM File construction) and fetches with `yield_per`. Measured **9.4× less memory** — flat ~5.8 MB regardless of file count vs 54 MB that scaled with N (removes the 265k-export OOM risk). Column-select also lifted speed further (`get_graph_document[1k]` 22.8→16.3ms).
- **Subset-scoped refs:** `_load_file_refs(file_ids=…)` scopes the association query + loads only referenced targets for filtered exports; full exports load targets unfiltered (an `IN()` over every referenced id would exceed SQLite's bound-param limit).
- **Filtered export via Core:** `export_entities_filtered` now routes File/Company/Person/Location through the Core path (File with subset-scoped refs). Parity locked by new tests in `test_core_export_parity.py`.

**Residual caveats (still open):**
- Relationship-order parity depends on association rows being read in natural (insertion) order so the first category becomes `mainEntityOfPage`. Guarded by the parity test — do **not** add `ORDER BY` to `_load_file_refs` without re-verifying parity.
- `export_entities_filtered` for **Category** and unknown entity types still uses the ORM path (Category needs parent/subcategory refs; ORM output is identical).
- Categories are loaded fully in `_iter_core_category_records` (a first pass resolves parent/subcategory refs) — fine at current category counts, not stream-safe if categories ever reach file-scale.
- `to_schema_org()` methods are thin delegators to the shared builders — edit the builders, not the methods, or the two paths diverge.

### Test set class imbalance in model evaluation

**Status:** Reframed (2026-07-01) — original premise was wrong; residual work is classifier accuracy + coverage, not sample count.
**Priority:** P3
**Source:** model-evaluation session, 2026-05-16; investigated 2026-07-01
**Original context:** Classes with ≤2 samples scored 0% F1; assumed a test-set support-starvation issue.

**2026-07-01 investigation findings:**
- The old `evaluate_model.py` ran only the **filename-heuristic baseline** (`FileCategorizationModel`), which has *no code path* to medical/financial/personal/property/business — so those classes scored 0% regardless of sample count. Fixed by adding `--classifier content` (runs the production `ContentBasedFileOrganizer` CLIP+OCR pipeline).
- Test-set label vocabulary **already matches** the production classifier (verified by set-diff against the full production vocab). Earlier "taxonomy mismatch" reports (`financial→media`, `medical→game_assets`) were **misclassifications**, not label problems.
- `filepath` **is** a valid production category (the filepath-matching stage emits it); do not treat it as alien vocab.
- Insurance cards classify as `medical`/`insurance` (not `identification`); an intermediate relabel to `identification` was reverted. `fonts` and `research` samples were verified to classify correctly under `--classifier content`.

**Remaining work (real, not sample count):**
1. **Classifier accuracy — partially done (2026-07-01, commit `3ac3b9c`).** The root cause was **not** CLIP treating documents as generic images; it was (a) filename-keyword collisions routing document rasters before OCR runs, and (b) `enhance_weak_image_classification` bailing before consulting OCR whenever CLIP was weak.
   - **Fixed — medical → `game_assets`:** `medellin_bloodwork` matched the game sprite keyword `blood` (Priority 3) so OCR never ran. New `_ocr_document_override` lets clean, high-confidence OCR that classifies as a document category override the ambiguous game-asset `textures` guess, and `enhance_weak_image_classification` now consults OCR even when CLIP is weak. `medellin_bloodwork` now → `medical`. Covered by `tests/unit/test_ocr_document_override.py`.
   - **Not a code bug — financial → `media`:** the redacted `my_documents_usaa` sample's OCR is destroyed by over-redaction (`PAGE 1 48 65 90A CIC USAA…`) and legitimately classifies as `legal`. Needs a **less-destructively-redacted financial sample**, not a routing change.
   - **New sub-thread:** `email_…lab` (medical) → `person` because the ID stage (Priority 3.5) over-matches `date of birth`; resolves under the Option C person-taxonomy work above.
2. **Coverage gaps** — `identification` now covered (2026-07-01) by a **fully synthetic specimen** (`scripts/generate_specimen_id.py` → `results/test_set_augmentation/redacted/specimen_drivers_license.png`; fabricated data, no biometric PII — replaces the removed real DL). It classifies as `personal/identification` (main category `personal`), so test-label-vs-prediction hinges on the Option C taxonomy decision. `person` and `other` still have **no** test samples. `fonts` and `research` were added 2026-07-01.
3. **Option 2 — done (2026-07-01)** — `evaluate_model.py` now takes `--min-support` (default `DEFAULT_MIN_SUPPORT=5`). Classes below the threshold are moved to `low_support_categories` and excluded from both the printed per-class table and the new `macro_avg_supported` metric, so a 1-2 sample class no longer shows a misleading 0% F1 or drags the headline number. Per-class entries carry a `reported` flag; full raw metrics are still retained in `per_category_metrics`.

**Affected:**
- `scripts/file_organizer_content_based.py` — `_ocr_document_override` + OCR-when-CLIP-weak (commit `3ac3b9c`)
- `scripts/evaluate_model.py` (content classifier path — done; metric filtering — done)
- financial test-sample re-redaction (test data, not code)

### Implement Option C — demote `person` from a category to a relationship — DONE (2026-07-12)

**Status:** ✅ Done (2026-07-12) — implemented per [`PERSON_TAXONOMY_OPTION_C_PLAN.md`](../PERSON_TAXONOMY_OPTION_C_PLAN.md).
**Priority:** P3 (resolves the `person`/`personal` convention below)
**Source:** person/personal taxonomy reconciliation, 2026-07-01

**Summary:** `person` is no longer emitted as a top-level category; every file is classified by document class (`personal/{contacts,employment,identification,certificates,other}`), and `Person/{Name}/` is now a derived symlink view regenerated from the `file→person` graph edges.

**What shipped:**
- **Classification:** all `person`-category returns remapped to `personal` in `scripts/shared/filename_classifier.py` (9 sites), `scripts/file_organizer_content_based.py` (`classify_by_person`, `_classify_identification_document`), and the dormant `src/organizers/content_organizer.py`. New `personal/contacts` subcategory (resume/CV/vCard) added to both `ContentClassifier` copies. Person→personal subcat mapping centralized in `_PERSON_SUBCAT_TO_PERSONAL_SUBCAT`.
- **Routing:** `person` folder maps and `get_destination_path` person branches removed from both organizers; `Personal/Contacts` added to the `personal` map.
- **Graph:** `GraphStore.get_all_people_with_files` / `get_files_by_person` reverse queries (with false-positive-name denylist).
- **View:** new `src/storage/person_view_generator.py` (`PersonViewGenerator`, idempotent symlink regen, aborts on real files under the view root) wired to `organize-files person-view [--view-root] [--apply]`.
- **Migration:** new `src/storage/person_migration.py` (filesystem-walk driven, dry-run default, collision-safe, manifest-backed rollback, no re-OCR) wired to `organize-files migrate-person [--apply] [--rollback]`.
- **Tests/docs:** `test_content_organizer.py` assertions updated; new tests for filename mapping, graph queries, `PersonViewGenerator`, and `person_migration`; `CLAUDE.md` Classification Priority + Output Folders updated. Full suite green (pre-existing `jsonschema`-missing failures unrelated). Plan step-7 grep confirms no filing-category `person` label remains (only entity/schema.org/vision-vocab usages).

**Operational note:** `migrate-person --apply` was run against real data (2026-07-12): 33 files moved into `Personal/{subcat}/`, `~/Documents/Person/` emptied of real files. `person-view --apply` (symlink regen) is the only remaining on-disk step and is left for the user to run.

### Person-view population — `index-people` graph edges + filename fallback — DONE (2026-07-12)

**Status:** ✅ Done (2026-07-12). Follows the Option C migration above.
**Priority:** P3 (makes the `Person/{Name}/` symlink view actually populate)
**Source:** post-migration session, 2026-07-12

**Why not just re-run `content`:** re-running `organize-files content` over `~/Documents/Personal` to create `file→person` edges was rejected — the classifier re-derives from content and (dry-run confirmed) would relocate **6 of 33** files to worse spots (resume `.webp` → `Financial`/`Legal`, DUI PDFs → `Property`/`Uncategorized`), degrading the migration's trustworthy folder-based placement. Only 15/33 files even have a detected person.

**What shipped instead:** `organize-files index-people [--manifest] [--person-root] [--apply]` (dry-run default) in `src/storage/person_migration.py`. Derives person attribution from the migration manifest's `src` (the user's original `Person/{Name}/` filing) and writes `File` rows + person edges at each file's **current** `Personal/` path — no file moves, no re-OCR/CLIP. Idempotent (`add_file` upserts, `add_file_to_person` no-ops duplicate edges).

**Attribution review (7 originally-unattributed files):** only one had a recoverable person without OCR — `RESUME1-ChynaStrange.pdf` (**Chyna Strange**, name in the CamelCase filename). The other six are false-positive traps: `Resume-Blue`/`Resume-Orange` (template colors), `MarketingTemplate`/`PAS-PartTime` (generic/program names), a wage-calculator `.xlsx`, and `unnamed (1).jpg`. Added a conservative filename fallback to `build_person_index` (tried only when no name dir matches): gated to resume/CV filenames, requires two adjacent proper-case tokens (CamelCase-aware), stopword-filtered (resume/template/color). Extracts Chyna Strange, rejects all six false positives. A 9-case parametrized test pins the rejections; name-dir attribution still takes precedence.

**Also fixed this session** (correctness surfaced by the first real runs):
- `migrate-person` and `person-view` skip OS junk (`.DS_Store`/`Thumbs.db`/AppleDouble) via a single shared `shared.file_ops.is_os_junk_file`, so leftover junk under `Person/` doesn't trip the view's real-file abort guard.
- `person-view` excludes graph rows whose `current_path` no longer exists from the dry-run count and reports them (was overstating symlinks that apply would never create; `_write_view` already skipped them). 8 stale rows (files deleted in the P1 PII scrub above) are correctly skipped, not turned into dangling links.

**Result on the real tree:** attribution 27/33 (Alyshia Ledlie 23, Isabel Budenz 2, Chyna Strange 1, Kenneth Reitz 1); `index-people --apply` wrote 27 edges; `person-view` dry-run now reports 27 symlinks across 5 people. Remaining 6 files have no person identifiable without OCR (deliberately avoided). Full suite: 858 passed, 2 skipped.

### Reconcile `person` vs `personal` category convention

**Status:** Superseded by the Option C plan above (chosen convention: demote `person` to a relationship).
**Priority:** P3 (taxonomy ambiguity; causes avoidable eval misses)
**Source:** test-set / classifier alignment, 2026-07-01
**Context:** The production classifier can emit **both** `person` and `personal` as a file's main category, from two different stages of `detect_file_category`:
- **Person entity detection** (Classification Priority #2) fires first for name-bearing documents (resumes, signatures, contact info) → returns `person`.
- **Content classification** (`content_classifier.py`, later stage) has a `personal` document category → returns `personal` when no person entity is detected.

Because Person detection runs earlier and wins, a personal document that names an individual is labeled `person`, while an equivalent one without a detectable name is labeled `personal`. The split is an artifact of stage ordering, not a meaningful semantic distinction, and it produces avoidable evaluation misses (test label `personal` vs prediction `person`).

**Proposed fix (define a convention):**
1. Decide the canonical taxonomy: either (a) **merge** — treat `person` as the entity/owner and `personal` as the document class, and have the evaluator map one to the other; or (b) **keep distinct** with an explicit rule (e.g., `person` = files attributable to a specific named individual; `personal` = personal-life documents with no identified person) and relabel the test set accordingly.
2. Document the chosen convention in `CLAUDE.md` (Classification Priority) and apply it consistently in `content_classifier.py` and any test-set labels.
3. Add an evaluator alias/mapping layer if (a) is chosen so `person`/`personal` are scored consistently.

**Affected:**
- `src/classifiers/content_classifier.py` (category vocabulary)
- `scripts/file_organizer_content_based.py` (`detect_file_category` stage ordering)
- `CLAUDE.md` (Classification Priority documentation)
- test-set labels + `scripts/evaluate_model.py` (optional alias mapping)

### Migrate storage timestamps to timezone-aware datetimes

**Status:** Won't do (documented) — revisit only if a tz-aware DB backend (e.g. Postgres) is added.
**Priority:** P4 (no active bug; no benefit on the current backend)
**Source:** datetime.utcnow deprecation fix, 2026-06-27; audited 2026-07-01
**Context:** `datetime.utcnow()` was deprecated on Python 3.12+. The fix introduced `src/storage/_time.py::utcnow()` returning a **naive** UTC datetime as a behavior-preserving drop-in. It is used consistently across the storage layer (`models.py`, `graph_store.py`, `kv_store.py`, `migration.py`) — no stray `datetime.utcnow()` remains. The deprecation warning is gone and timestamps are naive-but-consistent.

**Audit finding (2026-07-01) — why this is closed:** the store is **SQLite-only** (`create_engine('sqlite:///…')` in `graph_store.py` and `kv_store.py`). SQLite has no native timezone type, so SQLAlchemy `DateTime(timezone=True)` is a **no-op** there — it does not persist tzinfo and returns **naive** datetimes on read. Flipping the column type buys nothing. Flipping `_time.py` to aware *without* a read-side coercion layer is a regression, not a cleanup: a fresh aware `utcnow()` compared against a DB-loaded naive `expires_at` raises `TypeError: can't compare offset-naive and offset-aware` in the `kv_store.py` TTL paths (lines ~117, 223, 600, 674, 743). The naive helper is the correct pragma for a single-backend SQLite store; aware UTC buys nothing until the backend changes.

**Corrections to the earlier proposed fix (now superseded):**
- Golden snapshots do **not** need updating — `test_generate_schema_golden.py::_VOLATILE_KEYS` already normalizes `dateCreated`/`dateModified`/`uploadDate` to `<normalized>` before diffing.
- `tests/unit/test_base.py` date assertions feed **explicit input datetimes**, not `utcnow()`, so they are unaffected.
- The plan omitted the one step that actually matters on SQLite: a `TypeDecorator` (`UtcDateTime`) coercing naive→aware(UTC) on every read.

**If revisited (Option B — only with a tz-aware backend):**
1. Add a `UtcDateTime` `TypeDecorator` that coerces naive→aware(UTC) on read; apply to all `DateTime` columns.
2. Switch `_time.py::utcnow()` to `datetime.now(timezone.utc)` (aware).
3. Audit `timeline_api.py:308` and `organized_at`/`started_at`/`completed_at` isoformat consumers for the added `+00:00` suffix.
4. No data-rewrite migration needed — read-side coercion handles legacy naive rows.

**Secondary (pre-existing, low risk):** `migration.py:271` sets `exif_datetime = datetime.fromisoformat(...)`, which is aware or naive depending on the EXIF string. Output-only (never compared), so an inconsistency, not a live bug.

**Affected (if revisited):**
- `src/storage/_time.py` (aware return)
- `src/storage/models.py` (column types + `UtcDateTime` TypeDecorator)
- `src/storage/kv_store.py` (comparison/arithmetic audit)
- `src/api/timeline_api.py` + any JSON-LD output consumers (offset format change)


