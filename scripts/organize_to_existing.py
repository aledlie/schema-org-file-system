#!/usr/bin/env python3
"""
Organize content-described files into existing Schema.org folder structure.
Maps content types to existing folders in ~/Documents.
"""

import json
import shutil
from pathlib import Path
from collections import defaultdict

from shared.constants import CONTENT_TO_EXISTING_FOLDER, CONTENT_ABBREVIATIONS, IMAGE_EXTENSIONS
from shared.file_ops import resolve_collision

# Reverse lookup: "_abbrev_" substring → canonical content type label.
# CONTENT_ABBREVIATIONS maps content_type → abbrev, so we invert it here.
# Derived from shared constants so it stays in sync automatically.
_ABBREV_TO_CONTENT = {f"_{abbrev}_": ctype for ctype, abbrev in CONTENT_ABBREVIATIONS.items()}


def organize_files(base_path: str = "~/Documents", dry_run: bool = False) -> dict:
    """Organize files from ~/Documents root into existing subfolders."""

    base_path = Path(base_path).expanduser()

    print(f"\n{'='*60}")
    print(f"Organizing Files to Existing Folders {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")
    print(f"Base path: {base_path}")

    # Find all files in ~/Documents root that match our renamed files
    root_files = [f for f in base_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]

    # Filter to only files we renamed (have content descriptions)
    files_to_organize = []
    for f in root_files:
        if any(abbrev in f.name.lower() for abbrev in _ABBREV_TO_CONTENT):
            files_to_organize.append(f)

    print(f"Files to organize: {len(files_to_organize)}\n")

    stats: defaultdict[str, int] = defaultdict(int)
    organization_log = []

    for i, file_path in enumerate(files_to_organize, 1):
        # Determine content type from filename abbreviation
        content_type = None
        fname_lower = file_path.name.lower()

        # First-match wins; order is CONTENT_ABBREVIATIONS insertion order (Python 3.7+ dict guarantee).
        # Files matching multiple abbreviations resolve to whichever appears first in that dict.
        for abbrev_key, ctype in _ABBREV_TO_CONTENT.items():
            if abbrev_key in fname_lower:
                content_type = ctype
                break

        if not content_type:
            stats['no_content_type'] += 1
            continue

        # Get destination folder
        dest_folder = CONTENT_TO_EXISTING_FOLDER.get(content_type)
        if not dest_folder:
            stats['no_mapping'] += 1
            continue

        dest_dir = base_path / dest_folder
        dest_path = dest_dir / file_path.name

        # Create directory if needed
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle collisions
        dest_path = resolve_collision(dest_path)

        # Move file
        try:
            if not dry_run:
                shutil.move(str(file_path), str(dest_path))

            stats['organized'] += 1
            organization_log.append({
                'source': str(file_path),
                'destination': str(dest_path),
                'content_type': content_type,
                'folder': dest_folder
            })

            if i <= 30 or i % 100 == 0:
                action = "Would move" if dry_run else "Moved"
                print(f"  {action}: {file_path.name}")
                print(f"       → {dest_folder}/")

        except Exception as e:
            stats['errors'] += 1
            print(f"  Error: {file_path.name}: {e}")

    # Print summary
    print(f"\n{'='*60}")
    print("Organization Summary")
    print(f"{'='*60}\n")
    print(f"Total files found: {len(files_to_organize)}")
    print(f"Organized: {stats['organized']}")
    print(f"No content type: {stats['no_content_type']}")
    print(f"No folder mapping: {stats['no_mapping']}")
    print(f"Errors: {stats['errors']}")

    if dry_run:
        print("\n⚠️  This was a DRY RUN - no files were moved")

    # Show breakdown by folder
    if organization_log:
        print("\nFiles by Destination Folder:")
        print("-" * 40)
        folder_counts: defaultdict[str, int] = defaultdict(int)
        for item in organization_log:
            folder_counts[item['folder']] += 1

        for folder, count in sorted(folder_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {folder}: {count}")

    return {
        'stats': dict(stats),
        'log': organization_log
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Organize files into existing folder structure'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without moving files'
    )
    parser.add_argument(
        '--output-log',
        help='Save organization log to JSON file'
    )

    args = parser.parse_args()

    result = organize_files(dry_run=args.dry_run)

    if args.output_log:
        with open(args.output_log, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nOrganization log saved to: {args.output_log}")


if __name__ == '__main__':
    main()
