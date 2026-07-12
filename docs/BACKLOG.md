# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-12.

## Open Items

### Person-graph edge hygiene

No prune tooling, leaky denylist, and dead-path edge cruft.

**Status:** Open — workarounds documented, no code fix yet.
**Priority:** P3
**Source:** person-view / index-people operational session, 2026-07-12

Three related gaps surfaced while populating the `Person/{Name}/` symlink view. All are currently handled by manual ORM edits; each could be closed with a small amount of code.

1. **No prune tooling for `file→person` edges.** Neither the CLI nor `GraphStore` exposes a way to delete a person edge. Pruning is done directly via ORM (`file_people.delete().where(...)` plus deleting the orphaned `Person` row), after backing up `results/file_organization.db`. *Fix idea:* a `GraphStore.remove_person_edge` / `prune_person(name_or_id)` method, optionally wired to an `organize-files prune-person` command.
2. **`get_all_people_with_files` denylist is leaky.** False-positive "people" (event/org names) still pass the org/keyword denylist — e.g. `Morning Train` (from `Burning_Flipside_Map.pdf`) — and would create spurious `Person/{Name}/` folders on `person-view --apply` unless pruned first. *Fix idea:* stronger heuristics (require given+family name shape, expand denylist) or a confirmation/review step before view generation.
3. **Dead-path edges are cruft, not errors.** When a file's source moves or is scrubbed, `person-view` skips its edge (correctly, never erroring) but the stale edge lingers in the graph indefinitely. *Fix idea:* a `--prune-missing` flag on `index-people`/`person-view` that drops edges whose current source path no longer exists.


