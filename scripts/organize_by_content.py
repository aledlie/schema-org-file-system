#!/usr/bin/env python3
"""
Organize renamed files into Schema.org-based folder structure based on content type.
Uses the CLIP classification results to determine proper organization.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple

# Schema.org-based folder mapping for content types
CONTENT_TO_SCHEMA = {
    # Animals/Pets -> ImageObject/Animal
    "an animal or pet": ("ImageObject", "Animal"),

    # Memes/Social -> CreativeWork/SocialMediaPosting
    "a meme or social media image": ("CreativeWork", "SocialMediaPosting"),

    # Logos -> CreativeWork/Brand
    "a logo or brand image": ("CreativeWork", "Brand"),

    # Games -> CreativeWork/GameAsset
    "a game or entertainment": ("CreativeWork", "GameAsset"),

    # Artwork -> CreativeWork/VisualArtwork
    "artwork or illustration": ("CreativeWork", "VisualArtwork"),

    # Documents -> DigitalDocument/Document
    "a document or text": ("DigitalDocument", "Document"),

    # Screenshots -> ImageObject/Screenshot
    "screenshot: a computer screen": ("ImageObject", "Screenshot"),
    "screenshot: a mobile phone": ("ImageObject", "MobileScreenshot"),

    # Diagrams -> CreativeWork/Diagram
    "a diagram or chart": ("CreativeWork", "Diagram"),

    # Portraits -> ImageObject/Portrait
    "people or portrait": ("ImageObject", "Portrait"),

    # Products -> Product/Image
    "a product or object": ("Product", "ProductImage"),

    # Interior -> RealEstateListing/Interior
    "an interior room": ("RealEstateListing", "Interior"),

    # Food -> ImageObject/FoodPhoto
    "food or a meal": ("ImageObject", "FoodPhoto"),

    # Nature/Landscape -> ImageObject/Landscape
    "a landscape or nature scene": ("ImageObject", "Landscape"),

    # Cityscape -> ImageObject/Cityscape
    "a cityscape or urban scene": ("ImageObject", "Cityscape"),

    # Vehicles -> ImageObject/Vehicle
    "a vehicle or transportation": ("ImageObject", "Vehicle"),

    # Buildings -> ImageObject/Architecture
    "a building or architecture": ("ImageObject", "Architecture"),

    # Events -> ImageObject/Event
    "an event or celebration": ("ImageObject", "Event"),

    # Sports -> ImageObject/Sports
    "sports or physical activity": ("ImageObject", "Sports"),

    # Abstract -> CreativeWork/AbstractArt
    "abstract art or pattern": ("CreativeWork", "AbstractArt"),
}


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

    base_path = Path(base_path).expanduser()

    # Load rename log with content types
    with open(rename_log_file, 'r') as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print(f"Organizing Files by Content {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")
    print(f"Base path: {base_path}")
    print(f"Files to organize: {len(data['log'])}")
    print(f"Mode: {'Move' if move_files else 'Copy'}\n")

    stats = defaultdict(int)
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
        dest_dir = get_schema_path(content_type, base_path)
        dest_path = dest_dir / source_path.name

        # Skip if already in correct location
        if source_path.parent == dest_dir:
            stats['already_organized'] += 1
            continue

        # Handle collisions
        if dest_path.exists():
            counter = 1
            stem = source_path.stem
            ext = source_path.suffix
            while dest_path.exists():
                new_name = f"{stem}_{counter}{ext}"
                dest_path = dest_dir / new_name
                counter += 1

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
                rel_dest = dest_path.relative_to(base_path)
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
        print(f"\n⚠️  This was a DRY RUN - no files were moved")

    # Show organization breakdown
    if organization_log:
        print(f"\nOrganization by Schema.org Category:")
        print("-" * 40)
        category_counts = defaultdict(int)
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
