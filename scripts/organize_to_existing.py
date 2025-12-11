#!/usr/bin/env python3
"""
Organize content-described files into existing Schema.org folder structure.
Maps content types to existing folders in ~/Documents.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from collections import defaultdict

# Map content types to existing folder paths
CONTENT_TO_EXISTING_FOLDER = {
    # Animals/Pets -> ImageObject/Photograph (closest existing match)
    "an animal or pet": "ImageObject/Photograph",

    # Memes/Social -> CreativeWork/SocialMediaPosting
    "a meme or social media image": "CreativeWork/SocialMediaPosting",

    # Logos -> CreativeWork/Brand
    "a logo or brand image": "CreativeWork/Brand",

    # Games -> CreativeWork/GameAsset/Sprites
    "a game or entertainment": "CreativeWork/GameAsset/Sprites",

    # Artwork -> CreativeWork/VisualArtwork
    "artwork or illustration": "CreativeWork/VisualArtwork",

    # Documents -> DigitalDocument/Document
    "a document or text": "DigitalDocument/Document",

    # Screenshots -> ImageObject/Screenshot
    "screenshot: a computer screen": "ImageObject/Screenshot",
    "screenshot: a mobile phone": "ImageObject/Screenshot",

    # Diagrams -> CreativeWork/Diagram
    "a diagram or chart": "CreativeWork/Diagram",

    # Portraits -> ImageObject/Photograph
    "people or portrait": "ImageObject/Photograph",

    # Products -> Product (existing folder)
    "a product or object": "Product",

    # Interior -> RealEstateListing
    "an interior room": "RealEstateListing",

    # Food -> ImageObject/Photograph
    "food or a meal": "ImageObject/Photograph",

    # Nature/Landscape -> ImageObject/Photograph
    "a landscape or nature scene": "ImageObject/Photograph",

    # Cityscape -> ImageObject/Photograph
    "a cityscape or urban scene": "ImageObject/Photograph",

    # Vehicles -> ImageObject/Photograph
    "a vehicle or transportation": "ImageObject/Photograph",

    # Buildings -> ImageObject/Photograph
    "a building or architecture": "ImageObject/Photograph",

    # Events -> ImageObject/Photograph
    "an event or celebration": "ImageObject/Photograph",

    # Sports -> ImageObject/Photograph
    "sports or physical activity": "ImageObject/Photograph",

    # Abstract -> CreativeWork/VisualArtwork
    "abstract art or pattern": "CreativeWork/VisualArtwork",
}


def organize_files(base_path: str = "~/Documents", dry_run: bool = False) -> dict:
    """Organize files from ~/Documents root into existing subfolders."""

    base_path = Path(base_path).expanduser()

    # Load the content rename log to get content types
    log_file = Path(__file__).parent.parent / 'results' / 'content_rename_log.json'
    with open(log_file, 'r') as f:
        rename_data = json.load(f)

    # Build mapping of filename to content type
    filename_to_content = {}
    for item in rename_data['log']:
        # Get the final filename (after all renames)
        final_name = Path(item['new']).name
        filename_to_content[final_name] = item.get('content_type')

    print(f"\n{'='*60}")
    print(f"Organizing Files to Existing Folders {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")
    print(f"Base path: {base_path}")

    # Find all files in ~/Documents root that match our renamed files
    root_files = [f for f in base_path.iterdir() if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic']]

    # Filter to only files we renamed (have content descriptions)
    files_to_organize = []
    for f in root_files:
        # Check if this looks like one of our renamed files
        if any(keyword in f.name.lower() for keyword in ['_pet_', '_meme_', '_logo_', '_game_', '_art_', '_doc_', '_screenshot_', '_chart_', '_portrait_', '_product_', '_interior_', '_food_']):
            files_to_organize.append(f)

    print(f"Files to organize: {len(files_to_organize)}\n")

    stats = defaultdict(int)
    organization_log = []

    for i, file_path in enumerate(files_to_organize, 1):
        # Determine content type from filename
        content_type = None
        fname_lower = file_path.name.lower()

        if '_pet_' in fname_lower:
            content_type = "an animal or pet"
        elif '_meme_' in fname_lower:
            content_type = "a meme or social media image"
        elif '_logo_' in fname_lower:
            content_type = "a logo or brand image"
        elif '_game_' in fname_lower:
            content_type = "a game or entertainment"
        elif '_art_' in fname_lower:
            content_type = "artwork or illustration"
        elif '_doc_' in fname_lower:
            content_type = "a document or text"
        elif '_screenshot_' in fname_lower:
            content_type = "screenshot: a computer screen"
        elif '_chart_' in fname_lower:
            content_type = "a diagram or chart"
        elif '_portrait_' in fname_lower:
            content_type = "people or portrait"
        elif '_product_' in fname_lower:
            content_type = "a product or object"
        elif '_interior_' in fname_lower:
            content_type = "an interior room"
        elif '_food_' in fname_lower:
            content_type = "food or a meal"

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
        if dest_path.exists():
            counter = 1
            stem = file_path.stem
            ext = file_path.suffix
            while dest_path.exists():
                new_name = f"{stem}_{counter}{ext}"
                dest_path = dest_dir / new_name
                counter += 1

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
        print(f"\n⚠️  This was a DRY RUN - no files were moved")

    # Show breakdown by folder
    if organization_log:
        print(f"\nFiles by Destination Folder:")
        print("-" * 40)
        folder_counts = defaultdict(int)
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
