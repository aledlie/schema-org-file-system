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
from typing import List, Any

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def cmd_content(args: Any) -> None:
    """Run content-based organization using AI/OCR."""
    # Import here to avoid loading heavy dependencies until needed
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from file_organizer_content_based import ContentBasedFileOrganizer, main as content_main

    # Delegate to existing main function with modified sys.argv
    sys.argv = ['organize-files content'] + _args_to_argv(args)
    content_main()


def cmd_name(args: Any) -> None:
    """Run name-based organization (no AI)."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from src.organizers.name_organizer import main as name_main

    sys.argv = ['organize-files name'] + _args_to_argv(args)
    name_main()


def cmd_type(args: Any) -> None:
    """Run type-based organization by file extension."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from file_organizer_by_type import main as type_main

    sys.argv = ['organize-files type'] + _args_to_argv(args)
    type_main()


def cmd_preprocess(args: Any) -> None:
    """Run ML data preprocessing."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from data_preprocessing import main as preprocess_main

    sys.argv = ['organize-files preprocess'] + _args_to_argv(args)
    preprocess_main()


def cmd_evaluate(args: Any) -> None:
    """Run model evaluation."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from evaluate_model import main as evaluate_main

    sys.argv = ['organize-files evaluate'] + _args_to_argv(args)
    evaluate_main()


def cmd_migrate(args: Any) -> None:
    """Run database migration for ID generation."""
    from storage.migration import run_migration

    db_path = args.db_path or 'results/file_organization.db'
    print(f"\n{'='*60}")
    print("Running ID Generation Migration")
    print(f"{'='*60}\n")
    run_migration(db_path)
    print("\nMigration complete. Canonical IDs have been generated for existing records.")


def cmd_person_view(args: Any) -> None:
    """Regenerate the derived Person/{Name}/ symlink view from graph edges."""
    from storage.graph_store import GraphStore
    from storage.person_view_generator import PersonViewGenerator

    view_root = Path(args.view_root).expanduser() if args.view_root else None
    graph_store = GraphStore(args.db_path)
    generator = PersonViewGenerator(graph_store, view_root=view_root)
    apply = bool(args.apply)
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


def cmd_health(args: Any) -> None:
    """Run system health check."""
    from health_check import check_system
    check_system(verbose=True)


def cmd_update_site(args: Any) -> None:
    """Update _site dashboard data."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from update_site_data import main as update_main

    sys.argv = ['organize-files update-site'] + _args_to_argv(args)
    update_main()


def cmd_timeline(args: Any) -> None:
    """Generate timeline data for visualization."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from generate_timeline_data import main as timeline_main

    sys.argv = ['organize-files timeline'] + _args_to_argv(args)
    timeline_main()


