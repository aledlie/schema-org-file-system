# Backlog Migrate - Implementation Examples

This document demonstrates the backlog migration workflow with real examples from the schema-org-file-system project.

## Example 1: Parse BACKLOG.md

**Input BACKLOG.md (before migration):**

```markdown
# Backlog

## Open Items

### R3 — Fix Image.open() file handle leak in image_content_renamer.py

**Status:** Pending

The `_get_date_string` method (line 149) calls `Image.open(image_path).convert("RGB")` without a context manager.
On macOS with HEIC files, Pillow can hold file descriptors open, causing issues when processing large directories.

**File:** `scripts/image_content_renamer.py:149`

---

### R8 — Add unit tests for scripts/shared/ module

**Status:** Pending

The six files in `scripts/shared/` have no unit test coverage. Existing test fixtures in `tests/conftest.py`
(`temp_dir`, `temp_db_path`, `sample_image_file`) would make it trivial to test utilities.

**Files:** `scripts/shared/*`, `tests/unit/test_shared.py` (new)
```

**Parsing Result:**

| ID | Title | Section | Status | Body | Impl Links |
|----|-------|---------|--------|------|------------|
| R3 | Fix Image.open() file handle leak in image_content_renamer.py | Review Findings | Pending | (contains file reference) | `scripts/image_content_renamer.py:149` |
| R8 | Add unit tests for scripts/shared/ module | Review Findings | Pending | (no explicit status change) | `scripts/shared/*`, `tests/unit/test_shared.py` |

**Decision:** Skip R3 and R8 (status is "Pending", not "Done/Resolved").

---

## Example 2: Parse & Migrate Completed Items

**Input BACKLOG.md (with completed items):**

```markdown
# Backlog

## Open Items

(No open items at this time.)

## Completed (Migrated 2026-03-28)

- R3 — Fixed Image.open() file handle leak [Resolved]
- R4 — Documented _ABBREV_TO_CONTENT priority [Resolved]
- R5 — Updated typing imports to modern syntax [Resolved]
```

**Workflow Step 1: Identify Completed Items**

Search for `[x]` checkboxes or "Resolved" status markers:
- R3: `[Resolved]` → Include
- R4: `[Resolved]` → Include
- R5: `[Resolved]` → Include

**Workflow Step 2: Resolve Target Version**

For each item, apply version resolution priority:

| Item | Method | Reasoning | Target Version |
|------|--------|-----------|-----------------|
| R3 | H5 (Fallback) | No commit hash, no version in path, section has no date | Latest (2.0.0) |
| R4 | H5 (Fallback) | Same as R3 | 2.0.0 |
| R5 | H5 (Fallback) | Same as R3 | 2.0.0 |

**Workflow Step 3: Create Changelog Entry**

Append to `docs/changelog/2.0.0/CHANGELOG.md`:

```markdown
### Review Resolutions

#### R3 — Fix Image.open() file handle leak in image_content_renamer.py

**Issue:** The `_get_date_string` method (line 149) calls `Image.open(image_path).convert("RGB")` without a context manager.
On macOS with HEIC files, Pillow can hold file descriptors open, causing issues when processing large directories.

**File:** `scripts/image_content_renamer.py:149`

**Status:** Resolved

---

#### R4 — Document _ABBREV_TO_CONTENT first-match priority in organize_to_existing.py

**Issue:** A filename like `_screenshot_landscape_photo.jpg` matches both abbreviations. The loop takes the first match with `break`,
making the result dependent on `CONTENT_ABBREVIATIONS` insertion order.

**File:** `scripts/organize_to_existing.py:64–67`

**Status:** Resolved

---

#### R5 — Update typing imports to modern syntax in analyze_renamed_files.py and image_content_renamer.py

**Issue:** Both scripts import `from typing import Dict, List, Optional, Tuple` (old-style) instead of using Python 3.10+ union syntax
(`str | None` instead of `Optional[str]`).

**Files:** `scripts/analyze_renamed_files.py:14`, `scripts/image_content_renamer.py:12`

**Status:** Resolved
```

**Workflow Step 4: Update BACKLOG.md**

Use Edit tool to remove only the migrated items and their sections:

```diff
--- a/docs/BACKLOG.md
+++ b/docs/BACKLOG.md
@@ -5,28 +5,4 @@ Context: repomix-output.xml (scripts/ directory snapshot, 2026-02-25).

 ## Open Items

-### R3 — Fix Image.open() file handle leak in image_content_renamer.py
-**Status:** Pending
-...
-
-### R4 — Document _ABBREV_TO_CONTENT first-match priority
-**Status:** Pending
-...
-
-### R5 — Update typing imports to modern syntax
-**Status:** Pending
-...
-
-## Completed (Migrated 2026-03-28)
-
-- R3 — Fixed Image.open() file handle leak [Resolved]
-- R4 — Documented _ABBREV_TO_CONTENT priority [Resolved]
-- R5 — Updated typing imports to modern syntax [Resolved]
+(No open items at this time.)
```

**Workflow Step 5: Summary**

```
Backlog Migration Complete
  Items migrated: 3 | Skipped: 0
  Versions updated: 2.0.0
```

---

## Example 3: Mixed Status (Some Pending, Some Resolved)

**Input BACKLOG.md:**

```markdown
## Open Items

### R1 — Pending item A
**Status:** Pending

### R2 — Completed item B
**Status:** [x] Resolved (commit abc1234d)

### R3 — Pending item C
**Status:** Pending
```

**Processing:**

| Item | Status | Action | Reason |
|------|--------|--------|--------|
| R1 | Pending | Skip | Not marked Done |
| R2 | Resolved | Migrate | Marked Done |
| R3 | Pending | Skip | Not marked Done |

**Result:**
- Only R2 is migrated to changelog
- R1 and R3 remain in BACKLOG.md
- Edit removes only R2 section from BACKLOG.md

---

## Example 4: Version Resolution with Commit Hash

**Item in BACKLOG.md:**

```markdown
### H1 — Commit shared utilities

Consolidates duplicated utilities. See implementation in commit 4b69100.

**Files:** `scripts/shared/__init__.py`, etc.
```

**Processing:**

1. Extract commit hash: `4b69100`
2. Get commit date: `git show --format=%ai 4b69100` → `2026-03-28`
3. Match to closest changelog version: 2.0.0 (released 2026-03-28)
4. Assign to version 2.0.0

---

## Example 5: Version Resolution with Path

**Item in BACKLOG.md:**

```markdown
### L2 — Document API changes

See implementation details in `docs/changelog/v1.9.0/CHANGELOG.md#api-changes`.

**Status:** [x] Resolved
```

**Processing:**

1. Extract path: `docs/changelog/v1.9.0/CHANGELOG.md`
2. Extract version: `v1.9.0`
3. Assign directly to v1.9.0

---

## Example 6: Update CHANGELOG.md Index

**Before:**

```markdown
# Changelog

All notable changes to this project are documented per version.

| Version | Date | Notes |
|---------|------|-------|
| [2.0.0](./2.0.0/CHANGELOG.md) | 2026-03-28 | Major refactoring |
| [v1](./v1/CHANGELOG.md) | 2025-08-15 | Initial release |
```

**After adding v1.9.0:**

```markdown
# Changelog

All notable changes to this project are documented per version.

| Version | Date | Notes |
|---------|------|-------|
| [2.0.0](./2.0.0/CHANGELOG.md) | 2026-03-28 | Major refactoring |
| [v1.9.0](./v1.9.0/CHANGELOG.md) | 2026-03-15 | Feature additions |
| [v1](./v1/CHANGELOG.md) | 2025-08-15 | Initial release |
```

---

## Migration Telemetry

When migration completes, emit:

```
[SKILL_COMPLETE] skill=backlog-migrate outcome=success migrated=8 skipped=0
```

Span attributes recorded:

| Span | Attribute | Value |
|------|-----------|-------|
| `plugin-post-tool` | `plugin.name=backlog-migrate` | Always set |
| `plugin-post-tool` | `plugin.output_size` | Bytes of final summary |
| `builtin-post-tool` | `builtin.tool=Edit` | For each BACKLOG.md removal |
| `builtin-post-tool` | `builtin.tool=Write` | For each changelog append |

---

## Key Rules Enforced

1. **Never delete non-Done items** — Only items marked Resolved/Done are migrated
2. **Preserve all cross-references** — Commit hashes, file paths, links remain intact
3. **Use Edit for BACKLOG.md** — Never rewrite entire file; use targeted deletions
4. **Group by section** — Maintain original organization (High Priority, Review Findings, etc.)
5. **Never re-migrate** — Skip items already in a changelog (H1 priority check)
6. **Clean sections** — Remove entire section headers for migrated items; never leave empty sections
7. **Table format for changelog** — Consistent formatting across all entries

---

## Edge Cases

### Case: Item with Multiple Implementation Links

```markdown
### M2 — Fix broken path reference

Scripts: `scripts/launch_timeline.sh`, related: `scripts/generate_timeline_data.py`

**Status:** [x] Resolved
```

**Action:** Preserve all file references in changelog entry.

### Case: Item Without Clear Version

```markdown
### L5 — Update docs

**Status:** [x] Resolved
```

**Resolution:** Use H5 fallback → assign to latest existing version (2.0.0).

### Case: Item Already in Changelog

During parsing, if an item ID (e.g., R3) is found in any existing `docs/changelog/*/CHANGELOG.md`:

```markdown
### R3 — Some item
**Status:** [x] Resolved
```

**Action:** Skip with note: "Already in changelog/2.0.0/CHANGELOG.md (H1 priority check)".

---

## Real-World Example: schema-org-file-system

**Migration Session (2026-03-28):**

8 items migrated from BACKLOG.md to `docs/changelog/2.0.0/CHANGELOG.md`:
- R3: Image.open() file handle leak
- R4: _ABBREV_TO_CONTENT documentation
- R5: Typing imports modernization
- R6: Pillow context manager semantics
- R7: db_connection() auto-commit docs
- R8: Unit tests for scripts/shared/

All assigned to version 2.0.0 via H5 fallback (no explicit version markers in items).

Final backlog state: "No open items at this time." — fully cleaned.
