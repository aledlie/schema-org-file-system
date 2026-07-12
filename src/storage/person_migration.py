#!/usr/bin/env python3
"""
Person/ -> Personal/{subcat}/ Migration Tool (Option C, Phase 5).

Moves the pre-existing on-disk files under `~/Documents/Person/` into the new
doc-class folders under `~/Documents/Personal/{subcat}/`, since the `person`
filing category is being retired in favor of `personal` (see
`PERSON_TAXONOMY_OPTION_C_PLAN.md`). `Person/` will later be regenerated as a
symlink view (a separate, not-yet-built generator) and that generator aborts
if it finds any real (non-symlink) file under its root -- so this migration
must fully empty `Person/` of real files.

Filesystem-walk driven, DB advisory only: on-disk `Person/` is a strict
superset of what the DB knows about (most existing files predate the graph
store, or were moved outside of it), so enumerating from DB rows would miss
the majority of files. The DB is consulted per-file, as an optional hint for
picking a more precise subcategory than the on-disk folder name alone allows.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import File, FileStatus
from .graph_store import GraphStore

try:
    from ..constants import SEPARATOR_WIDTH_MEDIUM
except ImportError:
    from constants import SEPARATOR_WIDTH_MEDIUM

try:
    from shared.file_ops import resolve_collision
except ImportError:  # pragma: no cover - fallback when scripts/ isn't already on sys.path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from shared.file_ops import resolve_collision


DEFAULT_PERSON_ROOT = Path("~/Documents/Person").expanduser()
DEFAULT_DOCUMENTS_ROOT = Path("~/Documents").expanduser()
DEFAULT_MANIFEST_PATH = Path("person-migrate-manifest.json")

# OS/metadata junk that must never be migrated (matched on exact basename, plus
# the AppleDouble "._*" resource-fork prefix). These would otherwise be swept
# into Personal/Other and even collision-renamed (.DS_Store_1, ...).
_IGNORED_FILENAMES = frozenset({".DS_Store", "Thumbs.db", ".localized", "desktop.ini"})
_APPLEDOUBLE_PREFIX = "._"

# Legacy top-level category name a `person`-filed row was stored under.
PERSON_CATEGORY_NAME = "person"

# `personal` subcategories a file can be migrated into.
SUBCAT_CONTACTS = "contacts"
SUBCAT_EMPLOYMENT = "employment"
SUBCAT_IDENTIFICATION = "identification"
SUBCAT_OTHER = "other"

# Where a migration plan's `subcat` came from.
SUBCAT_SOURCE_DB = "db"
SUBCAT_SOURCE_SUBFOLDER = "subfolder"
SUBCAT_SOURCE_FALLBACK = "fallback"

MIGRATION_REASON = "migrated from legacy Person/ category (Option C phase 5)"
ROLLBACK_REASON = "rolled back Option C phase 5 person migration"

# A person-name subfolder is expected to be at least this many Title Case words
# (e.g. "Alyshia Ledlie"). Used to distinguish NAME dirs from doc-class dirs
# that aren't in SUBFOLDER_NAME_TO_SUBCAT (which map to `other`, flagged).
MIN_NAME_WORD_COUNT = 2

# Table from PERSON_TAXONOMY_OPTION_C_PLAN.md: legacy `person` DB subcategory
# -> new `personal` subcategory.
DB_PERSON_SUBCAT_TO_PERSONAL_SUBCAT: Dict[str, str] = {
    "contacts": SUBCAT_CONTACTS,
    "employees": SUBCAT_EMPLOYMENT,
    "references": SUBCAT_EMPLOYMENT,
    "clients": SUBCAT_OTHER,
    "travel": SUBCAT_OTHER,
    "events": SUBCAT_OTHER,
    "other": SUBCAT_OTHER,
    "journal": SUBCAT_OTHER,
    "family": SUBCAT_OTHER,
}

# On-disk subfolder name (immediately under the walk root) -> `personal`
# subcategory, used only when no usable DB hint exists for a file. Any
# subfolder not in this table is either a person's NAME dir (-> contacts,
# see _looks_like_person_name_dir) or unrecognized (-> other, flagged).
SUBFOLDER_NAME_TO_SUBCAT: Dict[str, str] = {
    "Identity": SUBCAT_IDENTIFICATION,
    "Employment": SUBCAT_EMPLOYMENT,
    "Resumes": SUBCAT_EMPLOYMENT,
    "Events": SUBCAT_OTHER,
}

# Destination folder (relative to documents_root) for each `personal` subcat.
# Mirrors ContentBasedFileOrganizer.category_paths["personal"].
PERSONAL_SUBCAT_FOLDER: Dict[str, str] = {
    SUBCAT_CONTACTS: "Personal/Contacts",
    SUBCAT_EMPLOYMENT: "Personal/Employment",
    SUBCAT_IDENTIFICATION: "Personal/Identification",
    SUBCAT_OTHER: "Personal/Other",
}


@dataclass
class MigrationEntry:
    """One planned (or executed) file move."""

    src: str
    dst: str
    subcat: str
    subcat_source: str
    file_id: Optional[str] = None
    flagged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src": self.src,
            "dst": self.dst,
            "subcat": self.subcat,
            "subcat_source": self.subcat_source,
            "file_id": self.file_id,
            "flagged": self.flagged,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MigrationEntry":
        return MigrationEntry(
            src=data["src"],
            dst=data["dst"],
            subcat=data["subcat"],
            subcat_source=data["subcat_source"],
            file_id=data.get("file_id"),
            flagged=data.get("flagged", False),
        )


def _iter_real_files(root: Path) -> Iterator[Path]:
    """Yield every real (non-symlink) file under root, deterministically ordered."""
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not (path.is_file() and not path.is_symlink()):
            continue
        if path.name in _IGNORED_FILENAMES or path.name.startswith(_APPLEDOUBLE_PREFIX):
            continue
        yield path


def _find_db_file(session: Session, path: Path) -> Optional[File]:
    """Look up a File row by either its current or original path."""
    path_str = str(path)
    return (
        session.query(File)
        .filter(or_(File.current_path == path_str, File.original_path == path_str))
        .first()
    )


def _lookup_db_person_subcat(db_file: File) -> Optional[str]:
    """Return the legacy `person/{subcat}` this file was previously filed under, if any."""
    for category in db_file.categories:
        if category.parent is not None and category.parent.name == PERSON_CATEGORY_NAME:
            return category.name
    return None


def _looks_like_person_name_dir(subfolder_name: str) -> bool:
    """Heuristic: Person/ subdirs are either a known doc-class name (Identity,
    Employment, ...) or a literal person name (e.g. "Alyshia Ledlie"). A name
    dir is multi-word Title Case, alphabetic (allowing hyphens) per word."""
    words = subfolder_name.split()
    if len(words) < MIN_NAME_WORD_COUNT:
        return False
    return all(word[:1].isupper() and word.replace("-", "").isalpha() for word in words)


def _determine_subcat(
    walk_root: Path, path: Path, db_subcat: Optional[str]
) -> "tuple[str, str, bool]":
    """Return (subcat, subcat_source, flagged) for a single on-disk file."""
    if db_subcat is not None:
        mapped = DB_PERSON_SUBCAT_TO_PERSONAL_SUBCAT.get(db_subcat)
        if mapped is not None:
            return mapped, SUBCAT_SOURCE_DB, False

    try:
        relative_parts = path.relative_to(walk_root).parts
    except ValueError:
        relative_parts = (path.name,)

    if len(relative_parts) <= 1:
        # File sits directly at the walk root -- no subfolder name to key off.
        return SUBCAT_OTHER, SUBCAT_SOURCE_FALLBACK, True

    subfolder = relative_parts[0]
    if subfolder in SUBFOLDER_NAME_TO_SUBCAT:
        return SUBFOLDER_NAME_TO_SUBCAT[subfolder], SUBCAT_SOURCE_SUBFOLDER, False
    if _looks_like_person_name_dir(subfolder):
        return SUBCAT_CONTACTS, SUBCAT_SOURCE_SUBFOLDER, False

    return SUBCAT_OTHER, SUBCAT_SOURCE_FALLBACK, True


def _resolve_collision_with_seen(dest: Path, seen: Set[Path]) -> Path:
    """Like resolve_collision, but also avoids destinations already claimed
    earlier in this same plan (which won't exist on disk yet, so
    resolve_collision alone can't see them)."""
    candidate = resolve_collision(dest)
    counter = 1
    stem, ext, parent = dest.stem, dest.suffix, dest.parent
    while candidate in seen:
        candidate = resolve_collision(parent / f"{stem}_{counter}{ext}")
        counter += 1
    return candidate


def build_migration_plan(
    person_root: Path = DEFAULT_PERSON_ROOT,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    db_path: Optional[str] = None,
) -> List[MigrationEntry]:
    """Walk person_root and compute the full migration plan. Never touches
    the filesystem or DB -- pure planning, safe to call for a dry run."""
    person_root = Path(person_root)
    documents_root = Path(documents_root)

    graph_store = GraphStore(db_path) if db_path else None
    session = graph_store.get_session() if graph_store else None

    entries: List[MigrationEntry] = []
    seen_destinations: Set[Path] = set()
    try:
        for src in _iter_real_files(person_root):
            db_file = _find_db_file(session, src) if session else None
            db_subcat = _lookup_db_person_subcat(db_file) if db_file else None
            subcat, source, flagged = _determine_subcat(person_root, src, db_subcat)

            dest_dir = documents_root / PERSONAL_SUBCAT_FOLDER[subcat]
            dest = _resolve_collision_with_seen(dest_dir / src.name, seen_destinations)
            seen_destinations.add(dest)

            entries.append(
                MigrationEntry(
                    src=str(src),
                    dst=str(dest),
                    subcat=subcat,
                    subcat_source=source,
                    file_id=db_file.id if db_file else None,
                    flagged=flagged,
                )
            )
    finally:
        if session:
            session.close()

    return entries


def apply_migration(entries: List[MigrationEntry], db_path: Optional[str] = None) -> int:
    """Execute a previously computed plan: move files on disk and, for any
    entry with a matching DB row, update its current_path. Returns the number
    of files actually moved."""
    graph_store = GraphStore(db_path) if db_path else None
    session = graph_store.get_session() if graph_store else None

    moved = 0
    try:
        for entry in entries:
            src = Path(entry.src)
            dst = Path(entry.dst)
            if not src.exists():
                continue  # already moved (e.g. a re-run of a prior apply)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved += 1

            if entry.file_id and graph_store:
                graph_store.update_file_status(
                    entry.file_id,
                    FileStatus.ORGANIZED,
                    destination=str(dst),
                    reason=MIGRATION_REASON,
                    session=session,
                )
    finally:
        if session:
            session.close()

    return moved


def write_manifest(entries: List[MigrationEntry], manifest_path: Path) -> None:
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps([entry.to_dict() for entry in entries], indent=2))


