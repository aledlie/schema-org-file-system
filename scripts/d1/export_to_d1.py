#!/usr/bin/env python3
"""
Export existing SQLite database to D1-compatible SQL dump.

Usage:
  python scripts/d1/export_to_d1.py [--db-path results/file_organization.db] [--output results/d1_dump.sql]
"""

import sqlite3
import json
import argparse
from datetime import datetime
from pathlib import Path


def export_to_sql(db_path: str, output_path: str) -> None:
    """Export SQLite database to SQL dump compatible with D1."""
    if not Path(db_path).exists():
        print(f"Error: Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all tables
    cursor.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name NOT LIKE 'sqlite_%'
    ORDER BY name
  """)
    tables = [row[0] for row in cursor.fetchall()]

    with open(output_path, "w") as f:
        f.write("-- D1 Data Export\n")
        f.write(f"-- Exported: {datetime.now().isoformat()}\n")
        f.write("-- Source: SQLite Database\n\n")

        for table in tables:
            f.write(f"\n-- Table: {table}\n")

            # Get column info
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]

            # Get data
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()

            if rows:
                for row in rows:
                    values = []
                    for col_name, val in zip(columns, row):
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, str):
                            # Escape single quotes
                            escaped = val.replace("'", "''")
                            values.append(f"'{escaped}'")
                        elif isinstance(val, bool):
                            values.append("1" if val else "0")
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        else:
                            # JSON or other types
                            escaped = json.dumps(val).replace("'", "''")
                            values.append(f"'{escaped}'")

                    col_list = ", ".join(columns)
                    val_list = ", ".join(values)
                    f.write(f"INSERT INTO {table} ({col_list}) VALUES ({val_list});\n")

            f.write("\n")

    conn.close()

    # Get file size stats
    input_size = Path(db_path).stat().st_size / (1024 * 1024)
    output_size = Path(output_path).stat().st_size / (1024 * 1024)

    print("✓ Export complete")
    print(f"  Source DB: {db_path} ({input_size:.2f} MB)")
    print(f"  SQL dump: {output_path} ({output_size:.2f} MB)")
    print(f"  Tables exported: {len(tables)}")
    print("\nNext steps:")
    print("  1. Upload schema: wrangler d1 execute file-organization-db < scripts/d1/schema.sql")
    print(f"  2. Load data: wrangler d1 execute file-organization-db < {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export SQLite to D1-compatible SQL")
    parser.add_argument("--db-path", default="results/file_organization.db")
    parser.add_argument("--output", default="results/d1_dump.sql")

    args = parser.parse_args()
    export_to_sql(args.db_path, args.output)
