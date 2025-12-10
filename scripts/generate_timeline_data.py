#!/usr/bin/env python3
"""
Generate timeline data JSON for the run history visualization.
Queries the SQLite database and creates a JSON file for the frontend.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "results" / "file_organization.db"
OUTPUT_PATH = Path(__file__).parent.parent / "_site" / "timeline_data.json"


def get_db_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_sessions() -> list[dict[str, Any]]:
    """Get all organization sessions with their stats."""
    conn = get_db_connection()
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

    conn.close()
    return sessions


def get_session_categories(session_id: str) -> list[dict[str, Any]]:
    """Get category breakdown for a specific session."""
    conn = get_db_connection()
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

    categories = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return categories


def get_session_schema_types(session_id: str) -> list[dict[str, Any]]:
    """Get schema type distribution for a specific session."""
    conn = get_db_connection()
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

    schema_types = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return schema_types


def get_session_extensions(session_id: str) -> list[dict[str, Any]]:
    """Get file extension distribution for a specific session."""
    conn = get_db_connection()
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

    extensions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return extensions


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


def get_cumulative_stats() -> dict[str, Any]:
    """Get cumulative statistics across all sessions."""
    conn = get_db_connection()
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

    stats = dict(cursor.fetchone())

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

    conn.close()
    return stats


def generate_timeline_data() -> dict[str, Any]:
    """Generate complete timeline data structure."""
    sessions = get_sessions()

    # Enrich each session with detailed data
    enriched_sessions = []
    previous_session = None

    for session in sessions:
        session['categories'] = get_session_categories(session['id'])
        session['schema_types'] = get_session_schema_types(session['id'])
        session['extensions'] = get_session_extensions(session['id'])
        session['changes'] = calculate_session_changes(session, previous_session)

        enriched_sessions.append(session)
        previous_session = session

    return {
        'generated_at': datetime.now().isoformat(),
        'cumulative': get_cumulative_stats(),
        'sessions': enriched_sessions,
        'session_count': len(enriched_sessions)
    }


def main():
    """Generate and save timeline data."""
    print(f"Generating timeline data from {DB_PATH}...")

    data = generate_timeline_data()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Timeline data saved to {OUTPUT_PATH}")
    print(f"  - {data['session_count']} sessions")
    print(f"  - {data['cumulative']['total_files']} total files")


if __name__ == "__main__":
    main()
