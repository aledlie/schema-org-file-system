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

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def cmd_content(args):
    """Run content-based organization using AI/OCR."""
    # Import here to avoid loading heavy dependencies until needed
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from file_organizer_content_based import ContentBasedFileOrganizer, main as content_main

    # Delegate to existing main function with modified sys.argv
    sys.argv = ['organize-files content'] + _args_to_argv(args)
    content_main()


def cmd_name(args):
    """Run name-based organization (no AI)."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from file_organizer_by_name import main as name_main

    sys.argv = ['organize-files name'] + _args_to_argv(args)
    name_main()


def cmd_type(args):
    """Run type-based organization by file extension."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from file_organizer_by_type import main as type_main

    sys.argv = ['organize-files type'] + _args_to_argv(args)
    type_main()


def cmd_preprocess(args):
    """Run ML data preprocessing."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from data_preprocessing import main as preprocess_main

    sys.argv = ['organize-files preprocess'] + _args_to_argv(args)
    preprocess_main()


def cmd_evaluate(args):
    """Run model evaluation."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from evaluate_model import main as evaluate_main

    sys.argv = ['organize-files evaluate'] + _args_to_argv(args)
    evaluate_main()


def cmd_migrate(args):
    """Run database migration for ID generation."""
    from storage.migration import run_migration

    db_path = args.db_path or 'results/file_organization.db'
    print(f"\n{'='*60}")
    print("Running ID Generation Migration")
    print(f"{'='*60}\n")
    run_migration(db_path)
    print("\nMigration complete. Canonical IDs have been generated for existing records.")


def cmd_health(args):
    """Run system health check."""
    from health_check import check_system
    check_system(verbose=True)


def cmd_update_site(args):
    """Update _site dashboard data."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from update_site_data import main as update_main

    sys.argv = ['organize-files update-site'] + _args_to_argv(args)
    update_main()


def cmd_timeline(args):
    """Generate timeline data for visualization."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
    from generate_timeline_data import main as timeline_main

    sys.argv = ['organize-files timeline'] + _args_to_argv(args)
    timeline_main()


def _args_to_argv(args):
    """Convert argparse namespace to argv list."""
    argv = []
    for key, value in vars(args).items():
        if key == 'func':
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


def main():
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
