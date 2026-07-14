#!/usr/bin/env python3
"""
Unified CLI for Schema.org File Organization System.

Provides a single entry point with subcommands for all file organization tasks.

Usage:
    organize-files content --source ~/Downloads --limit 100 --dry-run
    organize-files name --source ~/Downloads --target ~/Documents
    organize-files type --source ~/Desktop
    organize-files preprocess --output results/training_data
    organize-files evaluate --test-data results/test_set.json
    organize-files migrate-ids
    organize-files health
"""

import argparse
import sys
from pathlib import Path
from typing import Any

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / 'scripts'

# Shared option defaults, single-sourced for the parser definitions below.
DEFAULT_SOURCES = ['~/Desktop', '~/Downloads']
DEFAULT_TARGET = '~/Documents'
DEFAULT_DB_PATH = 'results/file_organization.db'
DEFAULT_COST_REPORT = 'results/cost_report.json'


def cmd_content(args: Any) -> None:
    """Run content-based organization using AI/OCR."""
    # Import here to avoid loading heavy dependencies until needed
    sys.path.insert(0, str(SCRIPTS_DIR))
    from file_organizer_content_based import run as content_run

    content_run(args)


def cmd_name(args: Any) -> None:
    """Run name-based organization (no AI)."""
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(SCRIPTS_DIR))
    from src.organizers.name_organizer import run as name_run

    name_run(args)


def cmd_type(args: Any) -> None:
    """Run type-based organization by file extension."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from file_organizer_by_type import run as type_run

    type_run(args)


def cmd_preprocess(args: Any) -> None:
    """Run ML data preprocessing."""
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(SCRIPTS_DIR))  # shared.constants, used by feature extraction
    from src.ml.data_preprocessor import run as preprocess_run

    preprocess_run(args)


def cmd_evaluate(args: Any) -> None:
    """Run model evaluation."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from evaluate_model import run as evaluate_run

    evaluate_run(args)


def cmd_migrate(args: Any) -> None:
    """Run database migration for ID generation."""
    from storage.migration import run_migration

    db_path = args.db_path or DEFAULT_DB_PATH
    print(f"\n{'='*60}")
    print("Running ID Generation Migration")
    print(f"{'='*60}\n")
    run_migration(db_path)
    print("\nMigration complete. Canonical IDs have been generated for existing records.")


def _prune_missing_edges(graph_store: Any, apply: bool) -> None:
    """Drop file->person edges whose file path no longer exists; print each."""
    label = "APPLIED" if apply else "DRY RUN"
    pruned = graph_store.prune_missing_person_edges(dry_run=not apply)
    print(f"[{label}] Dead-path person edges pruned: {pruned['edges_removed']}")
    for edge in pruned['edges']:
        print(f"    {edge['person']}: {edge['path']}")


def cmd_person_view(args: Any) -> None:
    """Regenerate the derived Person/{Name}/ symlink view from graph edges."""
    from storage.graph_store import GraphStore
    from storage.person_view_generator import PersonViewGenerator

    view_root = Path(args.view_root).expanduser() if args.view_root else None
    graph_store = GraphStore(args.db_path)
    apply = bool(args.apply)

    # Prune before generating so the view is derived from the cleaned graph.
    if args.prune_missing:
        _prune_missing_edges(graph_store, apply)

    generator = PersonViewGenerator(graph_store, view_root=view_root)
    summary = generator.generate(dry_run=not apply, apply=apply)

    label = "APPLIED" if apply else "DRY RUN"
    print(f"\n[{label}] Person view: {summary['people']} people, "
          f"{summary['symlinks_created']} symlinks, "
          f"{summary['removed_stale']} stale removed")
    for err in summary.get('errors', []):
        print(f"  ! {err}")


def cmd_migrate_person(args: Any) -> None:
    """Migrate legacy on-disk Person/ files into Personal/{subcat}/ folders."""
    from storage.person_migration import (
        DEFAULT_DOCUMENTS_ROOT,
        DEFAULT_MANIFEST_PATH,
        DEFAULT_PERSON_ROOT,
        migrate_person_files,
        rollback_person_migration,
    )

    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST_PATH
    db_path = None if args.no_db else args.db_path

    if args.rollback:
        rollback_person_migration(manifest_path, db_path=db_path)
        return

    person_root = Path(args.person_root).expanduser() if args.person_root else DEFAULT_PERSON_ROOT
    documents_root = (
        Path(args.documents_root).expanduser() if args.documents_root else DEFAULT_DOCUMENTS_ROOT
    )
    migrate_person_files(
        person_root=person_root,
        documents_root=documents_root,
        db_path=db_path,
        manifest_path=manifest_path,
        apply=bool(args.apply),
    )


