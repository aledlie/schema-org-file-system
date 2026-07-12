#!/usr/bin/env python3
"""
Derived Person/{Name}/ symlink view generator.

Regenerates a browsable `Person/{Name}/` tree of symlinks pointing at the
real (doc-class) files recorded against each person in the graph. See
PERSON_TAXONOMY_OPTION_C_PLAN.md, Phase 4, for the design this implements.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# scripts/ isn't a package on sys.path by default outside of pytest and the
# organize-files CLI (both of which add it); insert it lazily here so this
# module also works when imported directly, mirroring the existing
# sys.path.insert pattern used by scripts/file_organizer_content_based.py.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.file_ops import is_os_junk_file, resolve_collision  # noqa: E402

DEFAULT_VIEW_ROOT = Path("~/Documents/Person")
DEFAULT_MIN_FILES = 1

# Same character set stripped by scripts/file_organizer_content_based.py's
# sanitize_company_name, so person and company folder names follow one
# filesystem-safety convention across the codebase.
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_MAX_SANITIZED_NAME_LENGTH = 50
_FALLBACK_SANITIZED_NAME = "Unknown"


class PersonViewRealFileError(Exception):
    """
    Raised when real (non-symlink) files are found under the view root.

    The view root doubles as the Phase 5 migration source; a real file here
    means migration hasn't finished (or something else wrote into the view),
    so regenerating must abort rather than risk masking or losing data.
    """

    def __init__(self, real_file_paths: List[Path]):
        self.real_file_paths = real_file_paths
        listing = "\n".join(f"  - {p}" for p in real_file_paths)
        super().__init__(
            "Refusing to regenerate the Person/ view: real (non-symlink) "
            "files exist under the view root. Move or remove them (see "
            "migrate-person) before re-running with apply=True:\n"
            f"{listing}"
        )


def _sanitize_person_name(name: str) -> str:
    stripped = _INVALID_FILENAME_CHARS.sub("", name)
    collapsed = " ".join(stripped.split())
    if len(collapsed) > _MAX_SANITIZED_NAME_LENGTH:
        collapsed = collapsed[:_MAX_SANITIZED_NAME_LENGTH].strip()
    return collapsed or _FALLBACK_SANITIZED_NAME


class PersonViewGenerator:
    """
    Regenerates view_root/{SanitizedName}/ as symlinks to each person's
    real files, derived from GraphStore.get_all_people_with_files().

    Modeled on src/storage/migration.py's JSONMigrator: a dry-run-by-default
    generator/migrator class returning a summary dict rather than raising
    on partial failure (per-file errors are collected, not fatal).
    """

    def __init__(self, graph_store: Any, view_root: Optional[Path] = None):
        self.graph_store = graph_store
        self.view_root = (view_root if view_root is not None else DEFAULT_VIEW_ROOT).expanduser()

    def generate(
        self,
        dry_run: bool = True,
        apply: bool = False,
        min_files: int = DEFAULT_MIN_FILES,
    ) -> Dict[str, Any]:
        """
        Regenerate the Person/ view.

        Args:
            dry_run: If True (default), compute and report what would
                happen without touching the filesystem at all.
            apply: Must be True (and dry_run False) for the run to write
                anything. Both flags are checked so an accidental
                apply=True, dry_run=True call still can't write.
            min_files: Minimum files a person must have to appear in the view.

        Returns:
            {"people": N, "symlinks_created": N, "removed_stale": N,
             "dry_run": bool, "errors": [...]}
        """
        errors: List[str] = []
        people = self.graph_store.get_all_people_with_files(min_files=min_files)

        # Only files that still exist on disk become symlinks; a graph row whose
        # current_path was moved/deleted (e.g. by a later reorg) would otherwise
        # yield a dangling link. Precompute the valid count and the missing
        # targets so the dry-run's numbers match what apply actually does
        # (apply's _write_view performs the same existence skip).
        missing_targets = [
            path
            for _display_name, file_paths in people
            for path in file_paths
            if not Path(path).exists()
        ]
        valid_targets = sum(len(paths) for _, paths in people) - len(missing_targets)

        summary: Dict[str, Any] = {
            "people": len(people),
            "symlinks_created": valid_targets,
            "removed_stale": 0,
            "dry_run": dry_run,
            "errors": errors,
        }

        should_write = apply and not dry_run
        if not should_write:
            for path in missing_targets:
                errors.append(f"source file missing, would skip: {path}")
            for real_file in self._find_real_files():
                errors.append(f"blocked by real file (would abort apply): {real_file}")
            return summary

        summary["removed_stale"] = self._remove_stale_symlinks()

        # The abort guard runs after stale-symlink removal, per the plan's
        # data-safety section: only a *real* leftover file blocks a run.
        remaining_real_files = self._find_real_files()
        if remaining_real_files:
            raise PersonViewRealFileError(remaining_real_files)

        summary["symlinks_created"] = self._write_view(people, errors)
        return summary

    def _iter_view_entries(self) -> Iterable[Path]:
        if not self.view_root.exists():
            return
        for dirpath, _dirnames, filenames in os.walk(self.view_root):
            for filename in filenames:
                if is_os_junk_file(filename):
                    continue
                yield Path(dirpath) / filename

    def _find_real_files(self) -> List[Path]:
        return [p for p in self._iter_view_entries() if not os.path.islink(p)]

    def _find_symlinks(self) -> List[Path]:
        return [p for p in self._iter_view_entries() if os.path.islink(p)]

    def _remove_stale_symlinks(self) -> int:
        removed = 0
        for path in self._find_symlinks():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        self._prune_empty_dirs()
        return removed

    def _prune_empty_dirs(self) -> None:
        if not self.view_root.exists():
            return
        for dirpath, _dirnames, _filenames in os.walk(self.view_root, topdown=False):
            if Path(dirpath) == self.view_root:
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                continue

    def _write_view(self, people: List[Tuple[str, List[str]]], errors: List[str]) -> int:
        created = 0
        for display_name, file_paths in people:
            person_dir = resolve_collision(self.view_root / _sanitize_person_name(display_name))
            try:
                person_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"failed to create directory {person_dir}: {exc}")
                continue

            for file_path in file_paths:
                src = Path(file_path)
                if not src.exists():
                    errors.append(f"source file missing, skipped: {file_path}")
                    continue

                dst = resolve_collision(person_dir / src.name)
                try:
                    dst.symlink_to(src)
                    created += 1
                except OSError as exc:
                    errors.append(f"failed to symlink {dst} -> {src}: {exc}")

        return created
