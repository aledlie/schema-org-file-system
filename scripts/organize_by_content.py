#!/usr/bin/env python3
"""
Organize renamed files into Schema.org-based folder structure based on content type.
Uses the CLIP classification results to determine proper organization.
"""

import json
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict

from shared.constants import CONTENT_TO_SCHEMA
from shared.file_ops import resolve_collision


def get_schema_path(content_type: str, base_path: Path) -> Path:
    """Get the Schema.org-based path for a content type."""
    if content_type in CONTENT_TO_SCHEMA:
        category, subcategory = CONTENT_TO_SCHEMA[content_type]
        return base_path / category / subcategory
    else:
        # Default to ImageObject/Other for unknown types
        return base_path / "ImageObject" / "Other"


def organize_files(
    rename_log_file: str,
    base_path: str = "~/Documents",
    dry_run: bool = False,
    move_files: bool = True
) -> Dict:
    """Organize files based on content classification."""

    base_dir = Path(base_path).expanduser()

    # Load rename log with content types
    with open(rename_log_file, 'r') as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print(f"Organizing Files by Content {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")
    print(f"Base path: {base_dir}")
    print(f"Files to organize: {len(data['log'])}")
    print(f"Mode: {'Move' if move_files else 'Copy'}\n")

    stats: defaultdict[str, int] = defaultdict(int)
    organization_log = []

    for i, item in enumerate(data['log'], 1):
        source_path = Path(item['new'])
        content_type = item.get('content_type')

        # Skip if file doesn't exist
        if not source_path.exists():
            stats['missing'] += 1
            continue

        # Skip if no content type
        if not content_type:
            stats['no_content_type'] += 1
            continue

        # Get destination path
        dest_dir = get_schema_path(content_type, base_dir)
        dest_path = dest_dir / source_path.name

        # Skip if already in correct location
        if source_path.parent == dest_dir:
            stats['already_organized'] += 1
            continue

        # Handle collisions
        dest_path = resolve_collision(dest_path)

        # Create destination directory
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Move or copy file
        try:
            if not dry_run:
                if move_files:
                    shutil.move(str(source_path), str(dest_path))
                else:
                    shutil.copy2(str(source_path), str(dest_path))

            stats['organized'] += 1
            organization_log.append({
                'source': str(source_path),
                'destination': str(dest_path),
                'content_type': content_type,
                'schema_category': CONTENT_TO_SCHEMA.get(content_type, ('ImageObject', 'Other'))
            })

            if i <= 30 or i % 50 == 0:
                action = "Would move" if dry_run else ("Moved" if move_files else "Copied")
                rel_dest = dest_path.relative_to(base_dir)
                print(f"  {action}: {source_path.name}")
                print(f"       → {rel_dest}")

        except Exception as e:
            stats['errors'] += 1
            print(f"  Error: {source_path.name}: {e}")

    # Print summary
    print(f"\n{'='*60}")
    print("Organization Summary")
    print(f"{'='*60}\n")
    print(f"Total files: {len(data['log'])}")
    print(f"Organized: {stats['organized']}")
    print(f"Already in place: {stats['already_organized']}")
    print(f"Missing files: {stats['missing']}")
    print(f"No content type: {stats['no_content_type']}")
    print(f"Errors: {stats['errors']}")

    if dry_run:
        print("\n⚠️  This was a DRY RUN - no files were moved")

    # Show organization breakdown
    if organization_log:
        print("\nOrganization by Schema.org Category:")
        print("-" * 40)
        category_counts: defaultdict[str, int] = defaultdict(int)
        for item in organization_log:
            cat = "/".join(item['schema_category'])
            category_counts[cat] += 1

        for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat}: {count}")

    return {
        'stats': dict(stats),
        'log': organization_log
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Organize files into Schema.org-based folder structure'
    )
    parser.add_argument(
        '--rename-log',
        default=str(Path(__file__).parent.parent / 'results' / 'content_rename_log.json'),
        help='Path to rename log JSON file'
    )
    parser.add_argument(
        '--base-path',
        default='~/Documents',
        help='Base path for organization (default: ~/Documents)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without moving files'
    )
    parser.add_argument(
        '--copy',
        action='store_true',
        help='Copy files instead of moving'
    )
    parser.add_argument(
        '--output-log',
        help='Save organization log to JSON file'
    )

    args = parser.parse_args()

    result = organize_files(
        rename_log_file=args.rename_log,
        base_path=args.base_path,
        dry_run=args.dry_run,
        move_files=not args.copy
    )

    if args.output_log:
        with open(args.output_log, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nOrganization log saved to: {args.output_log}")


if __name__ == '__main__':
    main()
