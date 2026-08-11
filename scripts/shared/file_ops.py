"""Shared file operation utilities."""

from pathlib import Path

from shared.constants import SIDECAR_DIR_SUFFIXES

# OS/metadata junk that file walks should ignore rather than treat as user
# data: exact basenames plus the AppleDouble "._*" resource-fork prefix.
IGNORED_FILENAMES = frozenset({".DS_Store", "Thumbs.db", ".localized", "desktop.ini"})
APPLEDOUBLE_PREFIX = "._"

# Hidden filenames that organizers should NOT skip (they are useful to end users).
_ALLOWED_HIDDEN = frozenset({".gitignore", ".env.example"})

# Directories that organizers should never descend into.
_SKIP_DIRS = frozenset({"__pycache__", ".git", "node_modules", ".venv", "venv"})


def is_os_junk_file(name: str) -> bool:
    """True if `name` (a basename) is OS/metadata junk that should be skipped."""
    return name in IGNORED_FILENAMES or name.startswith(APPLEDOUBLE_PREFIX)


def should_skip_file(file_path: Path) -> bool:
    """Return True if *file_path* should be excluded from file-organization walks.

    Canonical skip rules (single source of truth — both the content organizer
    and the type organizer delegate here):

    - Hidden files, except a small allowlist (``.gitignore``, ``.env.example``)
    - OS/metadata junk (``IGNORED_FILENAMES``)
    - Files whose path contains a dev-tooling directory (``__pycache__``, etc.)
    - Files nested inside a browser "Save Page As" sidecar folder (``*_files/``)
    """
    name = file_path.name

    if name.startswith(".") and name not in _ALLOWED_HIDDEN:
        return True

    if name in IGNORED_FILENAMES:
        return True

    if any(skip_dir in file_path.parts for skip_dir in _SKIP_DIRS):
        return True

    # Skip browser "Save Page As" sidecar folders (e.g. "foo_files/"): the
    # file lives under a parent dir whose name ends with a known suffix.
    if any(part.lower().endswith(SIDECAR_DIR_SUFFIXES) for part in file_path.parent.parts):
        return True

    return False


def resolve_collision(dest_path: Path) -> Path:
    """Resolve filename collision by appending incrementing counter.

    Given /foo/bar.png where bar.png exists, returns /foo/bar_1.png, etc.
    """
    if not dest_path.exists():
        return dest_path
    stem = dest_path.stem
    ext = dest_path.suffix
    parent = dest_path.parent
    counter = 1
    while dest_path.exists():
        dest_path = parent / f"{stem}_{counter}{ext}"
        counter += 1
    return dest_path
