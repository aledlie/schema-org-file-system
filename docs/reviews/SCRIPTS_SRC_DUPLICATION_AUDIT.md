# scripts/ vs src/ Code-Duplication Audit

**Date:** 2026-07-14
**Method:** multi-agent workflow — 21 finder agents (one per script group, every `scripts/**/*.py` plus `scripts/d1/schema.sql` read in full), one adversarial verifier per finding, completeness critic with a gap re-audit round. 85 agents total; every finding below was independently confirmed against both files with line-level evidence. 2 candidates were refuted and are listed at the end.
**Scope:** code in `scripts/` duplicating logic already covered by the canonical library in `src/`. Imports, delegation, launcher blocks, and backwards-compat re-exports were excluded by design.

**Result: 53 confirmed findings** (5 high, 45 medium, 3 low), grouped into 7 duplication zones below.

**Structural note that keeps this list honest:** `src/` imports heavily *from* `scripts/shared` (`GAME_SPRITE_KEYWORDS`, `SCREENSHOT_KEYWORDS`, `SCREENSHOT_PATTERNS`/`DOCUMENT_PATTERNS`, `IMAGE_EXTENSIONS_WIDE`, `classify_by_ocr`, `kie_*` are single-sourced via `from shared.x import y`). Those were spot-checked and are shared single sources, not copies — everything listed below is a genuine second implementation or second data table.

## Recommended priority order

1. Consolidate the timeline exporter (or delete the orphaned `TimelineAPI` export path) — two writers emit incompatible schemas to the same `_site/timeline_data.json`.
2. Fix `regenerate_schemas.py` metadata-dropping drift (regeneration silently loses ScholarlyArticle/CLIP properties src now emits).
3. Single-home the game keyword tables (union the bidirectional fixes; re-run the eval).
4. Auto-generate `scripts/d1/schema.sql` from `Base.metadata` (whole `merge_events` table is missing).
5. The rest opportunistically, when the owning script is next touched.

## Timeline generation — `scripts/generate_timeline_data.py` vs `src/api/timeline_api.py`