def cmd_index_people(args: Any) -> None:
    """Register migrated files in the graph with person edges (no file moves)."""
    from storage.person_migration import DEFAULT_MANIFEST_PATH, index_person_files

    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST_PATH
    person_root = Path(args.person_root).expanduser() if args.person_root else None
    kwargs = {
        "manifest_path": manifest_path,
        "db_path": args.db_path,
        "apply": bool(args.apply),
    }
    if person_root is not None:
        kwargs["person_root"] = person_root
    index_person_files(**kwargs)

    # Clean-up pass after indexing: drop edges whose file path is gone.
    if args.prune_missing:
        from storage.graph_store import GraphStore

        _prune_missing_edges(GraphStore(args.db_path), bool(args.apply))


def cmd_prune_person(args: Any) -> None:
    """Delete people and their file->person graph edges (no file moves)."""
    import shutil
    from datetime import datetime

    from storage.graph_store import GraphStore

    apply = bool(args.apply)
    label = "APPLIED" if apply else "DRY RUN"

    if apply:
        db_file = Path(args.db_path)
        if db_file.exists():
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            for suffix in ('', '-wal', '-shm'):
                src = Path(str(db_file) + suffix)
                if src.exists():
                    shutil.copy2(src, Path(f"{db_file}.bak-{stamp}{suffix}"))
            print(f"Backed up database to {db_file}.bak-{stamp}")

    store = GraphStore(args.db_path)
    missing = 0
    for target in args.people:
        key: Any = int(target) if target.isdigit() else target
        summary = store.prune_person(key, dry_run=not apply)
        if summary is None:
            print(f"[{label}] {target!r}: no matching person")
            missing += 1
            continue
        print(f"[{label}] {summary['name']} (id={summary['person_id']}): "
              f"{summary['edges_removed']} edge(s) removed, person deleted")
        for path in summary['paths']:
            print(f"    {path}")

    if missing:
        sys.exit(1)


def cmd_health(args: Any) -> None:
    """Run system health check."""
    from health_check import check_system
    check_system(verbose=True)


def cmd_update_site(args: Any) -> None:
    """Update _site dashboard data."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from update_site_data import run as update_run

    update_run(args)


def cmd_timeline(args: Any) -> None:
    """Generate timeline data for visualization."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from generate_timeline_data import run as timeline_run

    timeline_run(args)


# --------------------------------------------------------------------------- #
# Canonical argument definitions for forwarded subcommands.                    #
#                                                                              #
# Each add_*_arguments function is the single source of truth for its          #
# command's options: main() registers it on the organize-files subparser, and  #
# the target script's standalone main() applies the same function to its own   #
# parser. The cmd_* handlers pass the parsed namespace straight to the         #
# target's typed run(args) — no argv re-serialization, so outer/inner parser   #
# drift cannot occur.                                                          #
# --------------------------------------------------------------------------- #


def add_content_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for content-based organization (organize-files content)."""
    parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                        default=DEFAULT_SOURCES,
                        help='Source directories to organize')
    parser.add_argument('--target', '--base-path', dest='base_path',
                        default=DEFAULT_TARGET,
                        help='Target directory for organized files')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate without moving files')
    parser.add_argument('--limit', type=int,
                        help='Limit number of files to process')
    parser.add_argument('--report', help='Path to save JSON report')
    parser.add_argument('--force', action='store_true',
                        help='Force re-organization of all files, even if '
                             'already in correct location')
    parser.add_argument('--no-cost-tracking', action='store_true',
                        help='Disable cost tracking')
    parser.add_argument('--cost-report', nargs='?', const=DEFAULT_COST_REPORT,
                        default=DEFAULT_COST_REPORT,
                        help=f'Path to save cost/ROI report (default: {DEFAULT_COST_REPORT}, '
                             'use --no-cost-tracking to disable)')
    parser.add_argument('--check-deps', action='store_true',
                        help='Run system health check and show feature availability')
    parser.add_argument('--skip-health-check', action='store_true',
                        help='Skip startup health check')
    parser.add_argument('--sentry-dsn',
                        help='Sentry DSN for error tracking (or set SENTRY_DSN env var)')
    parser.add_argument('--no-sentry', action='store_true',
                        help='Disable Sentry error tracking')
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                        help='SQLite database path')
    parser.add_argument('--no-db', action='store_true',
                        help='Disable database persistence')
    parser.add_argument('--run-migration', action='store_true',
                        help='Run database migration to add canonical_id columns '
                             'to existing records')


def add_name_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for name-based organization (organize-files name)."""
    parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                        default=DEFAULT_SOURCES,
                        help='Source directories to organize')
    parser.add_argument('--target', '--base-path', dest='base_path',
                        default=DEFAULT_TARGET,
                        help='Target directory for organized files')
    parser.add_argument('--recursive', action='store_true',
                        help='Process subdirectories recursively')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate without moving files')
    parser.add_argument('--limit', type=int,
                        help='Limit number of files to process')


