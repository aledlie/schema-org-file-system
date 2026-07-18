"""Shared database connection utilities."""
from __future__ import annotations
import importlib.util
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Single-source DEFAULT_DB_PATH from src/constants.py. Loaded directly by file
# path (not `from src.constants import ...`) to avoid triggering the heavy
# ``src`` package __init__ and any scripts↔src import cycle from this low-level,
# broadly-imported util.
_CONSTANTS_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "constants.py"
_spec = importlib.util.spec_from_file_location("_src_constants", _CONSTANTS_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load constants module from {_CONSTANTS_PATH}")
_constants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_constants)
DEFAULT_DB_PATH = _constants.DEFAULT_DB_PATH


def get_db_connection(
  db_path: Path | str | None = None,
  row_factory: bool = True,
) -> sqlite3.Connection:
  """Get a SQLite connection.

  Caller is responsible for calling conn.close().
  Prefer db_connection() context manager to avoid leaks.

  Args:
    db_path: Path to database. Defaults to results/file_organization.db
    row_factory: If True, set row_factory to sqlite3.Row
  """
  path = Path(db_path) if db_path else DEFAULT_DB_PATH
  conn = sqlite3.connect(path)
  if row_factory:
    conn.row_factory = sqlite3.Row
  return conn


@contextmanager
def db_connection(
  db_path: Path | str | None = None,
  row_factory: bool = True,
) -> Generator[sqlite3.Connection, None, None]:
  """Context manager that opens and closes a SQLite connection.

  Does NOT auto-commit. After write operations, callers must either:
    - call ``conn.commit()`` explicitly, or
    - wrap the writes with ``with conn:`` (uses SQLite's implicit transaction).

  Usage:
    with db_connection() as conn:
        conn.execute(...)
        conn.commit()
  """
  conn = get_db_connection(db_path, row_factory)
  try:
    yield conn
  finally:
    conn.close()