def _args_to_argv(args: Any) -> List[str]:
    """Convert argparse namespace to argv list."""
    argv = []
    for key, value in vars(args).items():
        if key in ('func', 'command'):
            continue
        if value is None or value is False:
            continue
        if value is True:
            argv.append(f'--{key.replace("_", "-")}')
        elif isinstance(value, list):
            argv.append(f'--{key.replace("_", "-")}')
            argv.extend(str(v) for v in value)
        else:
            argv.append(f'--{key.replace("_", "-")}')
            argv.append(str(value))
    return argv


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
    content_parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                                default=['~/Desktop', '~/Downloads'],
                                help='Source directories to organize')
    content_parser.add_argument('--target', '--base-path', dest='base_path',
                                default='~/Documents',
                                help='Target directory for organized files')
    content_parser.add_argument('--dry-run', action='store_true',
                                help='Simulate without moving files')
    content_parser.add_argument('--limit', type=int,
                                help='Limit number of files to process')
    content_parser.add_argument('--report', help='Path to save JSON report')
    content_parser.add_argument('--no-cost-tracking', action='store_true',
                                help='Disable cost tracking')
    content_parser.add_argument('--no-sentry', action='store_true',
                                help='Disable Sentry error tracking')
    content_parser.add_argument('--db-path', default='results/file_organization.db',
                                help='SQLite database path')
    content_parser.add_argument('--no-db', action='store_true',
                                help='Disable database persistence')
    content_parser.set_defaults(func=cmd_content)

    # Name-based organization (no AI)
    name_parser = subparsers.add_parser(
        'name',
        help='Organize files by filename patterns (no AI)',
        description='Simple file organization based on filename patterns and paths'
    )
    name_parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                             default=['~/Desktop', '~/Downloads'],
                             help='Source directories to organize')
    name_parser.add_argument('--target', '--base-path', dest='base_path',
                             default='~/Documents',
                             help='Target directory for organized files')
    name_parser.add_argument('--dry-run', action='store_true',
                             help='Simulate without moving files')
    name_parser.add_argument('--limit', type=int,
                             help='Limit number of files to process')
    name_parser.set_defaults(func=cmd_name)

    # Type-based organization (by extension)
    type_parser = subparsers.add_parser(
        'type',
        help='Organize files by file type/extension',
        description='Simple file organization based on file extensions'
    )
    type_parser.add_argument('--source', '--sources', nargs='+', dest='sources',
                             default=['~/Desktop', '~/Downloads'],
                             help='Source directories to organize')
    type_parser.add_argument('--target', '--base-path', dest='base_path',
                             default='~/Documents',
                             help='Target directory for organized files')
    type_parser.add_argument('--dry-run', action='store_true',
                             help='Simulate without moving files')
    type_parser.set_defaults(func=cmd_type)

    # ML preprocessing
    preprocess_parser = subparsers.add_parser(
        'preprocess',
        help='Prepare training data for ML models',
        description='Data preprocessing pipeline for ML model training'
    )
    preprocess_parser.add_argument('--input', help='Input report JSON file')
    preprocess_parser.add_argument('--output', help='Output directory for training data')
    preprocess_parser.set_defaults(func=cmd_preprocess)

    # Model evaluation
    evaluate_parser = subparsers.add_parser(
        'evaluate',
        help='Evaluate model performance',
        description='Run evaluation metrics on test dataset'
    )
    evaluate_parser.add_argument('--test-data', help='Path to test dataset')
    evaluate_parser.add_argument('--model', help='Model to evaluate')
    evaluate_parser.add_argument(
        '--classifier', '-c', choices=['baseline', 'content'], default='baseline',
        help='baseline = filename heuristic; content = production CLIP+OCR classifier'
    )
    evaluate_parser.add_argument(
        '--min-support', type=int, default=None,
        help='Minimum per-class sample count for its metrics to be reported'
    )
    evaluate_parser.set_defaults(func=cmd_evaluate)

    # Database migration
    migrate_parser = subparsers.add_parser(
        'migrate-ids',
        help='Run database migration for canonical IDs',
        description='Add canonical_id columns and generate UUIDs for existing records'
    )
    migrate_parser.add_argument('--db-path', default='results/file_organization.db',
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
    person_view_parser.add_argument('--db-path', default='results/file_organization.db',
                                    help='Path to SQLite database')
    person_view_parser.add_argument('--apply', action='store_true',
                                    help='Write symlinks (default is dry-run)')
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
    migrate_person_parser.add_argument('--db-path', default='results/file_organization.db',
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
    index_people_parser.add_argument('--db-path', default='results/file_organization.db',
                                     help='Path to SQLite database')
    index_people_parser.add_argument('--apply', action='store_true',
                                     help='Write graph rows/edges (default is dry-run)')
    index_people_parser.set_defaults(func=cmd_index_people)

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
    update_site_parser.add_argument('--report', help='Source report JSON file')
    update_site_parser.set_defaults(func=cmd_update_site)

    # Generate timeline
    timeline_parser = subparsers.add_parser(
        'timeline',
        help='Generate timeline visualization data',
        description='Query database and create timeline_data.json for frontend'
    )
    timeline_parser.add_argument('--db-path', default='results/file_organization.db',
                                 help='Path to SQLite database')
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