def add_type_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for type-based organization (organize-files type)."""
    parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                        default=DEFAULT_SOURCES,
                        help='Source directories to organize')
    parser.add_argument('--target', '--base-path', dest='base_path',
                        default=DEFAULT_TARGET,
                        help='Target directory for organized files')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate without moving files')


def add_preprocess_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for ML data preprocessing (organize-files preprocess)."""
    parser.add_argument('--input', '-i', required=True,
                        help='Path to organization report JSON')
    parser.add_argument('--output', '-o', default='./ml_data',
                        help='Output directory for processed data')
    parser.add_argument('--test-ratio', type=float, default=0.2,
                        help='Test set ratio (default: 0.2)')
    parser.add_argument('--min-freq', type=int, default=5,
                        help='Minimum token frequency for vocabulary')
    parser.add_argument('--report-only', action='store_true',
                        help='Only generate report, no export')


def add_evaluate_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for model evaluation (organize-files evaluate)."""
    parser.add_argument('--test-data', '-t', default='results/ml_data/test.json',
                        help='Path to test.json')
    parser.add_argument('--output', '-o', default='results/model_evaluation.json',
                        help='Output path for results JSON')
    parser.add_argument('--classifier', '-c', choices=['baseline', 'content'],
                        default='baseline',
                        help='baseline = filename heuristic; content = production '
                             'CLIP+OCR classifier (requires test files on disk)')
    parser.add_argument('--min-support', type=int, default=None,
                        help='Minimum per-class sample count for its metrics to be '
                             'reported (default: evaluate_model.DEFAULT_MIN_SUPPORT)')


def add_update_site_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for dashboard data refresh (organize-files update-site)."""
    parser.add_argument('--results-dir', '-r', default='results',
                        help='Results directory')
    parser.add_argument('--site-dir', '-s', default='_site',
                        help='Site directory')
    parser.add_argument('--report', help='Specific report file to use')


