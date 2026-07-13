# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-12.

## Open Items

### Person-graph edge hygiene

Leaky denylist (prune and dead-path tooling shipped 2026-07-12).

**Status:** Open — gaps 1 and 3 closed (prune tooling, `--prune-missing`); gap 2 remains.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

Three related gaps surfaced while populating the `Person/{Name}/` symlink view; the remaining one is still handled by manual review.

1. ~~**No prune tooling for `file→person` edges.**~~ **Done (2026-07-12):** `GraphStore.remove_person_edge(file_id, person)` drops a single edge; `GraphStore.prune_person(name_or_id, dry_run=...)` deletes a person plus all its edges (clearing dependents' merge pointers, never touching files on disk), exposed as `organize-files prune-person <name-or-id>...` — dry-run by default, `--apply` backs up the DB (+ WAL/SHM sidecars) first. Tests: `tests/unit/test_graph_store_prune.py`.
2. **`get_all_people_with_files` denylist is leaky.** False-positive "people" (event/org names) still pass the org/keyword denylist — e.g. `Morning Train` (from `Burning_Flipside_Map.pdf`) — and would create spurious `Person/{Name}/` folders on `person-view --apply` unless pruned first. *Fix idea:* stronger heuristics (require given+family name shape, expand denylist) or a confirmation/review step before view generation.
3. ~~**Dead-path edges are cruft, not errors.**~~ **Done (2026-07-12):** `GraphStore.prune_missing_person_edges(dry_run=...)` drops edges whose file path (current_path, falling back to original_path) no longer exists on disk, keeping File and Person rows. Exposed as `--prune-missing` on both `organize-files person-view` (prunes before regenerating the view) and `organize-files index-people` (prunes after indexing); honors each command's `--apply`/dry-run flag. Tests: `tests/unit/test_graph_store_prune.py`.


