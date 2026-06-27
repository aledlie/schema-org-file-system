#!/usr/bin/env python3
"""
Timeline API - Provides session data for timeline visualization.

Fetches organization session data from SQLite database and serves it
as JSON for the timeline interface.
"""

import json
import sqlite3
from storage._time import utcnow
from typing import List, Dict, Any, Optional
from pathlib import Path
from collections import defaultdict

try:
    from .constants import COST_DECIMAL_PLACES
except ImportError:
    from constants import COST_DECIMAL_PLACES


class TimelineAPI:
    """API for fetching and formatting timeline data."""

    def __init__(self, db_path: str = "results/file_organization.db"):
        """
        Initialize the Timeline API.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """
        Fetch all organization sessions with aggregated statistics.

        Returns:
            List of session dictionaries with enriched data
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Fetch sessions with category distributions
        sessions = []

        try:
            # Get all sessions
            cursor.execute("""
                SELECT
                    id,
                    started_at,
                    completed_at,
                    dry_run,
                    total_files,
                    organized_count,
                    skipped_count,
                    error_count,
                    total_cost,
                    total_processing_time_sec as processing_time,
                    source_directories,
                    base_path
                FROM organization_sessions
                ORDER BY started_at DESC
            """)

            session_rows = cursor.fetchall()

            for row in session_rows:
                session_data = dict(row)

                # Parse JSON fields
                if session_data['source_directories']:
                    try:
                        session_data['source_directories'] = json.loads(
                            session_data['source_directories']
                        )
                    except json.JSONDecodeError:
                        session_data['source_directories'] = []

                # Get category distribution for this session
                session_data['categories'] = self._get_category_distribution(
                    cursor, session_data['id']
                )

                # Calculate derived metrics
                session_data['success_rate'] = self._calculate_success_rate(session_data)
                session_data['files_per_second'] = self._calculate_files_per_second(
                    session_data
                )
                session_data['cost_per_file'] = self._calculate_cost_per_file(session_data)

                # Get top schema types
                session_data['schema_types'] = self._get_schema_type_distribution(
                    cursor, session_data['id']
                )

                sessions.append(session_data)

        finally:
            conn.close()

        return sessions

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single session by ID.

        Args:
            session_id: Session ID to fetch

        Returns:
            Session dictionary or None if not found
        """
        sessions = self.get_all_sessions()
        for session in sessions:
            if session['id'] == session_id:
                return session
        return None

    def get_session_comparison(
        self, session_id_1: str, session_id_2: str
    ) -> Dict[str, Any]:
        """
        Compare two sessions and calculate differences.

        Args:
            session_id_1: First session ID
            session_id_2: Second session ID

        Returns:
            Comparison dictionary with deltas
        """
        session1 = self.get_session_by_id(session_id_1)
        session2 = self.get_session_by_id(session_id_2)

        if not session1 or not session2:
            raise ValueError("One or both sessions not found")

        comparison = {
            'session1': session1,
            'session2': session2,
            'deltas': {
                'total_files': session2['total_files'] - session1['total_files'],
                'organized_count': session2['organized_count'] - session1['organized_count'],
                'error_count': session2['error_count'] - session1['error_count'],
                'total_cost': round(
                    session2['total_cost'] - session1['total_cost'], 2
                ),
                'success_rate': round(
                    session2['success_rate'] - session1['success_rate'], 2
                ),
            }
        }

        return comparison

    def get_latest_sessions(self, limit: int = 2) -> List[Dict[str, Any]]:
        """
        Get the most recent sessions.

        Args:
            limit: Number of sessions to return

        Returns:
            List of recent sessions
        """
        sessions = self.get_all_sessions()
        return sessions[:limit]

    def get_aggregate_stats(self) -> Dict[str, Any]:
        """
        Calculate aggregate statistics across all sessions.

        Returns:
            Dictionary of aggregate metrics
        """
        sessions = self.get_all_sessions()

        if not sessions:
            return {
                'total_sessions': 0,
                'total_files_processed': 0,
                'total_organized': 0,
                'total_errors': 0,
                'total_cost': 0.0,
                'average_success_rate': 0.0,
                'total_processing_time': 0.0,
            }

        total_files = sum(s['total_files'] for s in sessions)
        total_organized = sum(s['organized_count'] for s in sessions)
        total_errors = sum(s['error_count'] for s in sessions)
        total_cost = sum(s['total_cost'] for s in sessions)
        avg_success_rate = sum(s['success_rate'] for s in sessions) / len(sessions)
        total_processing_time = sum(s['processing_time'] or 0 for s in sessions)

        # Category breakdown across all sessions
        all_categories = defaultdict(int)
        for session in sessions:
            for cat, count in session['categories'].items():
                all_categories[cat] += count

        return {
            'total_sessions': len(sessions),
            'total_files_processed': total_files,
            'total_organized': total_organized,
            'total_errors': total_errors,
            'total_cost': round(total_cost, 2),
            'average_success_rate': round(avg_success_rate, 2),
            'total_processing_time': round(total_processing_time, 2),
            'category_breakdown': dict(all_categories),
            'dry_run_count': sum(1 for s in sessions if s['dry_run']),
            'live_run_count': sum(1 for s in sessions if not s['dry_run']),
        }

    def _get_category_distribution(
        self, cursor: sqlite3.Cursor, session_id: str
    ) -> Dict[str, int]:
        """
        Get category distribution for a session.

        Args:
            cursor: Database cursor
            session_id: Session ID

        Returns:
            Dictionary mapping category names to file counts
        """
        cursor.execute("""
            SELECT c.name, COUNT(DISTINCT f.id) as count
            FROM files f
            JOIN file_categories fc ON f.id = fc.file_id
            JOIN categories c ON fc.category_id = c.id
            WHERE f.session_id = ?
            GROUP BY c.name
            ORDER BY count DESC
        """, (session_id,))

        rows = cursor.fetchall()
        distribution = {row['name']: row['count'] for row in rows}

        return distribution

    def _get_schema_type_distribution(
        self, cursor: sqlite3.Cursor, session_id: str
    ) -> Dict[str, int]:
        """
        Get schema type distribution for a session.

        Args:
            cursor: Database cursor
            session_id: Session ID

        Returns:
            Dictionary mapping schema types to counts
        """
        cursor.execute("""
            SELECT schema_type, COUNT(*) as count
            FROM files
            WHERE session_id = ? AND schema_type IS NOT NULL
            GROUP BY schema_type
            ORDER BY count DESC
            LIMIT 10
        """, (session_id,))

        rows = cursor.fetchall()
        distribution = {row['schema_type']: row['count'] for row in rows}

        return distribution

    @staticmethod
    def _calculate_success_rate(session: Dict[str, Any]) -> float:
        """Calculate success rate percentage."""
        if session['total_files'] == 0:
            return 0.0
        return round(
            (session['organized_count'] / session['total_files']) * 100, 2
        )

    @staticmethod
    def _calculate_files_per_second(session: Dict[str, Any]) -> float:
        """Calculate processing throughput."""
        if not session.get('processing_time') or session['processing_time'] == 0:
            return 0.0
        return round(session['total_files'] / session['processing_time'], 2)

    @staticmethod
    def _calculate_cost_per_file(session: Dict[str, Any]) -> float:
        """Calculate cost per file."""
        if session['total_files'] == 0:
            return 0.0
        return round(session['total_cost'] / session['total_files'], COST_DECIMAL_PLACES)

    def export_to_json(self, output_path: str = "_site/timeline_data.json") -> str:
        """
        Export all session data to JSON file for static serving.

        Args:
            output_path: Path to write JSON file
        """
        data = {
            'sessions': self.get_all_sessions(),
            'aggregate_stats': self.get_aggregate_stats(),
            'generated_at': utcnow().isoformat(),
        }

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        print(f"Timeline data exported to {output_path}")
        return output_path


def main() -> None:
    """CLI entry point for generating timeline data."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate timeline data from database")
    parser.add_argument(
        '--db-path',
        default='results/file_organization.db',
        help='Path to SQLite database'
    )
    parser.add_argument(
        '--output',
        default='_site/timeline_data.json',
        help='Output JSON file path'
    )
    parser.add_argument(
        '--session-id',
        help='Get specific session by ID'
    )
    parser.add_argument(
        '--compare',
        nargs=2,
        metavar=('SESSION1', 'SESSION2'),
        help='Compare two sessions'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show aggregate statistics'
    )

    args = parser.parse_args()

    try:
        api = TimelineAPI(args.db_path)

        if args.session_id:
            # Get specific session
            session = api.get_session_by_id(args.session_id)
            if session:
                print(json.dumps(session, indent=2, default=str))
            else:
                print(f"Session {args.session_id} not found")

        elif args.compare:
            # Compare two sessions
            comparison = api.get_session_comparison(args.compare[0], args.compare[1])
            print(json.dumps(comparison, indent=2, default=str))

        elif args.stats:
            # Show aggregate stats
            stats = api.get_aggregate_stats()
            print(json.dumps(stats, indent=2, default=str))

        else:
            # Export all data to JSON
            output_path = api.export_to_json(args.output)
            print(f"✅ Timeline data exported successfully to {output_path}")

            # Print summary
            stats = api.get_aggregate_stats()
            print("\n📊 Summary:")
            print(f"   Total Sessions: {stats['total_sessions']}")
            print(f"   Total Files: {stats['total_files_processed']:,}")
            print(f"   Success Rate: {stats['average_success_rate']}%")
            print(f"   Total Cost: ${stats['total_cost']:.2f}")

    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("Make sure you've run the file organizer at least once.")
        exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == '__main__':
    main()
