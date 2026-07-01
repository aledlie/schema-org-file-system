# Option C — Demote `person` from a category to a relationship

> **Status:** Planned, not yet implemented. Tracked in [`docs/BACKLOG.md`](docs/BACKLOG.md).
> Reconciles the `person` vs `personal` taxonomy overlap.

## Context

The classifier emits two overlapping labels for the same kind of file:
- **`person`** (a top-level *category*) → routes to `Person/{PersonName}/` — an **entity axis** (group by WHO).
- **`personal`** (a document *class*) → routes to `Personal/{Employment,Identification,Certificates,Other}/` — a **doc-class axis** (group by WHAT).

They collide: the *same* resume becomes `person` as a PDF but `personal` as a scanned image, purely from stage order and file type. This produces avoidable evaluation misses (label `personal` vs prediction `person`) and a confusing taxonomy.

**The fix (Option C):** stop treating `person` as a mutually-exclusive category. Classify every file by its **document class** (`personal`, `medical`, `legal`, …). Person attribution already lives in the graph as `file→person` edges (`add_file_to_person(..., role="mentioned")`, category-independent). `Person/{Name}/` becomes a **derived symlink view** regenerated from those edges. Existing on-disk `Person/` files are migrated into doc-class folders (dry-run first).

**Outcome:** one classification axis (doc class), person browsing preserved as a regenerable view, the PDF/image divergence eliminated, and `personal` test labels finally match production output.

---

## Key facts established during research

- **Production organizer** = `scripts/file_organizer_content_based.py` (`ContentBasedFileOrganizer`), wired to `organize-files content` and the evaluator.
- **Dormant parallel copy** = `src/organizers/content_organizer.py` (`ContentOrganizer`) — imported only by `src/organizers/__init__.py` + its own tests; runtime-dead. **In scope** (keep parity + fix tests).
- **`person` is emitted from FOUR sites, not one.** The primary is shared code both organizers delegate to:
  - `scripts/shared/filename_classifier.py::classify_by_filename_patterns` — `("person","contacts",…)` at **528, 547, 553, 729**; also `("person","travel"|"events"|"other",…)` at **1511, 1571, 1590, 1600, 1604**. Runs at PRIORITY 0b (`detect_file_category:2830`), **before** the others.
  - `scripts/file_organizer_content_based.py::classify_by_person` (2284–2360) — PRIORITY 1 (2860).
  - `scripts/file_organizer_content_based.py::_identify_person_from_id_ocr` — `("person","contacts",…)` ~3054–3062.
  - The dormant organizer mirrors these (`content_organizer.py:638,645,700–710`).
  - **Fixing the shared filename classifier is the highest-leverage edit — it hits both organizers at once.** Editing only `classify_by_person` will NOT remove `person` from output.
- Content classifier (`src/classifiers/content_classifier.py`) **never** emits `person`, only `personal` (subcats employment/identification/certificates/other, keywords at 108–121).
- Routing: `get_destination_path` person branches at `file_organizer_content_based.py:3447` (`Person/{name}`) and `3456` (`Person/Unknown`); folder maps `"person"` @1682 / `"personal"` @1616. Dormant equivalents at `content_organizer.py:1006/1013` and map @274–284.
- Storage: `graph_store.py` has `add_file_to_person`/`get_or_create_person` but **no reverse query**. `Person.files` relationship via `file_people` (has `role`) at `models.py:781`. Migration pattern `migration.py::run_migration(db_path, dry_run=False)`, CLI-wired as `migrate-ids`. File move = `shutil.move` (3759); collision helper `scripts/shared/file_ops.py::resolve_collision`. **No symlink code exists yet.**
- On disk `~/Documents/Person/` = **38 files**, DB has only ~8 rows matching `%/Person/%` → **~30 orphans with no DB row / no recorded doc-class**. Tree mixes NAME dirs (`Alyshia Ledlie`, `Kenneth Reitz`, `Isabel Budenz`) with SUBCATEGORY dirs (`Identity`, `Employment`, `Events`) and arbitrary nesting. `people` table contains false positives (`Introductory Meeting`, `Integrity Studio`, `Alyshia Ledlie Member Id`).

---

## Subcategory mapping (person subcat → personal subcat)

| person subcat | → personal subcat | notes |
|---|---|---|
| contacts | **contacts** (NEW) | resumes/CVs/vCards; avoids lossy merge into employment and rescues bare vCards from `uncategorized` |
| employees, references | employment | |
| clients, travel, events, other, journal, family | other | low-value distinctions; collapse to `Personal/Other` |
| (`_identify_person_from_id_ocr`) | identification | ID docs are identification, not contacts |

New `personal/contacts` subcategory touches: `content_classifier.py` (108–121 keywords), and the `personal` folder map in **both** organizers.

---

## Implementation steps

### Phase 1 — Classification: stop emitting `person`
1. **`scripts/shared/filename_classifier.py`** (primary): replace every `("person", <subcat>, …, people)` return with `("personal", <mapped_subcat>, …, people)` per the table. **Preserve the `people` list in the tuple** — it must keep flowing to the graph. Covers 528/547/553/729/1511/1571/1590/1600/1604.
2. **`scripts/file_organizer_content_based.py`**:
   - `classify_by_person` (2284–2360): return `("personal", <mapped_subcat>, people_names)` instead of `("person", …)`.
   - `_identify_person_from_id_ocr` (~3054): return `("personal","identification", people)`.
   - `detect_file_category` (2845–2874): unchanged tuple shape; `people_names` still threaded through position 5.
