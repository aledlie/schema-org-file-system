#!/usr/bin/env python3
"""
JSON to Database Migration Tool.

Migrates existing JSON result files to the graph-based SQL storage
and key-value store.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session

from .models import (
    File, Category, Company, Person, Location,
    OrganizationSession, CostRecord, SchemaMetadata,
    FileStatus, RelationshipType
)
from .graph_store import GraphStore
from .kv_store import KeyValueStorage


class JSONMigrator:
    """
    Migrates JSON result files to database storage.

    Handles:
    - Organization reports (content_organization_report_*.json)
    - Cost reports (cost_report_*.json, cost_roi_report.json)
    - Model evaluation reports (model_evaluation.json)
    """

    def __init__(
        self,
        db_path: str = 'results/file_organization.db',
        results_dir: str = 'results'
    ):
        """
        Initialize the migrator.

        Args:
            db_path: Path to database
            results_dir: Directory containing JSON files
        """
        self.db_path = db_path
        self.results_dir = Path(results_dir)
        self.graph_store = GraphStore(db_path)
        self.kv_store = KeyValueStorage(db_path)

        # Statistics
        self.stats = defaultdict(int)

    def migrate_all(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Migrate all JSON files in the results directory.

        Args:
            verbose: Print progress messages

        Returns:
            Migration statistics
        """
        if verbose:
            print("=" * 60)
            print("JSON to Database Migration")
            print("=" * 60)

        # Find all JSON files
        json_files = sorted(self.results_dir.glob('*.json'))

        if verbose:
            print(f"\nFound {len(json_files)} JSON files")

        # Categorize files
        organization_reports = []
        cost_reports = []
        other_files = []

        for f in json_files:
            if 'content_organization_report' in f.name:
                organization_reports.append(f)
            elif 'cost' in f.name.lower():
                cost_reports.append(f)
            else:
                other_files.append(f)

        if verbose:
            print(f"  - Organization reports: {len(organization_reports)}")
            print(f"  - Cost reports: {len(cost_reports)}")
            print(f"  - Other files: {len(other_files)}")

        # Migrate organization reports
        if organization_reports:
            if verbose:
                print(f"\n{'Migrating Organization Reports':=^60}")
            for f in organization_reports:
                try:
                    self._migrate_organization_report(f, verbose)
                except Exception as e:
                    print(f"  Error migrating {f.name}: {e}")
                    self.stats['errors'] += 1

        # Migrate cost reports
        if cost_reports:
            if verbose:
                print(f"\n{'Migrating Cost Reports':=^60}")
            for f in cost_reports:
                try:
                    self._migrate_cost_report(f, verbose)
                except Exception as e:
                    print(f"  Error migrating {f.name}: {e}")
                    self.stats['errors'] += 1

        # Store other files in key-value store
        if other_files:
            if verbose:
                print(f"\n{'Storing Other Files':=^60}")
            for f in other_files:
                try:
                    self._store_generic_json(f, verbose)
                except Exception as e:
                    print(f"  Error storing {f.name}: {e}")
                    self.stats['errors'] += 1

        # Print summary
        if verbose:
            self._print_summary()

        return dict(self.stats)

    def _migrate_organization_report(self, file_path: Path, verbose: bool = True):
        """
        Migrate a content organization report.

        Args:
            file_path: Path to JSON file
            verbose: Print progress
        """
        if verbose:
            print(f"\n  Processing: {file_path.name}")

        with open(file_path, 'r') as f:
            data = json.load(f)

        # Extract timestamp from filename
        timestamp_str = file_path.stem.replace('content_organization_report_', '')
        try:
            session_timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
        except ValueError:
            session_timestamp = datetime.utcnow()

        # Create organization session
        session = self.graph_store.get_session()

        try:
            org_session = OrganizationSession(
                id=hashlib.sha256(str(file_path).encode()).hexdigest()[:64],
                started_at=session_timestamp,
                completed_at=session_timestamp,
                dry_run=data.get('dry_run', False),
                total_files=data.get('total_files', 0),
                organized_count=data.get('organized', 0),
                skipped_count=data.get('skipped', 0),
                error_count=data.get('errors', 0)
            )
            session.merge(org_session)
            session.commit()
            self.stats['sessions'] += 1

            # Migrate individual file results in batches
            results = data.get('results', [])
            batch_size = 100
            for i, result in enumerate(results):
                with session.no_autoflush:
                    self._migrate_file_result(result, org_session.id, session)

                # Commit in batches to avoid large transactions
                if (i + 1) % batch_size == 0:
                    session.commit()

            # Final commit for remaining items
            session.commit()

            if verbose:
                print(f"    - Migrated {len(results)} file records")
                print(f"    - Session ID: {org_session.id[:16]}...")

        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def _migrate_file_result(
        self,
        result: Dict[str, Any],
        session_id: str,
        db_session: Session
    ):
        """
        Migrate a single file result.

        Args:
            result: File result dictionary
            session_id: Organization session ID
            db_session: Database session
        """
        source_path = result.get('source', '')
        if not source_path:
            return

        file_id = File.generate_id(source_path)

        # Map status
        status_map = {
            'organized': FileStatus.ORGANIZED,
            'would_organize': FileStatus.ORGANIZED,  # Dry run
            'skipped': FileStatus.SKIPPED,
            'error': FileStatus.ERROR,
            'already_organized': FileStatus.ALREADY_ORGANIZED
        }
        status = status_map.get(result.get('status'), FileStatus.PENDING)

        # Extract schema data
        schema_data = result.get('schema', {})

        # Create or update file
        file = db_session.query(File).filter(File.id == file_id).first()

        if not file:
            file = File(
                id=file_id,
                filename=Path(source_path).name,
                original_path=source_path,
                current_path=result.get('destination'),
                status=status,
                organization_reason=result.get('reason'),
                extracted_text_length=result.get('extracted_text_length', 0),
                schema_type=schema_data.get('@type'),
                schema_data=schema_data,
                session_id=session_id
            )

            # Image metadata
            image_meta = result.get('image_metadata', {})
            if image_meta:
                if image_meta.get('datetime'):
                    try:
                        file.exif_datetime = datetime.fromisoformat(image_meta['datetime'])
                    except (ValueError, TypeError):
                        pass

                coords = image_meta.get('gps_coordinates')
                if coords and len(coords) == 2:
                    file.gps_latitude = coords[0]
                    file.gps_longitude = coords[1]

            db_session.add(file)
            db_session.flush()  # Ensure file ID is committed before relationships
            self.stats['files'] += 1
        else:
            # Update existing
            file.current_path = result.get('destination') or file.current_path
            file.status = status
            db_session.flush()  # Ensure updates are visible

        # Add category relationship
        category = result.get('category')
        subcategory = result.get('subcategory')

        if category and category != 'uncategorized':
            self.graph_store.add_file_to_category(
                file_id, category, subcategory, session=db_session
            )
            self.stats['categories'] += 1

        # Add company relationship
        company_name = result.get('company_name')
        if company_name:
            self.graph_store.add_file_to_company(
                file_id, company_name, session=db_session
            )
            self.stats['companies'] += 1

        # Add people relationships
        people_names = result.get('people_names', [])
        for person_name in people_names:
            if person_name:
                self._add_person_to_file(file_id, person_name, db_session)
                self.stats['people'] += 1

        # Add location if GPS data available
        image_meta = result.get('image_metadata', {})
        location_name = image_meta.get('location_name')
        coords = image_meta.get('gps_coordinates')

        if location_name or coords:
            self._add_location_to_file(
                file_id, location_name, coords, db_session
            )
            self.stats['locations'] += 1

        # Store schema metadata - skip if file doesn't exist yet to avoid FK errors
        # Schema metadata will be stored directly in the File table's schema_data field instead
        # This avoids the complex FK relationship during migration

    def _add_person_to_file(
        self,
        file_id: str,
        person_name: str,
        db_session: Session
    ):
        """Add a person to a file."""
        if not person_name:
            return

        normalized = Person.normalize_name(person_name)
        person = db_session.query(Person)\
            .filter(Person.normalized_name == normalized).first()

        if not person:
            person = Person(
                name=person_name,
                normalized_name=normalized
            )
            db_session.add(person)
            db_session.flush()

        file = db_session.query(File).filter(File.id == file_id).first()
        if file and person and person not in file.people:
            file.people.append(person)
            person.file_count += 1

    def _add_location_to_file(
        self,
        file_id: str,
        location_name: Optional[str],
        coords: Optional[List[float]],
        db_session: Session
    ):
        """Add a location to a file."""
        lat = coords[0] if coords and len(coords) >= 2 else None
        lon = coords[1] if coords and len(coords) >= 2 else None

        # Generate location name
        if location_name:
            name = location_name
        elif lat is not None and lon is not None:
            name = f"({lat:.4f}, {lon:.4f})"
        else:
            name = "Unknown"

        location = self.graph_store.get_or_create_location(
            name=name,
            latitude=lat,
            longitude=lon,
            session=db_session
        )

        if location is None:
            return

        file = db_session.query(File).filter(File.id == file_id).first()
        if file and location not in file.locations:
            file.locations.append(location)
            location.file_count += 1

    def _migrate_cost_report(self, file_path: Path, verbose: bool = True):
        """
        Migrate a cost report.

        Args:
            file_path: Path to JSON file
            verbose: Print progress
        """
        if verbose:
            print(f"\n  Processing: {file_path.name}")

        with open(file_path, 'r') as f:
            data = json.load(f)

        # Store cost summary in key-value store
        metadata = data.get('metadata', {})
        report_id = metadata.get('generated_at', file_path.stem)

        # Store cost summary
        cost_summary = data.get('cost_summary', {})
        if cost_summary:
            self.kv_store.hset(
                f"cost_report:{report_id}",
                'summary',
                cost_summary,
                namespace='stats'
            )

        # Store ROI summary
        roi_summary = data.get('roi_summary', {})
        if roi_summary:
            self.kv_store.hset(
                f"cost_report:{report_id}",
                'roi',
                roi_summary,
                namespace='stats'
            )

        # Store feature breakdown
        feature_breakdown = cost_summary.get('feature_breakdown', {})
        for feature_name, feature_data in feature_breakdown.items():
            self.kv_store.hset(
                f"feature_stats:{feature_name}",
                report_id,
                feature_data,
                namespace='stats'
            )

        # Store projections
        projections = data.get('projections', {})
        if projections:
            self.kv_store.hset(
                f"cost_report:{report_id}",
                'projections',
                projections,
                namespace='stats'
            )

        # Store recommendations
        recommendations = data.get('recommendations', [])
        if recommendations:
            self.kv_store.hset(
                f"cost_report:{report_id}",
                'recommendations',
                recommendations,
                namespace='stats'
            )

        self.stats['cost_reports'] += 1

        if verbose:
            print(f"    - Stored cost summary and {len(feature_breakdown)} feature stats")

    def _store_generic_json(self, file_path: Path, verbose: bool = True):
        """
        Store a generic JSON file in key-value store.

        Args:
            file_path: Path to JSON file
            verbose: Print progress
        """
        if verbose:
            print(f"\n  Processing: {file_path.name}")

        with open(file_path, 'r') as f:
            data = json.load(f)

        # Store the entire JSON as a single key
        key = f"json_file:{file_path.stem}"
        self.kv_store.set(
            key,
            data,
            namespace='metadata'
        )

        self.stats['other_files'] += 1

        if verbose:
            print(f"    - Stored as key: {key}")

    def _print_summary(self):
        """Print migration summary."""
        print(f"\n{'Migration Summary':=^60}")
        print(f"  Sessions migrated:      {self.stats['sessions']}")
        print(f"  Files migrated:         {self.stats['files']}")
        print(f"  Categories created:     {self.stats['categories']}")
        print(f"  Companies linked:       {self.stats['companies']}")
        print(f"  People linked:          {self.stats['people']}")
        print(f"  Locations linked:       {self.stats['locations']}")
        print(f"  Cost reports stored:    {self.stats['cost_reports']}")
        print(f"  Other files stored:     {self.stats['other_files']}")
        print(f"  Errors:                 {self.stats['errors']}")
        print("=" * 60)

    def verify_migration(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Verify the migration by comparing counts.

        Returns:
            Verification results
        """
        if verbose:
            print(f"\n{'Verifying Migration':=^60}")

        results = {}

        # Count JSON files
        json_files = list(self.results_dir.glob('content_organization_report_*.json'))
        total_json_files = 0
        total_json_records = 0

        for f in json_files:
            with open(f, 'r') as fp:
                data = json.load(fp)
                total_json_files += data.get('total_files', 0)
                total_json_records += len(data.get('results', []))

        # Count database records
        db_stats = self.graph_store.get_statistics()

        results['json_files'] = len(json_files)
        results['json_records'] = total_json_records
        results['db_files'] = db_stats['total_files']
        results['db_categories'] = db_stats['total_categories']
        results['db_companies'] = db_stats['total_companies']

        if verbose:
            print(f"  JSON organization reports: {len(json_files)}")
            print(f"  JSON file records:         {total_json_records}")
            print(f"  Database file records:     {db_stats['total_files']}")
            print(f"  Database categories:       {db_stats['total_categories']}")
            print(f"  Database companies:        {db_stats['total_companies']}")

            # Check match
            if db_stats['total_files'] >= total_json_records * 0.9:
                print(f"\n  ✓ Migration appears successful")
            else:
                print(f"\n  ⚠ Some records may not have migrated")

        return results


def run_migration(db_path: str = 'results/file_organization.db', dry_run: bool = False) -> Dict[str, Any]:
    """
    Run ID generation migration to add canonical_id to all entities.

    This function:
    1. Adds canonical_id columns if they don't exist
    2. Backfills canonical_id for existing records using deterministic UUID v5
    3. Creates the merge_events table if needed

    Args:
        db_path: Path to SQLite database
        dry_run: If True, show what would be done without making changes

    Returns:
        Migration statistics
    """
    import sqlite3
    import uuid
    from pathlib import Path

    # Namespace UUIDs for deterministic ID generation (must match models.py)
    NAMESPACES = {
        'file': uuid.UUID('f4e8a9c0-1234-5678-9abc-def012345678'),
        'category': uuid.UUID('c4e8a9c0-2345-6789-abcd-ef0123456789'),
        'company': uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),
        'person': uuid.UUID('d1e2a3b4-5678-9abc-def0-123456789012'),
        'location': uuid.UUID('e2e3a4b5-6789-abcd-ef01-234567890123'),
    }

    def generate_canonical_id(namespace: str, name: str) -> str:
        """Generate deterministic UUID v5 from name."""
        ns_uuid = NAMESPACES.get(namespace)
        if not ns_uuid:
            raise ValueError(f"Unknown namespace: {namespace}")
        return str(uuid.uuid5(ns_uuid, name.lower().strip()))

    def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        cursor = conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        return column in columns

    def table_exists(conn: sqlite3.Connection, table: str) -> bool:
        """Check if a table exists."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found at {db_path}")
        return {'error': 'Database not found'}

    stats = defaultdict(int)
    conn = sqlite3.connect(str(db_path))

    try:
        # Phase 1: Schema Migration
        print("Phase 1: Schema Migration")
        print("-" * 40)

        tables_to_migrate = [
            ('files', 'VARCHAR(100)'),
            ('categories', 'VARCHAR(36)'),
            ('companies', 'VARCHAR(36)'),
            ('people', 'VARCHAR(36)'),
            ('locations', 'VARCHAR(36)'),
        ]

        for table, col_type in tables_to_migrate:
            if not table_exists(conn, table):
                print(f"  Table {table} does not exist, skipping")
                continue

            if not column_exists(conn, table, 'canonical_id'):
                if dry_run:
                    print(f"  [DRY RUN] Would add canonical_id to {table}")
                else:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN canonical_id {col_type}")
                    print(f"  Added canonical_id to {table}")
                stats['columns_added'] += 1
            else:
                print(f"  canonical_id already exists in {table}")

            # Add source_ids column if not exists
            if not column_exists(conn, table, 'source_ids'):
                if dry_run:
                    print(f"  [DRY RUN] Would add source_ids to {table}")
                else:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN source_ids JSON DEFAULT '[]'")
                    print(f"  Added source_ids to {table}")

            # Add merged_into_id for entity tables (not files)
            if table != 'files' and not column_exists(conn, table, 'merged_into_id'):
                if dry_run:
                    print(f"  [DRY RUN] Would add merged_into_id to {table}")
                else:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN merged_into_id INTEGER REFERENCES {table}(id)")
                    print(f"  Added merged_into_id to {table}")

        # Create merge_events table if not exists
        if not table_exists(conn, 'merge_events'):
            if dry_run:
                print("  [DRY RUN] Would create merge_events table")
            else:
                conn.execute("""
                    CREATE TABLE merge_events (
                        id VARCHAR(36) PRIMARY KEY,
                        target_entity_type VARCHAR(20) NOT NULL,
                        target_entity_id INTEGER NOT NULL,
                        target_canonical_id VARCHAR(36),
                        source_entity_ids JSON NOT NULL,
                        source_canonical_ids JSON,
                        merge_reason TEXT,
                        confidence FLOAT DEFAULT 1.0,
                        performed_by VARCHAR(100),
                        performed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        jsonld JSON,
                        is_rolled_back BOOLEAN DEFAULT FALSE,
                        rolled_back_at DATETIME,
                        rolled_back_by VARCHAR(100)
                    )
                """)
                print("  Created merge_events table")

        if not dry_run:
            conn.commit()

        # Phase 2: Data Backfill
        print("\nPhase 2: Data Backfill")
        print("-" * 40)

        # Backfill files (use urn:sha256:{id} format)
        if table_exists(conn, 'files'):
            cursor = conn.execute("SELECT id, original_path FROM files WHERE canonical_id IS NULL")
            rows = cursor.fetchall()
            if rows:
                print(f"  Backfilling {len(rows)} files...")
                for file_id, _ in rows:
                    canonical_id = f"urn:sha256:{file_id}"
                    if not dry_run:
                        conn.execute("UPDATE files SET canonical_id = ? WHERE id = ?", (canonical_id, file_id))
                    stats['files_backfilled'] += 1
                if not dry_run:
                    conn.commit()
            else:
                print("  No files need backfilling")

        # Backfill categories (use full_path for deterministic ID)
        if table_exists(conn, 'categories'):
            cursor = conn.execute("SELECT id, full_path, name FROM categories WHERE canonical_id IS NULL")
            rows = cursor.fetchall()
            if rows:
                print(f"  Backfilling {len(rows)} categories...")
                for cat_id, full_path, name in rows:
                    canonical_id = generate_canonical_id('category', full_path or name)
                    if not dry_run:
                        conn.execute("UPDATE categories SET canonical_id = ? WHERE id = ?", (canonical_id, cat_id))
                    stats['categories_backfilled'] += 1
                if not dry_run:
                    conn.commit()
            else:
                print("  No categories need backfilling")

        # Backfill companies
        if table_exists(conn, 'companies'):
            cursor = conn.execute("SELECT id, name FROM companies WHERE canonical_id IS NULL")
            rows = cursor.fetchall()
            if rows:
                print(f"  Backfilling {len(rows)} companies...")
                for comp_id, name in rows:
                    canonical_id = generate_canonical_id('company', name)
                    if not dry_run:
                        conn.execute("UPDATE companies SET canonical_id = ? WHERE id = ?", (canonical_id, comp_id))
                    stats['companies_backfilled'] += 1
                if not dry_run:
                    conn.commit()
            else:
                print("  No companies need backfilling")

        # Backfill people
        if table_exists(conn, 'people'):
            cursor = conn.execute("SELECT id, name FROM people WHERE canonical_id IS NULL")
            rows = cursor.fetchall()
            if rows:
                print(f"  Backfilling {len(rows)} people...")
                for person_id, name in rows:
                    canonical_id = generate_canonical_id('person', name)
                    if not dry_run:
                        conn.execute("UPDATE people SET canonical_id = ? WHERE id = ?", (canonical_id, person_id))
                    stats['people_backfilled'] += 1
                if not dry_run:
                    conn.commit()
            else:
                print("  No people need backfilling")

        # Backfill locations
        if table_exists(conn, 'locations'):
            cursor = conn.execute("SELECT id, name FROM locations WHERE canonical_id IS NULL")
            rows = cursor.fetchall()
            if rows:
                print(f"  Backfilling {len(rows)} locations...")
                for loc_id, name in rows:
                    canonical_id = generate_canonical_id('location', name)
                    if not dry_run:
                        conn.execute("UPDATE locations SET canonical_id = ? WHERE id = ?", (canonical_id, loc_id))
                    stats['locations_backfilled'] += 1
                if not dry_run:
                    conn.commit()
            else:
                print("  No locations need backfilling")

        # Phase 3: Create Indexes
        print("\nPhase 3: Create Indexes")
        print("-" * 40)

        indexes = [
            ("ix_files_canonical_id", "files", "canonical_id"),
            ("ix_categories_canonical_id", "categories", "canonical_id"),
            ("ix_companies_canonical_id", "companies", "canonical_id"),
            ("ix_people_canonical_id", "people", "canonical_id"),
            ("ix_locations_canonical_id", "locations", "canonical_id"),
        ]

        for index_name, table, column in indexes:
            if not table_exists(conn, table):
                continue
            # Check if index exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,)
            )
            if cursor.fetchone():
                print(f"  Index {index_name} already exists")
                continue

            if dry_run:
                print(f"  [DRY RUN] Would create index {index_name}")
            else:
                try:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})")
                    print(f"  Created index {index_name}")
                    stats['indexes_created'] += 1
                except sqlite3.OperationalError as e:
                    print(f"  Warning creating index {index_name}: {e}")

        if not dry_run:
            conn.commit()

        # Summary
        print("\n" + "=" * 40)
        print("Migration Summary")
        print("=" * 40)
        total_backfilled = sum(v for k, v in stats.items() if 'backfilled' in k)
        print(f"  Records backfilled: {total_backfilled}")
        print(f"  Indexes created: {stats.get('indexes_created', 0)}")
        if dry_run:
            print("\n  [DRY RUN] No changes were made")

    finally:
        conn.close()

    return dict(stats)


def main():
    """Run the migration."""
    import argparse

    parser = argparse.ArgumentParser(description='Migrate JSON results to database')
    parser.add_argument(
        '--db-path',
        default='results/file_organization.db',
        help='Database path'
    )
    parser.add_argument(
        '--results-dir',
        default='results',
        help='Results directory'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify migration after completion'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    args = parser.parse_args()

    migrator = JSONMigrator(args.db_path, args.results_dir)

    # Run migration
    stats = migrator.migrate_all(verbose=not args.quiet)

    # Verify if requested
    if args.verify:
        migrator.verify_migration(verbose=not args.quiet)

    print(f"\nDatabase saved to: {args.db_path}")


if __name__ == '__main__':
    main()