Both sides build and write the same artifact `_site/timeline_data.json` with already-incompatible output schemas. The live code path is the script (`src/cli.py:230`, `scripts/update_site_data.py:163`); `TimelineAPI` has zero code references outside its own file — a dead parallel implementation whose own `main()` would clobber the dashboard data file with a divergent document. Consolidate to one exporter: either fold the script-only enrichments into `TimelineAPI` and reduce the script to a launcher (matching the repo's launcher refactors), or delete the orphaned `TimelineAPI` export path.

### [HIGH] get_sessions

- **Kind:** diverged-copy
- **Script:** `scripts/generate_timeline_data.py:18-67`
- **Src counterpart:** `src/api/timeline_api.py:36-106` — `TimelineAPI.get_all_sessions (+ _calculate_success_rate, 275-282)`
- **Evidence:** Same organization_sessions SELECT column set (id, started_at, completed_at, dry_run, total_files, organized_count, skipped_count, error_count, total_cost, total_processing_time_sec, source_directories, base_path); near-verbatim source_directories parse: script 49-55 "session['source_directories'] = json.loads(session['source_directories'])" with JSONDecodeError -> [] vs src 76-82 identical logic; same success-rate formula "round((organized_count / total_files) * 100, N)" (script 59-61, src 280-282).
- **Divergence:** Script adds WHERE total_files > 0, ORDER BY started_at ASC, file_limit column, id_short, rounds success_rate to 1 decimal, and also catches TypeError; src orders DESC, aliases total_processing_time_sec as processing_time, rounds to 2 decimals, and adds files_per_second/cost_per_file enrichment.
- **Recommendation:** Fold the script's WHERE/ordering/id_short needs into TimelineAPI.get_all_sessions (e.g. flags/params), then have get_sessions delegate to it; pick one rounding precision.

### [HIGH] generate_timeline_data + run

- **Kind:** reimplementation
- **Script:** `scripts/generate_timeline_data.py:193-237`
- **Src counterpart:** `src/api/timeline_api.py:298-318` — `TimelineAPI.export_to_json`
- **Evidence:** Both build {generated_at: ...isoformat(), sessions: [...], aggregate/cumulative stats} and write the SAME artifact _site/timeline_data.json via identical tail: parent.mkdir(parents=True, exist_ok=True) then json.dump(data, f, indent=2, default=str) (script 231-233 with OUTPUT_PATH = _site/timeline_data.json at line 15; src 311-315 with default output_path="_site/timeline_data.json" at 298).
- **Divergence:** Document keys differ ('cumulative' + 'session_count' vs 'aggregate_stats'); script uses datetime.now(), src uses utcnow(); script enriches sessions with extensions and consecutive-session changes that src lacks. Note: the CLI (src/cli.py:227-232 cmd_timeline) uses the script; TimelineAPI has zero code references (docs only).
- **Recommendation:** Consolidate to one exporter: move script-only enrichment (extensions, consecutive changes) into TimelineAPI, standardize the output document, and reduce scripts/generate_timeline_data.py to a launcher over src/api/timeline_api.py (matching the repo's recent launcher refactors); or, if the script's format is canonical, delete the unused TimelineAPI export path so only one thing writes _site/timeline_data.json.

### [HIGH] run / OUTPUT_PATH

- **Kind:** reimplementation
- **Script:** `scripts/generate_timeline_data.py:15, 218-237`
- **Src counterpart:** `src/api/timeline_api.py:298-318` — `TimelineAPI.export_to_json`
- **Evidence:** Both write the same output artifact _site/timeline_data.json with json.dump(data, f, indent=2, default=str) after parent.mkdir(parents=True, exist_ok=True), embedding a generated_at ISO timestamp (script OUTPUT_PATH line 15 and run() lines 229-233; src output_path default "_site/timeline_data.json" lines 298, 311-315).
- **Divergence:** Payload shape differs: script writes {generated_at, cumulative, sessions (with changes/extensions), session_count}; src writes {sessions, aggregate_stats, generated_at}. src also accepts a configurable output_path; the script's is a module constant. organize-files timeline currently runs the script version, so two divergent generators target the same file.
- **Recommendation:** Consolidate on TimelineAPI.export_to_json: fold the script's payload additions (changes, extensions, cumulative naming) into TimelineAPI, reduce scripts/generate_timeline_data.py to a pure launcher over it (or point src/cli.py cmd_timeline at src/api/timeline_api.py directly), verifying the _site frontend against the unified JSON shape.

### [MEDIUM] get_session_schema_types

- **Kind:** diverged-copy
- **Script:** `scripts/generate_timeline_data.py:94-109`
- **Src counterpart:** `src/api/timeline_api.py:248-273` — `TimelineAPI._get_schema_type_distribution`
- **Evidence:** Token-identical SQL on both sides: "SELECT schema_type, COUNT(*) as count FROM files WHERE session_id = ? AND schema_type IS NOT NULL GROUP BY schema_type ORDER BY count DESC" (script 100-108, src 261-268).
- **Divergence:** src adds LIMIT 10; script returns list[dict] rows while src returns a {schema_type: count} dict.
- **Recommendation:** Keep one query in src/api/timeline_api.py (parameterize the limit/shape) and have the script call it instead of re-running its own SQL.

### [MEDIUM] get_session_categories

- **Kind:** partial-overlap
- **Script:** `scripts/generate_timeline_data.py:70-91`
- **Src counterpart:** `src/api/timeline_api.py:220-246` — `TimelineAPI._get_category_distribution`
- **Evidence:** Same per-session category-count query over the same 3-table join: script 76-90 "JOIN file_categories fc ON c.id = fc.category_id JOIN files f ON fc.file_id = f.id WHERE f.session_id = ? ... ORDER BY count DESC" vs src 233-241 "JOIN file_categories fc ON f.id = fc.file_id JOIN categories c ON fc.category_id = c.id WHERE f.session_id = ? ... ORDER BY count DESC".
- **Divergence:** Script also selects c.color, c.icon, AVG(fc.confidence), GROUP BY c.id, LIMIT 10 and returns list[dict]; src counts DISTINCT f.id, GROUP BY c.name, no limit, returns {name: count} dict.
- **Recommendation:** Extend TimelineAPI._get_category_distribution to optionally return color/icon/avg_confidence and a limit, then have the script delegate to it.

### [MEDIUM] calculate_session_changes

- **Kind:** partial-overlap
- **Script:** `scripts/generate_timeline_data.py:131-152`
- **Src counterpart:** `src/api/timeline_api.py:124-159` — `TimelineAPI.get_session_comparison`
- **Evidence:** Both compute the same inter-session deltas: total_files difference (script 144 "current['total_files'] - previous['total_files']" vs src 147 "session2['total_files'] - session1['total_files']"), organized_count difference (script 145, src 148), rounded success_rate delta (script 146 round(...,1), src 153-155 round(...,2)), rounded total_cost delta (script 147 round(...,4), src 150-152 round(...,2)).
- **Divergence:** Script adds is_first handling and time_delta (processing-time difference); src adds error_count delta and wraps both full session dicts; rounding precisions differ (1/4 vs 2/2).
- **Recommendation:** Extract one delta helper in src (session_a, session_b -> deltas dict with configurable precision) used by both get_session_comparison and the script's timeline changes.

### [MEDIUM] get_cumulative_stats

- **Kind:** partial-overlap
- **Script:** `scripts/generate_timeline_data.py:155-190`
- **Src counterpart:** `src/api/timeline_api.py:174-218` — `TimelineAPI.get_aggregate_stats`
- **Evidence:** Both produce cross-session aggregates with total_sessions, total files, total organized, avg processing metric, plus a category-count breakdown: script 160-188 does it in SQL (COUNT(DISTINCT session_id), SUM(CASE WHEN status='organized'...), top-5 categories query); src 194-218 sums the same fields in Python over get_all_sessions() (total_files, total_organized, category_breakdown via defaultdict).
- **Divergence:** Field sets drift: script has avg_processing_time and top_categories (LIMIT 5); src adds total_cost, average_success_rate, total_processing_time, dry_run_count/live_run_count and a full category_breakdown; script aggregates at the files level in SQL, src at the session level in Python (results can differ, e.g. organized counted per-file status vs per-session organized_count).
- **Recommendation:** Pick one aggregate source of truth in src/api/timeline_api.py (superset of both field sets) and have the script's cumulative block delegate; reconcile the file-level vs session-level counting discrepancy while merging.

## Schema regeneration — `scripts/regenerate_schemas.py` vs `FileProcessor.generate_schema`

Diverged copy with verbatim shared lines (`file_url = f"https://localhost/files/{quote(...)}"` occurs exactly twice in the repo — once on each side). Drift already bites: the script's `preserve_keys` list omits `identifier`/`sameAs`/`publisher`/`description`, so regenerating schemas silently drops the ScholarlyArticle and CLIP metadata that src now emits. Extract a shared schema-builder in src with optional `entity_id`/preserve-keys parameters and have the script delegate. Related backlog item: the script also mirrors the src generator import list.

### [HIGH] regenerate_schema

- **Kind:** diverged-copy
- **Script:** `scripts/regenerate_schemas.py:66-154`
- **Src counterpart:** `src/pipeline/file_processor.py:129-203` — `FileProcessor.generate_schema`
- **Evidence:** Both sides contain the identical line `file_url = f"https://localhost/files/{quote(file_path.name)}"` (script:100 / src:138 — the only two occurrences in the repo), the identical ImageObject branch `set_property('contentUrl', file_url, PropertyType.URL)` + `'encodingFormat', mime_type or 'image/png'` (script:104-111 / src:143-148), the identical document branch `mime_type or 'application/octet-stream'` + `set_property('contentSize', f"{stats.st_size}B", PropertyType.TEXT)` (script:120-129 / src:153-157), identical `generator.set_dates(created=datetime.fromtimestamp(stats.st_ctime), modified=datetime.fromtimestamp(stats.st_mtime))` (script:132-135 / src:180-183), and identical `generator.set_property('filePath', ..., PropertyType.TEXT)` (script:138 / src:199).
- **Divergence:** Script threads entity_id (canonical_id) into generators to emit @id, guards on file_path.exists(), uses raw file_path.stat() instead of src's cached_stat, and merges preserve_keys ('abstract','text','keywords','author','creator','width','height','duration','bitrate') from the existing DB schema. src version instead adds extracted-text abstract/text properties (truncated to 1000/5000 chars), ScholarlyArticle publisher/identifier/sameAs metadata, and a CLIP-derived description; src sets description unconditionally while the script conditions on truthiness.
- **Recommendation:** Extract a shared schema-builder in src (e.g. give FileProcessor.generate_schema — or a standalone function it calls — optional entity_id and existing_schema/preserve-keys parameters), then have regenerate_schemas.py delegate to it, keeping only the SQLite batch iteration and @id verification in the script.

### [MEDIUM] get_generator_for_type

- **Kind:** partial-overlap
- **Script:** `scripts/regenerate_schemas.py:39-63`
- **Src counterpart:** `src/pipeline/file_processor.py:142-176` — `FileProcessor.generate_schema (inline type-to-generator dispatch)`
- **Evidence:** Same schema_type-to-generator mapping: script maps 'ImageObject' -> ImageGenerator('ImageObject', ...) and 'DigitalDocument'/'Article'/'Report' -> DocumentGenerator(schema_type, ...) with default fallback `lambda: DocumentGenerator('DigitalDocument', ...)` (script:42-62); src's if/elif does `if schema_type == "ImageObject": generator = ImageGenerator(schema_type)` (src:143-144), `elif schema_type in ["DigitalDocument", "Article", SCHOLARLY_ARTICLE_SCHEMA_TYPE, "Report"]: generator = DocumentGenerator(schema_type)` (src:149-150), `else: generator = DocumentGenerator()` (src:173-174).
- **Divergence:** The script's dispatch table is a superset: it adds Photograph -> ImageGenerator, VideoObject/MovieClip -> VideoGenerator, AudioObject/MusicRecording/PodcastEpisode -> AudioGenerator, SoftwareSourceCode -> CodeGenerator, Dataset -> DatasetGenerator, Archive -> ArchiveGenerator, and passes entity_id to every constructor; src routes all of those types to the plain DocumentGenerator fallback and never sets entity_id.
- **Recommendation:** Promote the fuller dispatch (including video/audio/code/dataset/archive entries and the entity_id parameter) into src — e.g. a factory function in src/generators.py or src/pipeline/file_processor.py — have FileProcessor.generate_schema use it, and make the script import it instead of defining its own table.

### [MEDIUM] regenerate_schema (entity_id fallback expression)

- **Kind:** reimplementation
- **Script:** `scripts/regenerate_schemas.py:88-89`
- **Src counterpart:** `src/storage/models.py:254-258` — `File.get_iri (canonical-ID URN fallback; format also from File.generate_canonical_id lines 239-252, and inlined at models.py:792 and src/storage/migration.py:693)`
- **Evidence:** script:89 `entity_id = canonical_id if canonical_id else f"urn:sha256:{file_id}"` vs models.py:256-258 `if self.canonical_id: return self.canonical_id` / `return f"urn:sha256:{self.id}"`; same expression shape at models.py:792 `"@id": f.canonical_id or f"urn:sha256:{f.id}"` and migration.py:693 `canonical_id = f"urn:sha256:{file_id}"`.
- **Divergence:** None semantically — identical prefer-canonical_id-else-urn:sha256:{id} rule; the script writes it as a ternary over raw sqlite row values instead of calling the ORM method, so any future change to the URN scheme in models.py would silently desynchronize the script.
- **Recommendation:** Expose the rule as a small module-level helper in src/storage/models.py, e.g. `def file_iri(file_id, canonical_id=None): return canonical_id or f"urn:sha256:{file_id}"`, have File.get_iri (models.py:254-258) and build_file_jsonld (models.py:792) delegate to it, and import it in regenerate_schemas.py:89. The same helper also removes the src-internal repeat at src/storage/migration.py:693. Grep confirms no other scripts/ file inlines urn:sha256:/urn:uuid:, so this is the only script-side fix needed.

## Eval baseline — `scripts/evaluate_model.py` vs the production classifier cascade

`FileCategorizationModel` reimplements the predict cascade and game-subcategory split of `content_organizer.py` with different mechanics (token-ratio scoring vs substring matching), so the eval baseline silently disagrees with production per-file. Either delegate the game-subcategory mapping to `ContentOrganizer.classify_game_asset`, or explicitly document the model as a frozen baseline not expected to track production.

### [HIGH] FileCategorizationModel (predict_category cascade + _determine_game_subcategory)

- **Kind:** reimplementation
- **Script:** `scripts/evaluate_model.py:38-173 (cascade 47-102; game subcategory 149-173)`
- **Src counterpart:** `src/organizers/content_organizer.py:497-556 (cascade 1055-1290; game-asset priority 1174-1198; sprite/texture discriminator 190-198)` — `ContentOrganizer.classify_game_asset (+ detect_file_category priority cascade)`
- **Evidence:** Script docstring (line 39) states it 'Simulates the categorization logic from file_organizer_content_based.py' (now src/organizers). Both produce the identical label set from the same keyword families: script 154-161 checks audio extensions ['.wav','.ogg','.mp3'] against GAME_MUSIC_KEYWORDS/GAME_AUDIO_KEYWORDS returning 'music'/'audio', and 164-171 splits images into 'textures' vs 'sprites'; src 511-521 checks ['.wav','.ogg','.mp3','.flac','.aac'] against self.game_music_keywords/self.game_audio_keywords returning ('game_assets','music')/('game_assets','audio'), and 537-543 splits game_sprite_keywords matches into ('game_assets','sprites') vs ('game_assets','textures'). The script's Games parent-folder fallback (80-82) also self-documents as 'matches production's filepath priority stage in detect_file_category'.
- **Divergence:** Mechanics differ throughout: script uses a token-ratio game score (matches/len(tokens)*1.5, +0.1 boosts, 0.3 threshold) and a hardcoded texture_keywords list ['texture','wall','floor','tile','seamless','pattern']; src uses first-match substring checks, a _SPRITE_DISCRIMINATOR_KEYWORDS set, game-font/regex sprite patterns, and an OCR document override. Same behavior domain and output labels, but per-file decisions can disagree, so the eval baseline silently drifts from production.
- **Recommendation:** Keep the filename-only baseline as an intentional eval reference, but delegate the game subcategory mapping to ContentOrganizer.classify_game_asset (callable with just a Path built from the filename) so the sprite/texture/music/audio split cannot drift; alternatively, explicitly document FileCategorizationModel as a frozen baseline that is not expected to track production.

### [MEDIUM] FileCategorizationModel._matches_patterns (used with SCREENSHOT_PATTERNS/DOCUMENT_PATTERNS)

- **Kind:** near-identical-copy (no behavioral divergence; small helper duplicated + redundant recomputation of precomputed feature flags)
- **Script:** `scripts/evaluate_model.py:118-120 (uses at 61-63 and 72-73; imports at 17-20)`
- **Src counterpart:** `src/ml/feature_extractor.py:153-156 (feature uses at 87-89; import at 14)` — `FileFeatureExtractor._matches_patterns (+ is_screenshot/is_document features)`
- **Evidence:** Script: `def _matches_patterns(self, text, patterns): return any(re.search(p, text, re.IGNORECASE) for p in patterns)`; src: `def _matches_patterns(self, filename, patterns): filename_lower = filename.lower(); return any(re.search(p, filename_lower) for p in patterns)`. Both are applied to the same shared constants: script line 61 `self._matches_patterns(filename, SCREENSHOT_PATTERNS)` / line 72 `self._matches_patterns(filename, DOCUMENT_PATTERNS)` mirror src lines 87 `'is_screenshot': self._matches_patterns(filename, SCREENSHOT_PATTERNS)` and 89 `'is_document': self._matches_patterns(filename, DOCUMENT_PATTERNS)`.
- **Divergence:** Trivial drift only: script uses re.IGNORECASE on an already-lowercased filename, src pre-lowercases the filename — behaviorally equivalent for these lowercase patterns. The larger redundancy is that the test.json records the script consumes are produced by FileFeatureExtractor (via src/ml/data_preprocessor.py export_for_training, which writes test.json at line 305) and already contain precomputed 'is_screenshot' and 'is_document' booleans, which the script ignores and recomputes.
- **Recommendation:** Delete the local helper and read the precomputed feature fields (`feature['is_screenshot']`, `feature['is_document']`) that src/ml/feature_extractor.py already emits into every test record; if raw-pattern matching is still wanted, import FileFeatureExtractor._matches_patterns (or a module-level helper extracted from it) instead of keeping a copy.

## D1 DDL mirror — `scripts/d1/schema.sql` vs `src/storage/models.py`

Hand-maintained D1 DDL mirroring the ORM table-for-table, already stale: `files` is missing `ocr_confidence`, `detected_language`, `kie_fields`; the entire `merge_events` table (~18 columns) has no CREATE TABLE at all. Recommendation common to all rows: generate the DDL from `Base.metadata` (`sqlalchemy.schema.CreateTable(...).compile(dialect=sqlite)`) via a small generator invoked from `scripts/d1/export_to_d1.py`, so ORM columns can never silently drift out of the D1 schema.

### [MEDIUM] CREATE TABLE files

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:12-52`
- **Src counterpart:** `src/storage/models.py:136-231` — `class File`
- **Evidence:** SQL mirrors File column-for-column ('canonical_id TEXT UNIQUE NOT NULL, source_ids JSON, filename TEXT NOT NULL ... extracted_text TEXT, extracted_text_length INTEGER DEFAULT 0, schema_type TEXT, schema_data JSON' vs models.py canonical_id/source_ids/filename/.../extracted_text/extracted_text_length/schema_type/schema_data at lines 153-184), but stops at the pre-2.x column set.
- **Divergence:** SQL is missing three ORM columns added since it was written: ocr_confidence (models.py:179), detected_language (models.py:180), kie_fields (models.py:185). SQL also declares ix_files_session_id (schema.sql:52) which the ORM never defines (session_id at models.py:201 has no index=True).
- **Recommendation:** Stop hand-maintaining; regenerate schema.sql from Base.metadata (sqlalchemy.schema.CreateTable(...).compile(dialect=sqlite.dialect()) per table) via a small generator invoked from scripts/d1/export_to_d1.py or a make target, so ORM columns can never silently drift out of the D1 DDL.

### [MEDIUM] CREATE TABLE categories

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:55-75`
- **Src counterpart:** `src/storage/models.py:351-397` — `class Category`
- **Evidence:** SQL 'merged_into_id INTEGER, name TEXT UNIQUE NOT NULL, parent_id INTEGER, description TEXT, icon TEXT, color TEXT, level INTEGER DEFAULT 0, file_count INTEGER DEFAULT 0' matches models.py merged_into_id/name/parent_id/description/icon/color/level/file_count (lines 373-386) including the self-FKs to categories(id).
- **Divergence:** SQL is missing the indexed full_path column (models.py:383, 'e.g., Legal/Contracts'). SQL names the timestamps db_created_at/db_updated_at (schema.sql:67-68) but the ORM Category uses created_at/updated_at (models.py:389-390) — inserts targeting the ORM names would fail on the D1 table.
- **Recommendation:** Regenerate this CREATE TABLE from Base.metadata so full_path appears and timestamp column names match the ORM exactly.

### [MEDIUM] CREATE TABLE companies

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:78-93`
- **Src counterpart:** `src/storage/models.py:439-479` — `class Company`
- **Evidence:** SQL 'name TEXT NOT NULL, normalized_name TEXT UNIQUE NOT NULL, ... industry TEXT, file_count INTEGER DEFAULT 0, last_seen DATETIME' matches models.py name/normalized_name/industry/file_count/last_seen (lines 463-471); both index canonical_id and normalized_name.
- **Divergence:** SQL has 'website TEXT' (schema.sql:84) but the ORM column is domain (models.py:465). SQL is missing merged_into_id (models.py:461) and first_seen (models.py:470), and carries db_created_at/db_updated_at (schema.sql:88-89) which do not exist on the Company model at all.
- **Recommendation:** Regenerate from Base.metadata; the website-vs-domain rename alone means any column-name-driven export into this table breaks.

### [MEDIUM] CREATE TABLE people

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:96-111`
- **Src counterpart:** `src/storage/models.py:530-566` — `class Person`
- **Evidence:** SQL 'name TEXT NOT NULL, normalized_name TEXT UNIQUE NOT NULL, email TEXT, role TEXT, file_count INTEGER DEFAULT 0, last_seen DATETIME' matches models.py name/normalized_name/email/role/file_count/last_seen (lines 554-562).
- **Divergence:** SQL is missing merged_into_id (models.py:552) and first_seen (models.py:561); SQL's db_created_at/db_updated_at (schema.sql:106-107) have no counterpart columns on the Person model.
- **Recommendation:** Regenerate from Base.metadata so merge-tracking and first_seen columns exist in D1.

### [MEDIUM] CREATE TABLE locations

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:114-130`
- **Src counterpart:** `src/storage/models.py:633-680` — `class Location`
- **Evidence:** SQL 'name TEXT NOT NULL, latitude REAL, longitude REAL, city TEXT, state TEXT, country TEXT, file_count INTEGER DEFAULT 0' matches models.py name/city/state/country/latitude/longitude/file_count (lines 657-668).
- **Divergence:** SQL is missing merged_into_id (models.py:655), the indexed geohash column (models.py:665), and the composite indexes ix_locations_geo / ix_locations_city_state (models.py:678-679). ORM timestamp is created_at only (models.py:671); SQL has db_created_at/db_updated_at instead (schema.sql:125-126).
- **Recommendation:** Regenerate from Base.metadata to pick up geohash and the spatial composite indexes.

### [MEDIUM] CREATE TABLE file_categories / file_companies / file_people / file_locations

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:133-181`
- **Src counterpart:** `src/storage/models.py:96-133` — `file_categories / file_companies / file_people / file_locations association Tables`
- **Evidence:** Column lists match the four association Tables exactly: e.g. SQL file_companies 'confidence REAL DEFAULT 1.0, context TEXT' vs models.py Column('confidence', Float, default=1.0), Column('context', String(MAX_STRING_LENGTH)) (lines 110-111); file_people 'role TEXT' vs Column('role', ...) (line 120); file_locations 'location_type TEXT' vs Column('location_type', ...) (line 130).
- **Divergence:** The ORM composite primary keys (two primary_key=True columns per table) were transcribed as two inline 'PRIMARY KEY' declarations per table (e.g. 'file_id TEXT PRIMARY KEY, category_id INTEGER PRIMARY KEY', schema.sql:134-135, also 146-147, 159-160, 172-173). That is invalid SQLite — 'table has more than one primary key' — so these four CREATE TABLEs fail when the file is piped to wrangler d1 execute (the documented usage in export_to_d1.py:86).
- **Recommendation:** Regenerate from Base.metadata, which emits the correct 'PRIMARY KEY (file_id, category_id)' table constraint form.

### [MEDIUM] CREATE TABLE file_relationships

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:184-199`
- **Src counterpart:** `src/storage/models.py:983-1011` — `class FileRelationship`
- **Evidence:** SQL 'source_file_id TEXT NOT NULL, target_file_id TEXT NOT NULL, relationship_type TEXT NOT NULL, confidence REAL DEFAULT 1.0 ... UNIQUE (source_file_id, target_file_id, relationship_type)' matches models.py columns (992-997) and UniqueConstraint 'uq_file_relationship' (1008-1009).
- **Divergence:** SQL column 'metadata JSON' (schema.sql:190) vs ORM extra_data (models.py:998); SQL 'db_created_at' (schema.sql:191) vs ORM created_at (models.py:1001).
- **Recommendation:** Regenerate from Base.metadata so the metadata/extra_data rename and timestamp name are reconciled.

### [MEDIUM] CREATE TABLE organization_sessions

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:202-218`
- **Src counterpart:** `src/storage/models.py:1014-1044` — `class OrganizationSession`
- **Evidence:** SQL 'source_directories JSON, base_path TEXT ..., dry_run BOOLEAN DEFAULT 0, file_limit INTEGER, total_files INTEGER DEFAULT 0, organized_count ..., skipped_count ..., error_count ..., total_cost REAL DEFAULT 0.0, total_processing_time_sec REAL DEFAULT 0.0' matches models.py lines 1025-1040 field-for-field.
- **Divergence:** SQL names the start timestamp created_at (schema.sql:214, plus index ix_organization_sessions_created_at at :218) but the ORM column is started_at (models.py:1023, indexed). SQL also adds NOT NULL to base_path which the ORM does not declare (models.py:1029).
- **Recommendation:** Regenerate from Base.metadata; the created_at/started_at mismatch breaks any name-based insert or query against D1.

### [MEDIUM] CREATE TABLE cost_records

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:221-236`
- **Src counterpart:** `src/storage/models.py:1058-1085` — `class CostRecord`
- **Evidence:** SQL 'session_id TEXT, file_id TEXT, feature_name TEXT NOT NULL ... success BOOLEAN DEFAULT 1, created_at DATETIME' with FKs to organization_sessions(id)/files(id) matches models.py session_id/file_id/feature_name/success/created_at (1067-1077) and the same FK targets.
- **Divergence:** SQL is missing error_message (models.py:1074). Constraints on cost vs processing_time_sec are swapped: SQL has 'cost REAL NOT NULL, processing_time_sec REAL DEFAULT 0.0' (schema.sql:226-227) while the ORM has processing_time_sec nullable=False and cost default=0.0 (models.py:1071-1072). The composite index ix_cost_feature_date (models.py:1084) is absent from SQL.
- **Recommendation:** Regenerate from Base.metadata to restore error_message, correct the swapped NOT NULL/default, and add the composite index.

### [MEDIUM] CREATE TABLE schema_metadata

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:239-247`
- **Src counterpart:** `src/storage/models.py:1088-1113` — `class SchemaMetadata`
- **Evidence:** Same table name and skeleton: SQL 'file_id TEXT UNIQUE NOT NULL ... FOREIGN KEY (file_id) REFERENCES files(id)' matches models.py file_id = Column(..., ForeignKey('files.id'), unique=True, index=True) (line 1097); both carry a schema_context column.
- **Divergence:** Severely drifted: SQL has schema_version (schema.sql:242) which no longer exists in the ORM, and is missing schema_type (models.py:1100), schema_json JSON NOT NULL (models.py:1102), is_valid (1105), and validation_errors (1106). SQL types schema_context as JSON vs ORM String default 'https://schema.org' (1101); timestamps db_created_at/db_updated_at vs ORM created_at/updated_at (1109-1110).
- **Recommendation:** Regenerate from Base.metadata — the current SQL cannot even hold the model's NOT NULL schema_json payload.

### [MEDIUM] CREATE TABLE key_value_store

- **Kind:** diverged-copy
- **Script:** `scripts/d1/schema.sql:250-256`
- **Src counterpart:** `src/storage/models.py:1116-1145` — `class KeyValueStore`
- **Evidence:** Same table name and core pair: SQL 'key TEXT UNIQUE NOT NULL, value JSON' vs models.py key = Column(String(MAX_STRING_LENGTH), nullable=False) / value = Column(JSON) (1127-1128).
- **Divergence:** SQL is missing namespace (models.py:1126, NOT NULL + indexed), value_type (1129), file_id FK (1132), and expires_at (1135). SQL makes key globally UNIQUE while the ORM uniqueness is UniqueConstraint('namespace','key') (models.py:1142) — the SQL would reject the same key in two namespaces, which the KVStore design explicitly supports. Indexes ix_kv_namespace_key/ix_kv_expires (1143-1144) are absent; timestamps named db_* vs created_at/updated_at (1138-1139).
- **Recommendation:** Regenerate from Base.metadata; the wrong uniqueness scope is a functional bug, not just cosmetic drift.

### [MEDIUM] header enum comments + missing merge_events table

- **Kind:** partial-overlap
- **Script:** `scripts/d1/schema.sql:1-9`
- **Src counterpart:** `src/storage/models.py:75-92, 1148-1205` — `FileStatus / RelationshipType / MergeEventType / class MergeEvent`
- **Evidence:** Header comments hand-copy the enum value sets: '-- FileStatus: pending, organized, skipped, error, already_organized' and '-- RelationshipType: duplicate, similar, version, derived, related, parent_child, references' (schema.sql:8-9) match FileStatus (models.py:75-81) and RelationshipType (models.py:84-92) exactly.
- **Divergence:** The mirror covers only the pre-merge-tracking schema: MergeEventType (models.py:1148-1154) is not listed in the enum comments and the entire merge_events table (class MergeEvent, models.py:1157-1205, ~18 columns incl. target_entity_type, source_entity_ids, jsonld, rollback fields) has no CREATE TABLE anywhere in schema.sql — a whole ORM table silently absent from the D1 DDL.
- **Recommendation:** Generate the full DDL (all tables in Base.metadata, enum value comments included) from the models instead of maintaining this file by hand; that automatically adds merge_events and keeps enum comments truthful.

## Type organizer — `scripts/file_organizer_by_type.py` vs `src/pipeline` + `mime_classifier`

The script's `type_mapping` routes the same extensions to different destinations than `src/organizers/mime_classifier.py` (`Documents/Excel` vs `Data/CSV`, `Media/Video` vs `Media/Videos`, flat `Fonts` vs `CreativeWork/Fonts/*`), and its organize/summary loop duplicates `BatchProcessor`/`FileProcessor` structure. Fold the script-only extension classes into the src tables, reconcile the drifted destinations, and delegate the loop.

### [MEDIUM] FileTypeOrganizer.organize_directory / print_summary

- **Kind:** diverged-copy
- **Script:** `scripts/file_organizer_by_type.py:156-222`
- **Src counterpart:** `src/pipeline/batch_processor.py:47-180` — `BatchProcessor.scan_directory / organize_directories / print_summary`
- **Evidence:** Script 184-192 builds summary {'total_files','organized','already_organized','skipped','errors','dry_run','results'} — identical keys in identical order to batch_processor 142-151. print_summary is near-verbatim on both sides: script 198-209 vs src 157-168 share "Organization Summary", "Total files processed:", "Successfully organized:", "Already organized:", "Skipped:", "Errors:", "⚠️  This was a DRY RUN - no files were moved", "Category Breakdown", plus the same defaultdict loop `if result.get('category'): category_stats[result['category']] += 1` (script 216-219 vs src 174-177). Scan loop matches too: script 169-171 `for item in source_path.rglob('*'): if item.is_file() and not self.should_skip_file(item)` vs src 52-53. Header f-string `{'(DRY RUN)' if dry_run else ''}` at script 162 vs src 81.
- **Divergence:** src version adds CLIP/easyocr pre-warm, registry stats, company/cost sections, and sorts categories alphabetically with .capitalize(); script sorts by count desc, prints progress every 100 files, and takes a single source dir instead of a list.
- **Recommendation:** Delete the script's organize_directory/print_summary and run FileTypeOrganizer through src/pipeline BatchProcessor (it already duck-types organizers via _effective_organizer and should_skip_file); alternatively extract the shared scan+summary skeleton into src/pipeline and delegate.

### [MEDIUM] FileTypeOrganizer.organize_file

- **Kind:** diverged-copy
- **Script:** `scripts/file_organizer_by_type.py:99-154`
- **Src counterpart:** `src/pipeline/file_processor.py:371-509` — `FileProcessor.organize_file`
- **Evidence:** Same skeleton and status vocabulary. Result init: script 101-106 `{'source': str(file_path), 'status': 'skipped', 'destination': None, ...}` vs src 399-406 identical keys. Guard pair: script 108-114 `if self.should_skip_file(file_path): stats['skipped'] += 1; return` then `if not file_path.is_file(): stats['skipped'] += 1; return` vs src 408-416 same two guards updating organizer.stats['skipped']. Already-in-place: script 131-135 sets status 'already_organized' and stats['already_organized'] += 1 vs src 463-471 identical. Move: script 138-142 `shutil.move(...)` then status 'organized' else 'would_organize' vs src 474-475 and 508 `result["status"] = "organized" if not dry_run else "would_organize"`.
- **Divergence:** src version adds pre-classification image rename, schema generation/validation, registry registration, graph-store persistence, and a force flag; script adds resolve_collision on name clash and per-category stats counters.
- **Recommendation:** Fold the plain move path (collision-resolving mkdir+shutil.move with already_organized/would_organize statuses) into src/pipeline (FileProcessor or a shared helper) and have the script delegate, keeping only the type-specific classification local.

### [MEDIUM] FileTypeOrganizer.type_mapping / get_category_for_file

- **Kind:** partial-overlap
- **Script:** `scripts/file_organizer_by_type.py:30-93`
- **Src counterpart:** `src/organizers/mime_classifier.py:15-119` — `FONT_EXTENSIONS / classify_font / classify_by_mime`
- **Evidence:** Both classify by extension into the same folder taxonomy. Fonts: script 62 `'Fonts': ['.ttf', '.otf', '.woff', '.woff2']` vs src FONT_EXTENSIONS 16-19 keys '.ttf'/'.otf'/'.woff'/'.woff2'. Archives: script 59 `['.zip', '.tar', '.gz', '.rar', '.7z', '.bz2']` vs src 91-95 `.zip` branch plus `['.tar', '.gz', '.bz2', '.7z', '.rar']`. Screenshot special-case: script 76-77 `if name_lower.startswith('screenshot'): return 'Images/Photos/Screenshots'` vs src 47-48 `if 'screenshot' in file_name or file_name.startswith('screen'): return ('images', 'screenshots', 'ImageObject')`. Executables: script 65 `['.exe', '.app', '.pkg', '.dmg']` vs src 98 `['.dmg', '.pkg', '.exe', '.msi', '.deb', '.rpm']`. Destinations match src CATEGORY_PATHS (src/organizers/category_config.py 17-91): 'Images/Photos', 'Documents/PDFs', 'Documents/Word', 'Documents/Text', 'Code/Python', 'Code/JavaScript', 'Data/JSON', 'Media/Audio' appear verbatim on both sides.
- **Divergence:** Taxonomy drift: script routes .csv/.xls/.xlsx → 'Documents/Excel', .ppt → 'Documents/PowerPoint', video → 'Media/Video', .ts/.tsx → 'Code/TypeScript', fonts → flat 'Fonts', executables → 'Other/Executables'; src routes these to Data/CSV, Documents/Spreadsheets, Documents/Presentations, Media/Videos, code/javascript, CreativeWork/Fonts/*, Software/Installers. Script-only classes: Data/YAML, Data/XML, Data/Config, Code/Shell, Code/Web, Data/Timezones, Other/Misc; src-only: mime-prefix routing, research/markdown/music/database branches, schema_type triples.
- **Recommendation:** Replace type_mapping/get_category_for_file with mimetypes.guess_type + src.organizers.mime_classifier.classify_by_mime/classify_font resolved through CATEGORY_PATHS; first fold the script-only extension classes (yaml/xml/config/shell/web) into the src tables and reconcile the drifted destinations so one table is authoritative.

### [MEDIUM] get_category_for_file game-asset keyword list

- **Kind:** partial-overlap
- **Script:** `scripts/file_organizer_by_type.py:80-81`
- **Src counterpart:** `src/organizers/name_organizer.py:253-275` — `FileNameOrganizer.filename_patterns['game_assets']['sprites']`
- **Evidence:** Script 80: `any(pattern in name_lower for pattern in ['frame', 'item', 'segment', 'wing', 'arm', 'leg', 'head', 'torso'])` → 'Images/Photos/GameAssets'. src sprites list contains anchored regexes for 7 of these 8 tokens: `^frame\d+`, `^item\d+`, `^wing_`, `^arm_`, `^leg`, `^head_`, `^torso_` (name_organizer 264-274). The same body-part vocabulary also lives in src/organizers/content_organizer.py: _SPRITE_DISCRIMINATOR_KEYWORDS 191-198 ({'frame', ..., 'leg', 'arm', 'head', 'torso', ..., 'wing', ...}) and the regex `^(head|torso|arm|leg|body|wing|hair)_\w+` at line 389.
- **Divergence:** Script uses unanchored substrings (matches 'framework', 'items', etc.) and adds 'segment'; src uses anchored regexes plus is_image routing to 'Media/Photos'/'Games' vs 'GameAssets/Sprites', and content_organizer keeps a much larger curated keyword set.
- **Recommendation:** Drop the inline substring list and reuse the src vocabulary — import a shared sprite-keyword constant (content_organizer._SPRITE_DISCRIMINATOR_KEYWORDS or the name_organizer sprite patterns, hoisted into a shared src constant) or delegate game-asset detection to the src organizer.

## Keyword and constant tables duplicated between `scripts/shared` and `src`

The `GAME_SPRITE_KEYWORDS` pattern (single-homed in `shared.constants`, imported by `content_organizer.py:22`) is the model; these tables never got the same treatment. Notable: `GAME_FONT_KEYWORDS` is element-for-element identical on both sides; `GAME_AUDIO/MUSIC_KEYWORDS` diverged in both directions — src added ~34 terms the script lacks, while the script fixed the `'cast'`-matches-`'podcast'` false positive (`'spellcast'`) that src still has.

### [MEDIUM] IMAGE_EXTENSIONS / IMAGE_EXTENSIONS_WIDE

- **Kind:** diverged-copy
- **Script:** `scripts/shared/constants.py:17-18`
- **Src counterpart:** `src/pipeline/batch_processor.py:9-11` — `_IMAGE_EXTENSIONS`
- **Evidence:** shared/constants.py:17-18: IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp"}; IMAGE_EXTENSIONS_WIDE = IMAGE_EXTENSIONS | {".tiff", ".tif", ".svg", ".ico", ".raw"}  —  batch_processor.py:9-11: _IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".tif"}). The src set is exactly IMAGE_EXTENSIONS plus .tiff/.tif (i.e. IMAGE_EXTENSIONS_WIDE minus .svg/.ico/.raw), including the distinctive .heic member.
- **Divergence:** src's private frozenset includes .tiff/.tif (like the WIDE variant) but omits .svg/.ico/.raw; shared's narrow IMAGE_EXTENSIONS omits .tiff/.tif. Neither set exactly equals the other, so directory scans in BatchProcessor (line 112) accept a different file population than scripts using the shared tables (e.g. scripts/organize_to_existing.py line 32). Note the duplication direction is src copying scripts/shared: shared.constants is the de-facto canonical table — src/pipeline/file_processor.py:52 already imports IMAGE_EXTENSIONS_WIDE from shared.constants, and batch_processor itself imports other shared.constants symbols (lines 14-15).
- **Recommendation:** Have batch_processor import the extension set from shared.constants like file_processor.py does (keep the local frozenset only as the ImportError fallback inside the existing try block, or move the extension tables into src and have scripts/shared re-export them), then pick one canonical member list so scan filters agree.

### [MEDIUM] _IMAGE_EXTENSIONS

- **Kind:** diverged-copy
- **Script:** `scripts/collect_kie_training_data.py:46`
- **Src counterpart:** `src/pipeline/batch_processor.py:9-11` — `_IMAGE_EXTENSIONS`
- **Evidence:** Script line 46: `_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".heic"}`. Src lines 9-11: `_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".tif"})`. Same identifier name; 8 of 9 members identical.
- **Divergence:** Src set includes ".gif" (and is a frozenset); the script's set omits it, so GIFs are scanned by the batch pipeline but silently skipped by KIE training-data collection. Both restate scripts/shared/constants.py IMAGE_EXTENSIONS (plus {".tiff", ".tif"}) instead of deriving from it — the repo already centralizes this vocabulary there (commented "used by 6+ scripts").
- **Recommendation:** Derive both sets from scripts/shared/constants.py, e.g. IMAGE_EXTENSIONS | {".tiff", ".tif"}, so the extension vocabulary has one source of truth; if the KIE collector intentionally excludes .gif, express that as an explicit subtraction from the shared set.

### [MEDIUM] GAME_FONT_KEYWORDS

- **Kind:** identical-copy
- **Script:** `scripts/shared/constants.py:438-453`
- **Src counterpart:** `src/organizers/content_organizer.py:393-398` — `ContentOrganizer.__init__ self.game_font_keywords`
- **Evidence:** Script: GAME_FONT_KEYWORDS = ['broguefont', 'gamefont', 'pixelfont', 'bitfont', 'font_', '_font', 'fontsheet', 'font_atlas', 'fontatlas', 'charset', 'glyphs', 'tilefont', 'asciifont', 'ascii_font']. Src: self.game_font_keywords: List[str] = ['broguefont', 'gamefont', 'pixelfont', 'bitfont', 'font_', '_font', 'fontsheet', 'font_atlas', 'fontatlas', 'charset', 'glyphs', 'tilefont', 'asciifont', 'ascii_font'] — same 14 items in the same order.
- **Divergence:** None — the two lists are element-for-element identical, only formatting differs.
- **Recommendation:** Single-home like GAME_SPRITE_KEYWORDS already is: content_organizer.py:22 imports GAME_SPRITE_KEYWORDS from shared.constants and assigns it at line 377 with the comment 'Single-homed in shared.constants'. Do the same for GAME_FONT_KEYWORDS: delete the inline literal at content_organizer.py:394-398 and assign self.game_font_keywords = GAME_FONT_KEYWORDS from the shared constant (GAME_FONT_KEYWORDS currently has no consumer besides the scripts/shared/__init__.py re-export).

### [MEDIUM] GAME_AUDIO_KEYWORDS

- **Kind:** diverged-copy
- **Script:** `scripts/shared/constants.py:377-408`
- **Src counterpart:** `src/organizers/content_organizer.py:352-363` — `ContentOrganizer.__init__ self.game_audio_keywords`
- **Evidence:** Both lists contain the distinctive instrument run 'fiddle', 'lute', 'mandoline', 'glockenspiel' plus 'bolt', 'spell', 'magic', 'dispel', 'summon', 'pickup', 'unlock' — 26 of the script's 30 entries appear in the src list.
- **Divergence:** Src list (~60 items) adds 'cast', 'chirp', 'crossbow', 'bow', 'potion', 'explosion', 'blast', 'petrification', 'neutralize', 'slow', 'darkness', 'achievement', 'quest', 'hit', 'death', 'footstep', 'jump', 'land', 'monster', 'creature', 'enemy', 'boss', 'battle', 'combat', 'starving', 'hunger', 'thirst', 'eat', 'drink', 'sleep', 'instrument', 'identify', 'greater', 'mental'; script list has 'sfx', 'sound', 'effect', 'ambient' which the src list lacks. Since scripts/evaluate_model.py:18,157 classifies eval data with the script list while production ContentOrganizer uses the src list, evaluation and production disagree on game-audio detection.
- **Recommendation:** Reconcile into one list (union or deliberate curation) in shared.constants.GAME_AUDIO_KEYWORDS, then have ContentOrganizer assign self.game_audio_keywords from it, mirroring the GAME_SPRITE_KEYWORDS pattern at content_organizer.py:22,377. Re-run the eval (scripts/evaluate_model.py consumes the same constant) to confirm no regression.

### [MEDIUM] GAME_MUSIC_KEYWORDS

- **Kind:** diverged-copy
- **Script:** `scripts/shared/constants.py:410-436`
- **Src counterpart:** `src/organizers/content_organizer.py:365-374` — `ContentOrganizer.__init__ self.game_music_keywords`
- **Evidence:** Both lists contain the distinctive ADOM-specific tokens 'drakalor', 'altar', 'dwarven', 'elven', 'clockwork' plus 'battle', 'boss', 'dungeon', 'castle', 'victory', 'defeat', 'chaos', 'hope', 'despair', 'triumph', 'mysterious' — 21 of the script's 25 entries appear in the src list.
- **Divergence:** Src list (~53 items) adds 'village', 'ruins', 'mountain', 'ocean', 'desert', 'snow', 'menu', 'credits', 'intro', 'outro', 'dark', 'light', 'epic', 'calm', 'peaceful', 'tension', 'march', 'symphony', 'monotony', 'lawful', 'chaotic', 'neutral', 'alignment', 'orcish', 'halls', 'abandon', 'corrupting', 'breeze', 'knowledge', 'oddisey', 'final', 'welcome'; script list has 'bgm', 'soundtrack', 'music', 'loop' which the src list lacks. scripts/evaluate_model.py:18,156 uses the script list, so eval music-detection differs from production ContentOrganizer.
- **Recommendation:** Same treatment as GAME_AUDIO_KEYWORDS: fold the two lists into a single shared.constants.GAME_MUSIC_KEYWORDS and have ContentOrganizer reference it instead of the inline literal at content_organizer.py:365-374, matching the single-homed GAME_SPRITE_KEYWORDS pattern.

### [MEDIUM] game_audio_keywords (AUDIO FILES section of classify_by_filename_patterns)

- **Kind:** diverged-copy
- **Script:** `scripts/shared/filename_classifier.py:814-970`
- **Src counterpart:** `src/organizers/content_organizer.py:352-374, 510-521` — `ContentOrganizer.game_audio_keywords + game_music_keywords (consumed by classify_game_asset)`
- **Evidence:** Script 819-825: "bolt", "spell", "magic", "spellcast", "chirp", "crossbow", "dagger", "sword", "arrow", "bow", "heal", "potion"... vs src 353-354: 'bolt', 'spell', 'magic', 'cast', 'chirp', 'crossbow', 'dagger', 'sword', 'arrow', 'bow', 'heal', 'potion'... — same sequence in the same order. Music tail also shared: script 928-942 "drakalor", "altar", "lawful", "chaotic", "dwarven", "elven", "orcish", "halls", "abandon", "corrupting", "breeze", "clockwork", "knowledge", "final", "welcome" vs src 371-373 'drakalor', 'altar', 'lawful', 'chaotic', ..., 'dwarven', 'elven', 'orcish', 'halls', 'abandon', 'corrupting', 'breeze', 'clockwork', 'knowledge', ..., 'final', 'welcome'. Both route audio-extension stems to game_assets.
- **Divergence:** Script merged src's two lists (audio + music) into one and routes everything to game_assets/audio; src routes .ogg music separately to game_assets/music. Script replaced 'cast' with 'spellcast' (comment: avoids matching 'podcast') — src still has the 'cast' false-positive. Script adds weapon terms (melee, axe, mace, whip, sabre, staff, thunder, firebolt, fireball, boomer, skur) and ADOM music terms (khelavaster, prophecy, spiraling, ancardia, goblin, drums, bird, ...); src has 'neutral', 'alignment', 'oddisey' which the script lacks. Pipeline note: detect_file_category runs the script at Priority 0b and classify_game_asset at Priority 3, and the script's audio section always returns for audio extensions (game_assets/audio or media/audio_other), so the src copy is unreachable dead code in ContentOrganizer's pipeline.
- **Recommendation:** Single-home the vocabulary in shared constants (as was already done for GAME_SPRITE_KEYWORDS, which content_organizer.py:377 imports): fold the script's fixes (spellcast, weapons, ADOM terms) and src's extras (neutral/alignment/oddisey, audio-vs-music split) into one canonical table, have the script's audio section consume it, and delete or delegate the shadowed classify_game_asset audio branch.

### [MEDIUM] entity_patterns + company_patterns + zouk rule

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:274-292, 555-590, 1513-1518`
- **Src counterpart:** `src/classifiers/content_classifier.py:304-315` — `known_text_companies (inside ContentClassifier.classify_content)`
- **Evidence:** Identical routing tuples on both sides: script 577 "capitalcityvillage": ("organization", "property_management", "Capital City Village") vs src 306 'capital city village': ('organization', 'property_management', 'Capital City Village'); script 564-565 "leora"/"leorahomehealth": ("organization", "healthcare", "Leora Home Health") vs src 307 same tuple; script 571 "inspiredmovement": ("organization", "vendors", "Inspired Movement") vs src 309 same tuple; script 1516-1518 'if "zouk" in stem: return ("zouk", "events", None, [])' vs src 311 'zouk': ('zouk', 'events', None).
- **Divergence:** Key space differs (concatenated/underscore filename stems vs spaced text phrases). src adds 'new beginnings child development'; script adds Fisterra/DotFun/EnsoCo/Google/Microsoft/Adobe/Amazon/Apple. Internally inconsistent too: company_patterns (278-283) routes Integrity Studio to subcategory "other" while entity_patterns (561-563) and src both use "vendors".
- **Recommendation:** Extract one canonical company -> (category, subcategory, display_name) table into src (e.g. beside EntityDetector), derive stem-variant and text-phrase keys from it programmatically, and import it in the script; reconcile the missing entries and the Integrity Studio other/vendors inconsistency while merging.

### [MEDIUM] financial_doc_keywords

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:1550-1565`
- **Src counterpart:** `src/classifiers/content_classifier.py:49-62` — `ContentClassifier.patterns['financial']['subcategories']`
- **Evidence:** Script 1555-1560: financial_doc_keywords = {"invoice": "invoices", "billing": "statements", "statement": "statements", "receipt": "other"} vs src 58-61: 'invoices': ['invoice', 'bill', 'billing', 'payment'], 'statements': ['statement', 'account', 'balance', 'transaction'] — same keyword -> financial-subcategory routing maintained in both tiers.
- **Divergence:** Contradictory mapping for 'billing': the filename tier files it under financial/statements while the content tier's vocabulary puts 'billing' under financial/invoices, so the same document classifies differently depending on which tier fires first.
- **Recommendation:** Reconcile the 'billing' mapping and derive both tiers from a single keyword->subcategory table (script matches stems, classifier matches text, but the mapping data should be one constant).

### [MEDIUM] BUSINESS TYPE PATTERNS (crm/thirdparty/hr/planning/meeting lists)

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:294-417`
- **Src counterpart:** `src/classifiers/content_classifier.py:64-82` — `ContentClassifier.patterns['business'] keywords + subcategories`
- **Evidence:** Script 324 'if "crm" in stem or "microlender" in stem' -> ("business", "crm") vs src 77 'crm': ['crm', 'contacts', 'microlender', 'customer'] — 'microlender' is highly distinctive and appears in both. Script hr_patterns 348-358 ('jobposting', 'hiring', 'teamroster', ...) + hr_doc_patterns 360 ['application', 'linkedin'] -> ("business", "hr") vs src 78 'hr': ['hiring', 'job posting', 'team roster', 'application', 'linkedin']. Script meeting_patterns 402-414 ('standup', 'meeting', 'minutes', 'agenda', 'retrospective', ...) -> ("business", "meeting_notes") vs src 79 'meeting_notes': ['meeting', 'standup', 'minutes', 'agenda', 'retrospective'] — all five identical.
- **Divergence:** Script adds separator variants (job_posting/job-posting, stand-up, ...) plus extra terms (3rdparty/thirdparties, boardmember, allhands, retro); src adds 'customer'. Note classify_content also scores the filename (combined text+filename at content_classifier.py:302), so the vocabularies genuinely compete rather than covering disjoint inputs.
- **Recommendation:** Single-home the business subcategory vocabularies in src and generate the concatenated/underscore/hyphen stem variants in the script from that list.

### [MEDIUM] RESUME FILES section (resume_patterns + is_cv_document) and COVER LETTERS

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:455-547`
- **Src counterpart:** `src/organizers/content_organizer.py:674-678` — `ContentOrganizer.classify_by_person resume branch`
- **Evidence:** Script 461 resume_patterns = ["resume", "curriculum_vitae", "curriculum-vitae"] plus is_cv_document (464-474), returning ("personal", "contacts", None, [person_name]) at 526-528; src 675-678: resume_patterns = ['resume', 'cv', 'curriculum', 'vitae']; if any(pat in filename_lower ...): return ('personal', 'contacts', people ...) — same filename rule and same (personal, contacts) target maintained in both. Same vocabulary also appears a third time in content_classifier.py:96 'contacts': ['resume', 'cv', 'vcard', 'contact', 'curriculum vitae'].
- **Divergence:** src uses a bare substring check ('cv' in filename_lower), which fires on any filename containing 'cv'; the script deliberately guards 'cv' with word-boundary checks (cv_/cv-/_cv/' cv'/... at 464-474) — the careful semantics never made it back to src. The two-tier layering is intentional (the script falls through when no person name is extractable from the filename so the content tier can pull it from text), but the predicate itself is double-homed and drifted.
- **Recommendation:** Move a single resume/CV filename predicate (with the script's boundary-safe cv logic) into src and have both the script section and classify_by_person import it.

### [MEDIUM] font-asset filename rules (broguefont regex, font/glyph/charset check, cp-codepage regexes, tinyfont regex)

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:1024-1027, 1056-1060, 1244-1248, 1347-1350`
- **Src counterpart:** `src/organizers/content_organizer.py:393-398, 526-529` — `ContentOrganizer.game_font_keywords (consumed by classify_game_asset)`
- **Evidence:** Script 1025 re.match(r"^broguefont\d+$", stem) -> ("game_assets", "fonts") and 1058 '"font" in stem or "glyph" in stem or "charset" in stem' -> ("game_assets", "fonts") vs src 395-397 game_font_keywords = ['broguefont', 'gamefont', 'pixelfont', 'bitfont', 'font_', '_font', 'fontsheet', 'font_atlas', 'fontatlas', 'charset', 'glyphs', 'tilefont', 'asciifont', 'ascii_font'] -> ('game_assets', 'fonts') at 527-529. 'broguefont', 'charset', and glyph terms appear on both sides with the same routing.
- **Divergence:** Script adds codepage regexes (^cp\d+[_-], ^(ascii|unicode|charset|codepage)[_-]) and ^[a-z]+font\d+; src's keyword list entries ('gamefont', 'pixelfont', 'fontsheet', ...) are mostly subsumed by the script's generic 'font in stem' check, which runs first (Priority 0b vs Priority 3) and shadows the src branch for most image stems.
- **Recommendation:** Consolidate font-asset detection into one shared vocabulary/regex set consumed by both tiers; prune the shadowed src keywords once merged.

### [MEDIUM] game_sprite_prefixes + numbered-sprite regexes

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:996-1055`
- **Src counterpart:** `src/organizers/content_organizer.py:379-391, 531-534` — `ContentOrganizer.game_sprite_patterns (consumed by classify_game_asset)`
- **Evidence:** Script 1000-1016 game_sprite_prefixes includes "weapon_", "armor_", "item_", "tile_", "spell_" vs src 390 re.compile(r'^(weapon|armor|item|sprite|frame|tile)\d*_') — same prefix set, both -> ('game_assets', 'sprites'). Script 1049 re.match(r"^\d+(_\d+)*$", stem) ('Numbered sprite') vs src 381 re.compile(r'^\d+_\d+$')  # 42_8, 51_3 (sprite sheets) — the src pattern is a strict subset of the script's.
- **Divergence:** Script adds camera-photo/screenshot exclusions (is_camera_photo, software_screenshot) and explicit timestamped variants (^\d+(_\d+)*_\d{8}_\d{6}$); src instead strips the timestamp via re.sub(r'_\d{8}_\d{6}$') on clean_stem (line 508). src has extra patterns (^\d+_grey, ^\d+_f, ^[a-z]+_[a-z]+_\d+, 2h_/arrow_v/arrow_h families) that the script covers differently via the GAME_SPRITE_KEYWORDS token match. Script tier runs first, so src patterns only see what the script missed.
- **Recommendation:** Merge the two regex/prefix sets into one shared table (alongside GAME_SPRITE_KEYWORDS in shared constants), keeping the script's camera/screenshot exclusions, and have classify_game_asset consume the same table.

### [MEDIUM] journal_keywords

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:1604-1621`
- **Src counterpart:** `src/classifiers/content_classifier.py:97` — `ContentClassifier.patterns['personal']['subcategories']['journal']`
- **Evidence:** src 97: 'journal': ['journal', 'diary', 'dream', 'reflection', 'memoir'] — all five words appear in script 1607-1616 journal_keywords = ["dream", "diary", "journal", "thoughts", "reflection", "memoir", ...]; both route to personal/journal.
- **Divergence:** Script adds 'thoughts', 'nightbefore', 'morningafter', 'dayof' which never made it into the content-tier vocabulary.
- **Recommendation:** Single-home the journal keyword list in src and import it in the script section.

### [MEDIUM] corporate_legal_patterns + contract_legal_patterns + legal_patterns + legal_keywords

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_classifier.py:143-191, 634-665, 1521-1548`
- **Src counterpart:** `src/classifiers/content_classifier.py:29-47` — `ContentClassifier.patterns['legal']`
- **Evidence:** Script 147-164 routes 'bylaws', 'operatingagreement', 'articlesofincorporation', 'certificateofformation' -> ("legal", "corporate") and 637-649 routes 'agreement', 'contract', 'amendment', 'operating' -> legal contracts/corporate; src 45 'corporate': ['llc', 'corporation', 'operating agreement', 'bylaws', 'articles', 'formation'] and 38 'contracts': ['contract', 'agreement', 'terms', ...] — the same word->subcategory routing in stem space vs text space.
- **Divergence:** Script adds NDA/CLA/release-of-liability boundary-safe handling absent from src. Also inconsistent inside the script: the later legal_keywords tier (1545-1548) routes 'contract'/'agreement'/'terms'/'amendment' matches to ("business", "legal") — a subcategory that does not exist in CONTENT_CATEGORY_PATHS['business'] (category_config.py:107-117), so those files land in Business/Other instead of Legal/*.
- **Recommendation:** Derive the filename variants from the src legal vocabulary, and reconcile the ("business", "legal") tier with the legal category (or add the missing path mapping).

### [MEDIUM] software_extensions + archive_extensions

- **Kind:** duplicated-constants
- **Script:** `scripts/shared/filename_classifier.py:615-632, 1376-1382`
- **Src counterpart:** `src/organizers/mime_classifier.py:90-99` — `classify_by_mime (archive/software extension branches)`
- **Evidence:** Script 1379 archive_extensions = {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"} vs mime_classifier 91-95: '.zip' plus ['.tar', '.gz', '.bz2', '.7z', '.rar'] — identical six-member set. Script 618-629 software_extensions includes ".dmg", ".pkg", ".msi", ".deb", ".rpm", ".exe" vs mime_classifier 98: ['.dmg', '.pkg', '.exe', '.msi', '.deb', '.rpm'] — identical six installers.
- **Divergence:** Script extends software with .app/.snap/.flatpak/.appimage and routes to technical/software_packages and technical/archives; mime_classifier routes to software/installers and archives/* in the type-organizer's CATEGORY_PATHS taxonomy. Different CLI modes, but the extension membership is the same data maintained twice.
- **Recommendation:** Share the archive/software extension-set constants (single-home in shared constants or src.organizers) and keep only the per-organizer destination mapping local.

### [MEDIUM] _GENERIC_FILENAME_PATTERNS

- **Kind:** partial-overlap
- **Script:** `scripts/shared/filename_utils.py:14-44`
- **Src counterpart:** `src/organizers/name_organizer.py:215-241` — `FileNameOrganizer.filename_patterns (screenshots / camera_photos / social_media entries)`
- **Evidence:** Script (matched against lowercased stem): r"^img_\d+", r"^pxl_\d+", r"^dsc_?\d+", r"^dcim_\d+", r"^screenshot[\s_-]", r"^\d{8}_\d{6}", r"^unnamed" (filename_utils.py:19-38). Src: r'^IMG_\d+', r'^PXL_\d+', r'^DSC_\d+', r'^DCIM_\d+' , r'^\d{8}_\d{6}' (name_organizer.py:230-234), r'^screenshot[_\s]' (name_organizer.py:216), r'^unnamed\(\d+\)' (name_organizer.py:241). Seven regex literals for camera-vendor prefixes, YYYYMMDD_HHMMSS timestamps, screenshot prefixes, and unnamed(N) placeholders are maintained in both tables.
- **Divergence:** Purpose and coverage differ: filename_utils uses the patterns (case-insensitively, on the lowercased stem) to flag generic filenames for content-based renaming and adds hashes/UUIDs/image(N)/photo(N)/file(N)/unix-ms patterns; name_organizer uses uppercase-literal variants to route files to Media/{Photos,Screenshots,SocialMedia} and adds its own extras (^\d{14}, ^\d{8}_[A-Za-z]+_\d{6}, ^Screen Shot, ^scrnshot, ^capture[_\s], Facebook n.jpg pattern). filename_utils also matches bare ^unnamed while name_organizer only matches ^unnamed\(\d+\). A new camera-vendor prefix (e.g. a new phone's naming scheme) must currently be added in both places.
- **Recommendation:** Extract the shared camera-vendor-prefix / timestamp / screenshot / unnamed regex core into one constant table (e.g. src/organizers/category_config.py or shared.constants) and have both filename_utils._GENERIC_FILENAME_PATTERNS and FileNameOrganizer.filename_patterns['camera_photos'/'screenshots'/'social_media'] compose from it, keeping their purpose-specific extras local, so vendor-prefix additions stay in sync.

## Small items — helpers, probes, and paths

Independent small copies: `compute_file_id` verbatim; `DEFAULT_DB_PATH` defined twice (script version root-anchored and correct, src version CWD-relative) with the raw literal hardcoded in 9 more src call sites; OCR dependency-probe blocks whose flags can disagree; and summary/label-mapping fragments.

### [MEDIUM] analyze_report (company-summary and category-breakdown sections)

- **Kind:** partial-overlap
- **Script:** `scripts/analyze_people_companies.py:43-67, 83-95, 112-129`
- **Src counterpart:** `src/pipeline/batch_processor.py:161-200` — `BatchProcessor.print_summary`
- **Evidence:** Script:63 `print(f"\nTotal files processed: {data['total_files']}")` vs src:161 `print(f"Total files processed: {summary['total_files']}")`; script:65 `Files with detected companies: {len(files_with_companies)}` vs src:197 `Total files with detected companies: {len(company_files)}`; script:44-46 filters `result.get('company_name')` and accumulates per-company file counts via defaultdict vs src:188-195 `company_files = [r for r in summary["results"] if r.get("company_name")]` + `company_counts[result["company_name"]] += 1`; script:117-127 `category_stats` defaultdict + `sorted(category_stats...)` + `category.capitalize()` vs src:174-180 same variable name and `category.capitalize()` print pattern. Both operate on the identical data shape: the report JSON the script loads is the exact summary dict `FileProcessor.save_report` (src/pipeline/file_processor.py:600-607) json.dumps, i.e. the same dict `print_summary` consumes.
- **Divergence:** Script sorts companies alphabetically and lists up to 3 filenames+category per company; src sorts by descending file count and prints counts only. Script's category breakdown tallies files-with-people and files-with-companies per category; src tallies total files per category. Script reads the saved report JSON from disk; src prints from the in-memory summary (same schema). Script's people sections (lines 28-41, 69-81, 97-110) are unique — src has no per-person report at all.
- **Recommendation:** Keep only the script's unique people-analysis sections and drop the redundant company/category summary — since the saved report has the identical schema as the in-memory summary, the script can load the JSON and delegate to BatchProcessor.print_summary for the company/category portions (or, if the richer per-company file listing is wanted long-term, move that aggregation into a src/pipeline reporting helper and have both print_summary and the script call it).

### [MEDIUM] _DOCUMENT_LABEL_MAP / _document_label (pass 5)

- **Kind:** partial-overlap
- **Script:** `scripts/relabel_test_set.py:94-103, 136-141`
- **Src counterpart:** `src/ml/feature_extractor.py:89, 153-156` — `is_document feature (_matches_patterns over DOCUMENT_PATTERNS)`
- **Evidence:** Script keys invoice/receipt/statement/tax/contract/resume/cv/letter are exactly shared.constants DOCUMENT_PATTERNS (constants.py:464-474) minus 'report', re-matched per filename via `re.search(rf"\b{re.escape(pattern)}\b", name)`. Src already computes `'is_document': self._matches_patterns(filename, DOCUMENT_PATTERNS)` over the same list, and the script's input samples are feature dicts carrying that field.
- **Divergence:** Script needs the specific matched keyword (to map to a category/subcategory pair) which src's boolean is_document cannot provide; script uses word-boundary matching vs src's substring matching; script intentionally omits 'report' and defines its own category/subcategory targets (e.g. 'invoice' -> ('financial','invoice')), whose names differ from src/classifiers/content_classifier.py's taxonomy ('invoices', 'employment').
- **Recommendation:** Keep the per-keyword category map (script-only behavior) but derive its key set from DOCUMENT_PATTERNS and use the sample's existing is_document flag as the prefilter; if per-keyword document detection is needed elsewhere, promote a keyword->label variant into src/ml/feature_extractor next to is_document.

### [MEDIUM] OCR_AVAILABLE dependency-probe block (module level, incl. pillow_heif register_heif_opener)

- **Kind:** diverged-copy
- **Script:** `scripts/file_organizer_content_based.py:25-46`
- **Src counterpart:** `src/organizers/content_organizer.py:32-55` — `OCR_AVAILABLE dependency-probe block (module level)`
- **Evidence:** Both files carry the same distinctive comment — script: "pypdf and PIL are imported here (even though extraction now lives in src.analyzers.text_extractor) so that OCR_AVAILABLE keeps gating the pipeline on the full dependency set, matching historical behavior."; src: identical minus the word "now" — followed by the same try-block: `import pypdf  # noqa: F401 — availability probe`, `from PIL import Image  # noqa: F401 — availability probe`, `from shared.ocr_classifier import OCR_AVAILABLE  # shared module-level flag; avoids duplicate probe`, and the identical nested HEIC block `from pillow_heif import register_heif_opener` / `register_heif_opener()` with `except ImportError: pass`, then `except ImportError: OCR_AVAILABLE = False`.
- **Divergence:** Script's probe additionally imports shared.file_ops.resolve_collision, shared.filename_utils.is_generic_filename, and shared.status.ProcessingStatus as availability probes, and prints "Warning: OCR libraries not available. Install python-doctr[torch], Pillow, pypdf" on failure; src's copy instead probes SCREENSHOT_KEYWORDS/classify_by_ocr/extract_ocr_with_confidence and silently stubs them to None/{} on failure. So the two OCR_AVAILABLE flags can disagree (e.g. if shared.status fails to import, only the script's flag goes False).
- **Recommendation:** Delete the script's probe and import the flag from the canonical module (`from src.organizers.content_organizer import OCR_AVAILABLE`), which already registers the HEIC opener as a side effect; ContentOrganizer.__init__ already defaults ocr_available=None to its own OCR_AVAILABLE (content_organizer.py line 231), so the script can also stop passing ocr_available=. If gating on file_ops/filename_utils/status is genuinely required, fold those extra probes into the src block first, then delegate.

### [MEDIUM] run() --run-migration branch

- **Kind:** diverged-copy
- **Script:** `scripts/file_organizer_content_based.py:372-384`
- **Src counterpart:** `src/cli.py:78-87` — `cmd_migrate`
- **Evidence:** Identical 4-line invocation sequence in both: `print(f"\n{'='*60}")`, `print("Running ID Generation Migration")`, `print(f"{'='*60}\n")`, `run_migration(...)`, followed by the identical completion string `print("\nMigration complete. Canonical IDs have been generated for existing records.")`, both preceded by the same local `from storage.migration import run_migration`.
- **Divergence:** Script wraps the block in `if GRAPH_STORE_AVAILABLE:` with an else branch printing "Error: GraphStore not available. Cannot run migration." and passes args.db_path directly; src/cli.py cmd_migrate has no availability guard but adds a default fallback `db_path = args.db_path or DEFAULT_DB_PATH`.
- **Recommendation:** Make the script's --run-migration branch delegate to the canonical handler (`from src.cli import cmd_migrate; cmd_migrate(args); return`), optionally keeping the GRAPH_STORE_AVAILABLE guard around the call — or extract a shared helper (e.g. a banner-owning wrapper in src/storage/migration.py) that both src/cli.py cmd_migrate and the script call, so the banner/completion strings and db-path defaulting live in one place.

### [MEDIUM] kie_result_to_schema_org / _KIE_SCHEMA_MIN_CONFIDENCE / KIE_FIELD_CLASSES

- **Kind:** partial-overlap
- **Script:** `scripts/shared/kie_schema_mapping.py:14-25, 95, 109-120`
- **Src counterpart:** `src/classifiers/content_classifier.py:210-252` — `ContentClassifier.classify_with_kie / _best_kie_field / _KIE_CLASSIFICATION_MIN_CONFIDENCE`
- **Evidence:** Script (line 95): `_KIE_SCHEMA_MIN_CONFIDENCE = 0.5`; (lines 118-119): `best = max(fields, key=lambda f: f.confidence)` / `if best.confidence < _KIE_SCHEMA_MIN_CONFIDENCE: continue`. Src (line 211): `_KIE_CLASSIFICATION_MIN_CONFIDENCE = 0.5`; (lines 249-251): `for f in kie_result.fields.get(name, ()): if f.confidence >= min_confidence and (best is None or f.confidence > best.confidence): best = f`. Src lines 230-232 also hardcode the class-name strings ("vendor_name", "store_name"), ("total_amount", "receipt_total"), ("invoice_date", "receipt_date") that duplicate entries of KIE_FIELD_CLASSES (script lines 14-25).
- **Divergence:** Script selects the best prediction within a single class then applies the 0.5 gate; src scans a tuple of class names with the gate inline. The two 0.5 thresholds have different names/docstrings, so they can silently drift apart, as can the class-name vocabulary (src hardcodes 6 of the 10 KIE_FIELD_CLASSES strings instead of referencing the table). Both sides were introduced by the same commit (685c91f).
- **Recommendation:** Hoist a shared best_kie_field(kie_result, class_names, min_confidence) helper and a single KIE min-confidence constant into scripts/shared/kie_utils.py (next to KIEField/KIEResult, which src already imports), then have both kie_result_to_schema_org and ContentClassifier.classify_with_kie delegate to it; replace the hardcoded class-name tuples in content_classifier with groups defined alongside KIE_FIELD_CLASSES in kie_schema_mapping.

### [MEDIUM] DEFAULT_DB_PATH

- **Kind:** duplicated-constant
- **Script:** `scripts/shared/db_utils.py:8`
- **Src counterpart:** `src/cli.py:31` — `DEFAULT_DB_PATH`
- **Evidence:** Script: DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "results" / "file_organization.db" -- src: DEFAULT_DB_PATH = 'results/file_organization.db'. Same constant name, same DB target, two modalities.
- **Divergence:** Script version is a repo-root-anchored absolute Path (CWD-independent); src version is a CWD-relative string that only resolves when run from project root. The raw literal 'results/file_organization.db' is additionally repeated as a hardcoded default argument in src/storage/graph_store.py:67, src/storage/kv_store.py:44 and 755, src/storage/migration.py:57/552/826, src/storage/person_migration.py:571, and src/api/timeline_api.py:25/328 (src/constants.py has no DB-path constant).
- **Recommendation:** Define one canonical DEFAULT_DB_PATH in src/constants.py (repo-root-anchored, like the script version), reference it from src/cli.py and every default argument in src/storage/{graph_store,kv_store,migration,person_migration}.py and src/api/timeline_api.py, and have scripts/shared/db_utils.py import it from src instead of redefining it.

### [LOW] compute_file_id

- **Kind:** identical-copy
- **Script:** `scripts/update_report_with_labels.py:18-20`
- **Src counterpart:** `src/storage/models.py:233-236` — `File.generate_id`
- **Evidence:** Script: `return hashlib.sha256(filepath.encode()).hexdigest()` (docstring: "Compute the file ID (SHA-256 hash of the path)"). Src: `return hashlib.sha256(path.encode()).hexdigest()` (docstring: "Generate a deterministic ID from the file path"). Identical body, only parameter name differs.
- **Divergence:** None in logic; parameter renamed filepath vs path. The script copy is also dead code: grep shows compute_file_id is defined but never called anywhere in the repo.
- **Recommendation:** Delete compute_file_id from the script (it is unused). If the ID computation is ever needed there, import File.generate_id from src.storage.models instead.

### [LOW] _SCREENSHOT_RE (pass 4 screenshot check)

- **Kind:** reimplementation
- **Script:** `scripts/relabel_test_set.py:90, 188-191`
- **Src counterpart:** `src/ml/feature_extractor.py:87, 153-156` — `FileFeatureExtractor._matches_patterns / is_screenshot feature`
- **Evidence:** Script: `_SCREENSHOT_RE = re.compile("|".join(SCREENSHOT_PATTERNS), re.IGNORECASE)` then `elif ext_cat == "image" and _SCREENSHOT_RE.search(filename)`. Src: `'is_screenshot': self._matches_patterns(filename, SCREENSHOT_PATTERNS)` where _matches_patterns does `any(re.search(p, filename_lower) for p in patterns)`. Both are case-insensitive searches of the identical shared SCREENSHOT_PATTERNS list against the filename.
- **Divergence:** Mechanics only: single IGNORECASE alternation regex vs lowercase-then-per-pattern search; equivalent results for the all-lowercase patterns in SCREENSHOT_PATTERNS. The script's input samples are FileFeatureExtractor feature dicts (they use its keys: parent_folder, extension_category, filepath), so each sample already carries the src-computed is_screenshot boolean.
- **Recommendation:** Drop _SCREENSHOT_RE and read the sample's existing `is_screenshot` feature (computed by src/ml/feature_extractor from the same constant), or call FileFeatureExtractor._matches_patterns; keeps matching semantics in one place.

### [LOW] classify_by_ocr (screenshot keyword scoring loop)

- **Kind:** partial-overlap
- **Script:** `scripts/shared/ocr_classifier.py:623-629`
- **Src counterpart:** `src/classifiers/content_classifier.py:254-269` — `ContentClassifier.score_all_categories`
- **Evidence:** Script (625-629): `hits = sum(1 for kw in keywords if kw in text_lower)` / `if hits:` / `screenshot_scores[category] = hits / len(keywords)`. Src (264-267): `hits = sum(1 for kw in keywords if kw in combined)` / `if hits:` / `scores[category] = hits / len(keywords)`. Identical fraction-of-keywords scoring formula; the same script function then delegates to `content_classifier.score_all_categories(text, image_path.name)` at ocr_classifier.py:634 for the Schema.org table, so the algorithm appears both inlined and delegated in one function. content_organizer.py:108-111 documents the shared semantics ('classify_by_ocr() scores as hits/len(keywords)').
- **Divergence:** Script version applies the loop to SCREENSHOT_KEYWORDS (local table) and additionally records raw hit counts in screenshot_hits for the SCREENSHOT_MIN_HITS >= 2 gate; src version matches against text+filename combined (`f"{text.lower()} {filename.lower()}"`) over the Schema.org keyword table and returns only scores, no hit counts.
- **Recommendation:** Generalize the scoring into one table-parameterized helper in src (e.g. a static ContentClassifier method or module function taking (text, keyword_table) and returning {category: (hits, score)}), have score_all_categories and classify_by_ocr's screenshot pass both call it, keeping the SCREENSHOT_MIN_HITS gate in the script. Note the threshold in content_organizer.py is calibrated to the hits/len(keywords) scale, so the formula must not change.

## Refuted candidates (checked, not duplication)

- `scripts/update_report_with_labels.py` — update_report (apply-corrections loop + category-change stats): The overlap is only the generic loop-and-tally idiom. Script (scripts/update_report_with_labels.py:101-145) matches DB labeling-session ground truth by path then filename, updates in place only when old != new, stamps label_source='database_verified', tracks matched_by_path/matched_by_filename/not_found/unchanged/updated_files with a two-level change key "{old_cat}/{old_sub} -> {new_cat}/{new_sub}" (line 128), then rewrites report metadata and the JSON file. Src (src/feedback/feedback_loop.py:119-192) applies learned filename-pattern suggestions from CorrectionFeedbackSystem gated by confidence >= 0.85 (line 144), works on result.copy(), sets feedback_suggestion/feedback_applied, and tallies a one-level key "{original} -> {new}" (line 187) into a different stats schema (total/suggestions_made/auto_applied/categories_changed) with no file I/O. Even the cited "identical" tally lines differ in key format and field names. The script imports nothing from src/feedback, and batch_apply_corrections is hardwired to self.feedback.get_suggestion, so it cannot serve as the script's implementation without redesign — materially different logic AND different data; no shared block at drift risk.

- `scripts/shared/filename_classifier.py` — no-extension system-file rules + .tpl/.sample/.icns/Makefile rules: The claimed kind (reimplementation of a src counterpart) does not hold. (1) No delegation is possible or intended: scripts/shared/filename_classifier.py is itself the shared src-consumed module for the content path (imported by src/organizers/content_organizer.py:24; its docstring lines 4-9 names its entry points, which do not include name_organizer), while src/organizers/name_organizer.py backs the separate 'organize-files name' CLI mode (src/cli.py:48). (2) The src side does not cover the script's behavior: of the ~15 no-extension rules in the script's main claimed block (1399-1466), only ONE — line 1456 r"^[A-Z][a-z]+_[A-Z][a-z]+$" — has any counterpart (name_organizer.py:303); numeric-ID (1412), hex-hash (1416), GMT/UTC (1432), ChangeLog (1436), CamelCase (1424), hyphenated-tool (1420), query-param (1444), and js(1) (1464) rules have none. (3) Every overlapping token routes to a conflicting destination in a deliberately different taxonomy: .sample → ("technical","config") at script:748-750 vs ('.Trash','BuildArtifacts') at name_organizer:136/422; .icns → ("game_assets","other") at script:1372-1374 vs ('.Trash','BuildArtifacts') at 133/422; .tpl → ("technical","templates") at script:1395-1397 vs ('Technical/Code','Other') at 172/427; city regex → ("technical","other") vs ('Data','LocationData') at 303/543; even .ico diverges (script:1368 technical/config vs name_organizer:42 plain image extension). Consolidating would change behavior of one mode. The residue — one verbatim regex plus ~5 tokens (.tpl/.sample/.icns/makefile/tsserver) — is convergent recognition of the same file corpus by two independent features, which the finder's own divergence note concedes ("parallel evolution rather than a copy"), not consolidatable duplication.

## Out-of-scope observations

Surfaced by the completeness critic; src-internal, so outside this audit's scope but worth recording:

- `content_organizer.py`'s Technical/ extension map (~lines 240-330) overlaps `mime_classifier.py`'s extension routing.
- `src/organizers/category_config.py` defines the GameAssets folder map twice (lines 77-82 and 188-193).
- `scripts/__pycache__` holds orphan `.pyc` files for deleted modules (`clip_naming`, `clip_refinement`, `ocr_utils`, `screenshot_renamer`, `image_content_renamer`, `analyze_renamed_files`, script-level `file_organizer`) — stale build artifacts.