def load_manifest(manifest_path: Path) -> List[MigrationEntry]:
    raw_entries = json.loads(Path(manifest_path).read_text())
    return [MigrationEntry.from_dict(raw) for raw in raw_entries]


def migrate_person_files(
    person_root: Path = DEFAULT_PERSON_ROOT,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    db_path: Optional[str] = None,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    apply: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Migrate legacy on-disk Person/ files into Personal/{subcat}/ folders.

    Dry-run by default (mirrors migration.py's run_migration(dry_run=...)
    pattern) -- pass apply=True to actually move files and update the DB.
    Always writes the manifest (even in dry-run) so it can be inspected
    before deciding to apply.
    """
    person_root = Path(person_root).expanduser()
    documents_root = Path(documents_root).expanduser()
    manifest_path = Path(manifest_path)

    if verbose:
        print("=" * SEPARATOR_WIDTH_MEDIUM)
        print("Person/ -> Personal/{subcat}/ Migration")
        print("=" * SEPARATOR_WIDTH_MEDIUM)
        print(f"  Source root:      {person_root}")
        print(f"  Destination root: {documents_root}")

    entries = build_migration_plan(person_root, documents_root, db_path)
    flagged_entries = [entry for entry in entries if entry.flagged]

    if verbose:
        print(f"\n  Files found:                {len(entries)}")
        print(f"  Low-confidence (flagged):   {len(flagged_entries)}")
        for source_kind in (SUBCAT_SOURCE_DB, SUBCAT_SOURCE_SUBFOLDER, SUBCAT_SOURCE_FALLBACK):
            count = sum(1 for entry in entries if entry.subcat_source == source_kind)
            print(f"    subcat_source={source_kind:<10} {count}")

    write_manifest(entries, manifest_path)
    if verbose:
        print(f"  Manifest written to: {manifest_path}")

    if not apply:
        if verbose:
            print("\n  [DRY RUN] No files moved, no DB rows updated")
        return {
            "dry_run": True,
            "planned": len(entries),
            "flagged": len(flagged_entries),
            "manifest_path": str(manifest_path),
            "entries": [entry.to_dict() for entry in entries],
        }

    moved = apply_migration(entries, db_path)
    if verbose:
        print(f"\n  Moved {moved}/{len(entries)} files")

    return {
        "dry_run": False,
        "migrated": moved,
        "flagged": len(flagged_entries),
        "manifest_path": str(manifest_path),
        "entries": [entry.to_dict() for entry in entries],
    }


def rollback_person_migration(
    manifest_path: Path,
    db_path: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Reverse a prior apply run using the manifest it wrote. Moves every file
    from its recorded `dst` back to its recorded `src` -- never recomputes
    destinations, so collision-renamed paths are handled correctly. Processed
    in reverse manifest order (last-moved-first-reversed); safe regardless of
    order since migration moves never overlap in destination.
    """
    manifest_path = Path(manifest_path)
    entries = load_manifest(manifest_path)

    if verbose:
        print(f"Rolling back {len(entries)} entries from {manifest_path}")

    graph_store = GraphStore(db_path) if db_path else None
    session = graph_store.get_session() if graph_store else None

    restored = 0
    try:
        for entry in reversed(entries):
            dst = Path(entry.dst)
            src = Path(entry.src)
            if not dst.exists():
                continue  # already rolled back, or was never actually applied
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            restored += 1

            if entry.file_id and graph_store:
                graph_store.update_file_status(
                    entry.file_id,
                    FileStatus.ORGANIZED,
                    destination=str(src),
                    reason=ROLLBACK_REASON,
                    session=session,
                )
    finally:
        if session:
            session.close()

    if verbose:
        print(f"  Restored {restored}/{len(entries)} files")

    return {"restored": restored, "total": len(entries)}
