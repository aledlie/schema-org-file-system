#!/usr/bin/env python3
"""
Generate scripts/d1/schema.sql from SQLAlchemy Base.metadata.

Run from the project root:
    python scripts/d1/generate_schema.py

The output file is the authoritative D1 schema — do not hand-edit it.
Edit src/storage/models.py instead, then re-run this script.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.dialects import sqlite as sqlite_dialect  # noqa: E402
from sqlalchemy.schema import CreateTable, CreateIndex  # noqa: E402

from src.storage.models import Base  # noqa: E402

_OUTPUT = PROJECT_ROOT / "scripts" / "d1" / "schema.sql"

_HEADER = """\
-- D1 Schema for File Organization System
-- Auto-generated from src/storage/models.py — do not hand-edit.
-- Regenerate: python scripts/d1/generate_schema.py

-- Enable foreign keys
PRAGMA foreign_keys = ON;
"""


def _compile_ddl(ddl, dialect) -> str:
    """Compile a DDL element and normalise indentation to 2 spaces."""
    raw = str(ddl.compile(dialect=dialect))
    # SQLAlchemy uses tabs; normalise to 2-space indent
    return raw.replace("\t", "  ")


def generate(dialect=None) -> str:
    if dialect is None:
        dialect = sqlite_dialect.dialect()

    sections = [_HEADER]

    for table in Base.metadata.sorted_tables:
        create_table = _compile_ddl(CreateTable(table, if_not_exists=True), dialect).rstrip()
        sections.append(f"-- {table.name}\n{create_table};")

        for idx in sorted(table.indexes, key=lambda i: i.name or ""):
            create_idx = _compile_ddl(CreateIndex(idx, if_not_exists=True), dialect).rstrip()
            sections.append(create_idx + ";")

        sections.append("")

    return "\n".join(sections) + "\n"


def main() -> None:
    schema_sql = generate()
    _OUTPUT.write_text(schema_sql, encoding="utf-8")
    print(f"Written {_OUTPUT}")


if __name__ == "__main__":
    main()