3. **`src/classifiers/content_classifier.py`**: add `contacts` subcategory under `personal` (keywords: resume, cv, vcard, contact, curriculum vitae).

### Phase 2 — Routing: retire the `person` folder branches
4. **`get_destination_path`** (`file_organizer_content_based.py:3447–3458`): delete the two `category=="person"` branches. Files now route via the `personal` folder map. Add `"contacts": "Personal/Contacts"` to the `personal` map (@1616).
5. Remove the now-dead `"person": {…}` folder map (@1682) — or leave a one-line comment marking it retired. `people_names` graph persistence (3609–3614) is **unchanged** (category-independent).
6. **Dormant `src/organizers/content_organizer.py`**: mirror all of the above — returns @638/645, path building @1006/1013, maps @274–284.

### Phase 3 — Graph query for the view
7. **`src/storage/graph_store.py`**: add `get_all_people_with_files(session, min_files=1)` and `get_files_by_person(person_id_or_name, session)` following the existing `get_session()`/session pattern. Filter obvious non-person names (heuristic: skip entries whose name matches an org/keyword denylist, e.g. contains `Studio`, `Meeting`, `Member Id`, `Inc`, `LLC`). Return `(display_name, [file current_paths])`.

### Phase 4 — Derived symlink view
8. **New `src/storage/person_view_generator.py`** — `PersonViewGenerator` (models after `JSONMigrator`):
   - `generate(view_root=~/Documents/Person, dry_run=True, apply=False)`.
   - For each person with files: create `view_root/{SanitizedName}/` and `Path.symlink_to()` each file's real (doc-class) path; resolve name clashes with `resolve_collision`.
   - **Idempotent regeneration:** before writing, remove **only** existing entries where `os.path.islink(p)` is true. **Abort with a clear error if any real (non-symlink) file remains under `view_root`** — never delete real data.
9. **`src/cli.py`**: register `organize-files person-view [--view-root] [--apply]` (dry-run default), mirroring the `migrate-ids` wiring (243–250 / cmd_migrate 73–82).

### Phase 5 — Migrate existing on-disk `Person/` files (RISKY — see data-safety)
10. **New migration** (own module or extend `migration.py`), CLI `organize-files migrate-person --apply` (dry-run default):
    - **Filesystem-walk driven, DB advisory** (on-disk is the superset; ~30 files have no DB row).
    - Walk `~/Documents/Person/**`. For each real file, choose target `Personal/{subcat}`:
      1. if a DB row exists → use its subcat mapped through the table;
      2. else map by the on-disk **subfolder name**: `Identity/`→identification, `Employment/`→employment, `Resumes/`→employment, top-level name-dir → contacts, `Events/`→other, else → **other (flagged)**.
    - Move via `shutil.move` **after** `resolve_collision` (never silent-overwrite). Update the DB `current_path` where a row exists.
    - Write `migrate-person-manifest.json` (src→dst per file) enabling `--rollback`.
    - **Ordering rule:** migration MUST fully empty `~/Documents/Person/` of real files **before** `person-view` writes symlinks back into it (view root == migration source root).

### Phase 6 — Tests & docs
11. Update `tests/unit/test_content_organizer.py` (204–220, 294, 322): assert `personal/{contacts,employment,identification}` instead of `person`; keep the people-extraction assertions.
12. New tests: `filename_classifier` returns `personal` not `person`; `get_files_by_person`/`get_all_people_with_files`; `PersonViewGenerator` dry-run + idempotent regen + real-file-abort guard; migration dry-run mapping + collision + rollback (use a tmp tree, never touch real `~/Documents`).
13. Update `CLAUDE.md` (Classification Priority #2, Output Folders, new commands) and close the BACKLOG item recording the chosen convention.

---

## Data-safety analysis (Phase 5 hazards)

- **View root == migration source root** (`~/Documents/Person/`). Enforce: migrate-out completes → verify no real files remain → only then generate symlink view. The view generator aborts if it finds a non-symlink under the root.
- **`shutil.move` silently overwrites** an existing dest → always `resolve_collision` first.
- **Orphans (~30 files, no DB row)** → handled by the filesystem walk + subfolder-name mapping; coarse but **lossless at the file level** (every file moved, none deleted).
- **Never re-run OCR/CLIP** during migration — preserves prior user intent and stays fast; accept coarse subcat over risky re-derivation.
- **Rollback:** every move recorded in a manifest; `--rollback` reverses it.
- **Dry-run is the default**; `--apply` required to touch disk.
- **False-positive people** filtered out of the view by the denylist in `get_all_people_with_files`.

---

## Verification (end-to-end)

1. `pytest tests/unit/test_content_organizer.py tests/unit/test_filename_classifier.py` (updated) → green.
2. Unit-test the new graph queries + `PersonViewGenerator` against a tmp DB/tree.
3. `organize-files content --source <fixtures> --dry-run` → confirm a resume/vCard/ID now report `Personal/{Contacts,Employment,Identification}`, and **no** `Person/` category appears in output.
4. `organize-files evaluate --classifier content --test-data results/ml_data/test.json` → `person`↔`personal` misses gone; `personal` support up.
5. `organize-files migrate-person` (dry-run) on a **copy** of `~/Documents/Person/` → inspect manifest; then `--apply` on the copy; verify source emptied, files under `Personal/...`, manifest complete; test `--rollback`.
6. `organize-files person-view` (dry-run then `--apply`) on the copy → `Person/{Name}/` populated with symlinks resolving to real files; re-run to confirm idempotent; drop a real file in the root and confirm it aborts.
7. `grep -rn '"person"' scripts/ src/` → only entity/relationship/schema.org-type usages remain (no category-label usages).
