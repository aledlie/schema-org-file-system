#!/usr/bin/env python3
"""
Timeline data generation for the run-history visualization.

Canonical implementation of the ``_site/timeline_data.json`` document
consumed by ``_site/run_timeline.html``: sessions (with per-session
category/schema-type/extension breakdowns and consecutive-session deltas)
plus cumulative stats. Reached via ``organize-files timeline``,
``organize-files update-site``, and the ``scripts/generate_timeline_data.py``
launcher — keep those the only writers of the output file.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.cli_inputs import TimelineInputs

from shared.db_utils import db_connection, DEFAULT_DB_PATH
from src.storage._time import utcnow

DB_PATH = DEFAULT_DB_PATH
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "_site" / "timeline_data.json"


def get_sessions(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Get all organization sessions with their stats."""
    with db_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                started_at,
                completed_at,
                dry_run,
                source_directories,
                base_path,
                file_limit,
                total_files,
                organized_count,
                skipped_count,
                error_count,
                total_cost,
                total_processing_time_sec
            FROM organization_sessions
            WHERE total_files > 0
            ORDER BY started_at ASC
        """)

        sessions = []
        for row in cursor.fetchall():
            session = dict(row)
            session['id_short'] = session['id'][:8]

            # Parse JSON fields
            if session['source_directories']:
                try:
                    session['source_directories'] = json.loads(session['source_directories'])
                except (json.JSONDecodeError, TypeError):
                    session['source_directories'] = []
            else:
                session['source_directories'] = []

            # Calculate success rate
            if session['total_files'] > 0:
                session['success_rate'] = round(
                    (session['organized_count'] / session['total_files']) * 100, 1
                )
            else:
                session['success_rate'] = 0

            sessions.append(session)

    return sessions


def get_session_categories(
    session_id: str, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Get category breakdown for a specific session."""
    with db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.name,
                c.color,
                c.icon,
                COUNT(fc.file_id) as count,
                AVG(fc.confidence) as avg_confidence
            FROM categories c
            JOIN file_categories fc ON c.id = fc.category_id
            JOIN files f ON fc.file_id = f.id
            WHERE f.session_id = ?
            GROUP BY c.id
            ORDER BY count DESC
            LIMIT 10
        """, (session_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_session_schema_types(
    session_id: str, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Get schema type distribution for a specific session."""
    with db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                schema_type,
                COUNT(*) as count
            FROM files
            WHERE session_id = ? AND schema_type IS NOT NULL
            GROUP BY schema_type
            ORDER BY count DESC
        """, (session_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_session_extensions(
    session_id: str, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Get file extension distribution for a specific session."""
    with db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                LOWER(file_extension) as extension,
                COUNT(*) as count
            FROM files
            WHERE session_id = ? AND file_extension IS NOT NULL
            GROUP BY LOWER(file_extension)
            ORDER BY count DESC
            LIMIT 10
        """, (session_id,))
        return [dict(row) for row in cursor.fetchall()]


def calculate_session_changes(current: dict, previous: dict | None) -> dict[str, Any]:
    """Calculate what changed between two sessions."""
    if previous is None:
        return {
            'is_first': True,
            'files_delta': current['total_files'],
            'organized_delta': current['organized_count'],
            'new_categories': [],
            'category_changes': []
        }

    return {
        'is_first': False,
        'files_delta': current['total_files'] - previous['total_files'],
        'organized_delta': current['organized_count'] - previous['organized_count'],
        'success_rate_delta': round(current['success_rate'] - previous['success_rate'], 1),
        'cost_delta': round(current['total_cost'] - previous['total_cost'], 4),
        'time_delta': round(
            (current['total_processing_time_sec'] or 0) -
            (previous['total_processing_time_sec'] or 0), 2
        )
    }


def get_cumulative_stats(db_path: Path | str | None = None) -> dict[str, Any]:
    """Get cumulative statistics across all sessions."""
    with db_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(DISTINCT session_id) as total_sessions,
                COUNT(*) as total_files,
                SUM(CASE WHEN status = 'organized' THEN 1 ELSE 0 END) as total_organized,
                AVG(processing_time_sec) as avg_processing_time
            FROM files
            WHERE session_id IS NOT NULL
        """)

        row = cursor.fetchone()
        stats = dict(row) if row else {
            'total_sessions': 0, 'total_files': 0,
            'total_organized': 0, 'avg_processing_time': None,
        }

        # Get category totals
        cursor.execute("""
            SELECT
                c.name,
                COUNT(fc.file_id) as count
            FROM categories c
            LEFT JOIN file_categories fc ON c.id = fc.category_id
            GROUP BY c.id
            ORDER BY count DESC
            LIMIT 5
        """)

        stats['top_categories'] = [dict(row) for row in cursor.fetchall()]

    return stats


def generate_timeline_data(db_path: Path | str | None = None) -> dict[str, Any]:
    """Generate complete timeline data structure."""
    sessions = get_sessions(db_path)

    # Enrich each session with detailed data
    enriched_sessions = []
    previous_session = None

    for session in sessions:
        session['categories'] = get_session_categories(session['id'], db_path)
        session['schema_types'] = get_session_schema_types(session['id'], db_path)
        session['extensions'] = get_session_extensions(session['id'], db_path)
        session['changes'] = calculate_session_changes(session, previous_session)

        enriched_sessions.append(session)
        previous_session = session

    return {
        'generated_at': utcnow().isoformat(),
        'cumulative': get_cumulative_stats(db_path),
        'sessions': enriched_sessions,
        'session_count': len(enriched_sessions)
    }


def run(args: "TimelineInputs") -> None:
    """Typed entry point: generate and save timeline data from validated CLI inputs.

    ``args`` is the frozen ``src.cli_inputs.TimelineInputs`` dataclass built
    from the options ``src.cli.add_timeline_arguments`` defines (the single
    source for this command, shared with the unified CLI). ``db_path=None``
    resolves to the shared DEFAULT_DB_PATH.
    """
    db_path = args.db_path or DB_PATH
    print(f"Generating timeline data from {db_path}...")

    data = generate_timeline_data(db_path)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Timeline data saved to {OUTPUT_PATH}")
    print(f"  - {data['session_count']} sessions")
    print(f"  - {data['cumulative']['total_files']} total files")


def main() -> None:
    """Standalone entry point (argument definitions shared with organize-files).

    Reached via the ``scripts/generate_timeline_data.py`` launcher, which puts
    the project root and ``scripts/`` on ``sys.path``.
    """
    import argparse

    from src.cli import add_timeline_arguments
    from src.cli_inputs import TimelineInputs

    parser = argparse.ArgumentParser(description='Generate timeline visualization data')
    add_timeline_arguments(parser)
    run(TimelineInputs.from_namespace(parser.parse_args()))


if __name__ == "__main__":
    main()
