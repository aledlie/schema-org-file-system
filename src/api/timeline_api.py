#!/usr/bin/env python3
"""
Timeline data generation for the run-history visualization.

``TimelineAPI`` is the canonical builder of the ``_site/timeline_data.json``
document consumed by ``_site/run_timeline.html``: sessions (each enriched with
category / schema-type / extension breakdowns and consecutive-session deltas)
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


class TimelineAPI:
    """Builds the timeline visualization document from the SQLite database.

    A single instance is bound to one database path (``None`` resolves to the
    shared ``DEFAULT_DB_PATH``). ``generate_document`` assembles the full
    ``_site/timeline_data.json`` payload; ``export_to_json`` also writes it.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = db_path
        # Fail early with a clear message instead of an opaque "no such table"
        # from the first query (and avoid sqlite3.connect creating an empty
        # phantom DB file at the missing path).
        effective_path = Path(db_path) if db_path else Path(DB_PATH)
        if not effective_path.exists():
            raise FileNotFoundError(
                f"Timeline database not found: {effective_path}. "
                "Run the file organizer at least once to create it."
            )

    def get_sessions(self) -> list[dict[str, Any]]:
        """Get all non-empty organization sessions with their stats, oldest first."""
        with db_connection(self.db_path) as conn:
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
                        session['source_directories'] = json.loads(
                            session['source_directories']
                        )
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

    def get_session_categories(self, session_id: str) -> list[dict[str, Any]]:
        """Get category breakdown for a specific session."""
        with db_connection(self.db_path) as conn:
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

    def get_session_schema_types(self, session_id: str) -> list[dict[str, Any]]:
        """Get schema type distribution for a specific session."""
        with db_connection(self.db_path) as conn:
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

    def get_session_extensions(self, session_id: str) -> list[dict[str, Any]]:
        """Get file extension distribution for a specific session."""
        with db_connection(self.db_path) as conn:
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

    @staticmethod
    def calculate_session_changes(
        current: dict, previous: dict | None
    ) -> dict[str, Any]:
        """Calculate what changed between two consecutive sessions."""
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
            'success_rate_delta': round(
                current['success_rate'] - previous['success_rate'], 1
            ),
            'cost_delta': round(current['total_cost'] - previous['total_cost'], 4),
            'time_delta': round(
                (current['total_processing_time_sec'] or 0) -
                (previous['total_processing_time_sec'] or 0), 2
            )
        }

    def get_cumulative_stats(self) -> dict[str, Any]:
        """Get cumulative statistics across all sessions."""
        with db_connection(self.db_path) as conn:
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

    def generate_document(self) -> dict[str, Any]:
        """Assemble the complete timeline document.

        Each session is enriched with its category / schema-type / extension
        breakdowns and the deltas versus the preceding session.
        """
        sessions = self.get_sessions()

        enriched_sessions = []
        previous_session = None

        for session in sessions:
            session['categories'] = self.get_session_categories(session['id'])
            session['schema_types'] = self.get_session_schema_types(session['id'])
            session['extensions'] = self.get_session_extensions(session['id'])
            session['changes'] = self.calculate_session_changes(session, previous_session)

            enriched_sessions.append(session)
            previous_session = session

        return {
            'generated_at': utcnow().isoformat(),
            'cumulative': self.get_cumulative_stats(),
            'sessions': enriched_sessions,
            'session_count': len(enriched_sessions)
        }

    def export_to_json(
        self, output_path: Path | str = OUTPUT_PATH
    ) -> dict[str, Any]:
        """Generate the timeline document and write it to ``output_path``.

        Returns the generated document so callers can report counts without
        re-reading the file.
        """
        data = self.generate_document()

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        return data


def generate_timeline_data(db_path: Path | str | None = None) -> dict[str, Any]:
    """Module-level convenience: build the full timeline document for ``db_path``."""
    return TimelineAPI(db_path).generate_document()


def run(args: "TimelineInputs") -> None:
    """Typed entry point: generate and save timeline data from validated CLI inputs.

    ``args`` is the frozen ``src.cli_inputs.TimelineInputs`` dataclass built
    from the options ``src.cli.add_timeline_arguments`` defines (the single
    source for this command, shared with the unified CLI). ``db_path=None``
    resolves to the shared DEFAULT_DB_PATH.
    """
    db_path = args.db_path or DB_PATH
    print(f"Generating timeline data from {db_path}...")

    data = TimelineAPI(db_path).export_to_json(OUTPUT_PATH)

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