def add_timeline_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for timeline generation (organize-files timeline)."""
    parser.add_argument('--db-path', default=None,
                        help=f'Path to SQLite database (default: {DEFAULT_DB_PATH})')


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='organize-files',
        description='Schema.org File Organization System - AI-powered file organization',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  organize-files content --source ~/Downloads --dry-run --limit 100
  organize-files name --source ~/Downloads --target ~/Documents
  organize-files type --source ~/Desktop
  organize-files health
  organize-files migrate-ids --db-path results/file_organization.db

For more help on a specific command:
  organize-files <command> --help
"""
    )

    subparsers = parser.add_subparsers(
        title='commands',
        description='Available organization commands',
        dest='command'
    )

    # Content-based organization (main AI organizer)
    content_parser = subparsers.add_parser(
        'content',
        help='Organize files using AI content analysis (CLIP, OCR)',
        description='AI-powered file organization using CLIP vision and OCR text extraction'
    )
    add_content_arguments(content_parser)
    content_parser.set_defaults(func=cmd_content)

    # Name-based organization (no AI)
    name_parser = subparsers.add_parser(
        'name',
        help='Organize files by filename patterns (no AI)',
        description='Simple file organization based on filename patterns and paths'
    )
    add_name_arguments(name_parser)
    name_parser.set_defaults(func=cmd_name)

    # Type-based organization (by extension)
    type_parser = subparsers.add_parser(
        'type',
        help='Organize files by file type/extension',
        description='Simple file organization based on file extensions'
    )
    add_type_arguments(type_parser)
    type_parser.set_defaults(func=cmd_type)

    # ML preprocessing
    preprocess_parser = subparsers.add_parser(
        'preprocess',
        help='Prepare training data for ML models',
        description='Data preprocessing pipeline for ML model training'
    )
    add_preprocess_arguments(preprocess_parser)
    preprocess_parser.set_defaults(func=cmd_preprocess)

    # Model evaluation
    evaluate_parser = subparsers.add_parser(
        'evaluate',
        help='Evaluate model performance',
        description='Run evaluation metrics on test dataset'
    )
    add_evaluate_arguments(evaluate_parser)
    evaluate_parser.set_defaults(func=cmd_evaluate)

    # Database migration
    migrate_parser = subparsers.add_parser(
        'migrate-ids',
        help='Run database migration for canonical IDs',
        description='Add canonical_id columns and generate UUIDs for existing records'
    )
    migrate_parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                                help='Path to SQLite database')
    migrate_parser.set_defaults(func=cmd_migrate)

    # Person symlink view (derived from graph edges)
    person_view_parser = subparsers.add_parser(
        'person-view',
        help='Regenerate the derived Person/{Name}/ symlink view from graph edges',
        description='Rebuild ~/Documents/Person/ as symlinks to doc-class files '
                    '(idempotent; aborts if a real file is found under the view root)'
    )
    person_view_parser.add_argument('--view-root',
                                    help='Root directory for the symlink view (default ~/Documents/Person)')  # noqa: E501
    person_view_parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                                    help='Path to SQLite database')
    person_view_parser.add_argument('--apply', action='store_true',
                                    help='Write symlinks (default is dry-run)')
    person_view_parser.add_argument('--prune-missing', action='store_true',
                                    help='First drop file->person edges whose file path '
                                         'no longer exists (honors --apply/dry-run)')
    person_view_parser.set_defaults(func=cmd_person_view)

    # Migrate legacy on-disk Person/ files into Personal/{subcat}/
    migrate_person_parser = subparsers.add_parser(
        'migrate-person',
        help='Migrate legacy on-disk Person/ files into Personal/{subcat}/ folders',
        description='Filesystem-walk migration of ~/Documents/Person/ into '
                    'Personal/{subcat}/; dry-run by default, manifest-backed rollback'
    )
    migrate_person_parser.add_argument('--person-root',
                                       help='Source root to migrate (default ~/Documents/Person)')
    migrate_person_parser.add_argument('--documents-root',
                                       help='Destination base for Personal/ (default ~/Documents)')
    migrate_person_parser.add_argument('--manifest',
                                       help='Manifest path (default person-migrate-manifest.json)')
    migrate_person_parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                                       help='Path to SQLite database')
    migrate_person_parser.add_argument('--no-db', action='store_true',
                                       help='Skip DB lookups and updates')
    migrate_person_parser.add_argument('--apply', action='store_true',
                                       help='Move files (default is dry-run)')
    migrate_person_parser.add_argument('--rollback', action='store_true',
                                       help='Reverse a prior apply using the manifest')
    migrate_person_parser.set_defaults(func=cmd_migrate_person)

    # Index migrated files into the graph with person edges (no file moves)
    index_people_parser = subparsers.add_parser(
        'index-people',
        help='Attach person->file graph edges for migrated files (no moves)',
        description='Register migrated Personal/ files in the graph at their '
                    'current path and attach person edges derived from the '
                    'migration manifest, so person-view can populate. No files move.'
    )
    index_people_parser.add_argument('--manifest',
                                     help='Migration manifest path (default person-migrate-manifest.json)')  # noqa: E501
    index_people_parser.add_argument('--person-root',
                                     help='Original Person/ root the manifest sources came from (default ~/Documents/Person)')  # noqa: E501
    index_people_parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                                     help='Path to SQLite database')
    index_people_parser.add_argument('--apply', action='store_true',
                                     help='Write graph rows/edges (default is dry-run)')
    index_people_parser.add_argument('--prune-missing', action='store_true',
                                     help='Afterwards drop file->person edges whose file '
                                          'path no longer exists (honors --apply/dry-run)')
    index_people_parser.set_defaults(func=cmd_index_people)

    # Prune person nodes + their file edges from the graph
    prune_person_parser = subparsers.add_parser(
        'prune-person',
        help='Delete people and their file->person graph edges (no file moves)',
        description='Remove false-positive or stale Person rows and all their '
                    'file->person edges from the graph. Files on disk are never '
                    'touched. Dry-run by default; --apply backs up the database '
                    'first, then deletes.'
    )
    prune_person_parser.add_argument('people', nargs='+',
                                     help='Person names or integer IDs to prune')
    prune_person_parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                                     help='Path to SQLite database')
    prune_person_parser.add_argument('--apply', action='store_true',
                                     help='Delete (default is dry-run)')
    prune_person_parser.set_defaults(func=cmd_prune_person)

    # Health check
    health_parser = subparsers.add_parser(
        'health',
        help='Check system dependencies and feature availability',
        description='Run system health check to verify all dependencies are installed'
    )
    health_parser.set_defaults(func=cmd_health)

    # Update site data
    update_site_parser = subparsers.add_parser(
        'update-site',
        help='Update _site dashboard data files',
        description='Generate and update dashboard data in _site directory'
    )
    add_update_site_arguments(update_site_parser)
    update_site_parser.set_defaults(func=cmd_update_site)

    # Generate timeline
    timeline_parser = subparsers.add_parser(
        'timeline',
        help='Generate timeline visualization data',
        description='Query database and create timeline_data.json for frontend'
    )
    add_timeline_arguments(timeline_parser)
    timeline_parser.set_defaults(func=cmd_timeline)

    # Parse and execute
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Execute the command
    args.func(args)


if __name__ == '__main__':
    main()
