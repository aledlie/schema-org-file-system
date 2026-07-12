"""Shared file operation utilities."""
from pathlib import Path

# OS/metadata junk that file walks should ignore rather than treat as user
# data: exact basenames plus the AppleDouble "._*" resource-fork prefix.
IGNORED_FILENAMES = frozenset({".DS_Store", "Thumbs.db", ".localized", "desktop.ini"})
APPLEDOUBLE_PREFIX = "._"


def is_os_junk_file(name: str) -> bool:
  """True if `name` (a basename) is OS/metadata junk that should be skipped."""
  return name in IGNORED_FILENAMES or name.startswith(APPLEDOUBLE_PREFIX)


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
