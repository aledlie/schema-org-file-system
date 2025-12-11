#!/usr/bin/env python3
"""
Add content descriptions to renamed image filenames.
Uses the analysis results from analyze_renamed_files.py to add meaningful descriptions.
"""

import os
import sys
import json
import re
from pathlib import Path
from collections import defaultdict

# Content type to short description mapping
CONTENT_ABBREVIATIONS = {
    "an animal or pet": "pet",
    "a meme or social media image": "meme",
    "a logo or brand image": "logo",
    "a game or entertainment": "game",
    "artwork or illustration": "art",
    "a document or text": "doc",
    "screenshot: a computer screen": "screenshot",
    "screenshot: a mobile phone": "mobile",
    "a diagram or chart": "chart",
    "people or portrait": "portrait",
    "a product or object": "product",
    "an interior room": "interior",
    "food or a meal": "food",
    "a landscape or nature scene": "landscape",
    "a cityscape or urban scene": "cityscape",
    "a vehicle or transportation": "vehicle",
    "a building or architecture": "building",
    "an event or celebration": "event",
    "sports or physical activity": "sports",
    "abstract art or pattern": "abstract",
}


def sanitize_for_filename(text: str, max_length: int = 30) -> str:
    """Sanitize text for use in filename."""
    if not text:
        return ""

    # Remove special characters, keep alphanumeric and spaces
    clean = re.sub(r'[^\w\s-]', '', text)
    # Replace spaces with underscores
    clean = re.sub(r'\s+', '_', clean.strip())
    # Remove multiple underscores
    clean = re.sub(r'_+', '_', clean)
    # Truncate
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip('_')
    return clean


def extract_ocr_keywords(ocr_text: str, max_words: int = 3) -> str:
    """Extract meaningful keywords from OCR text."""
    if not ocr_text:
        return ""

    # Skip if OCR text is too short or looks like garbage
    if len(ocr_text) < 5:
        return ""

    # Common noise patterns to skip
    noise_patterns = [
        r'^[\s\-\|\_\.\,\!\?\@\#\$\%\^\&\*\(\)]+$',  # Just punctuation
        r'^[a-z]{1,2}$',  # Single/double letters
    ]

    for pattern in noise_patterns:
        if re.match(pattern, ocr_text.strip(), re.IGNORECASE):
            return ""

    # Get first few meaningful words
    words = ocr_text.split()
    meaningful_words = []

    for word in words:
        # Skip short words and numbers-only
        clean_word = re.sub(r'[^\w]', '', word)
        if len(clean_word) >= 3 and not clean_word.isdigit():
            meaningful_words.append(clean_word)
            if len(meaningful_words) >= max_words:
                break

    return '_'.join(meaningful_words) if meaningful_words else ""


def generate_descriptive_filename(result: dict) -> str:
    """Generate a new descriptive filename from analysis result."""
    original_path = Path(result['path'])
    original_name = original_path.stem
    ext = original_path.suffix.lower()

    parts = []

    # Keep the date portion if it exists (YYYYMMDD)
    date_match = re.match(r'^(\d{8})', original_name)
    if date_match:
        parts.append(date_match.group(1))

    # Add content type abbreviation
    content_type = result.get('content_type')
    if content_type and content_type in CONTENT_ABBREVIATIONS:
        parts.append(CONTENT_ABBREVIATIONS[content_type])
    elif content_type:
        # Try to create abbreviation from content type
        abbrev = sanitize_for_filename(content_type.split()[0], max_length=10)
        if abbrev:
            parts.append(abbrev.lower())

    # Add OCR keywords if available and meaningful
    ocr_text = result.get('ocr_text')
    if ocr_text:
        keywords = extract_ocr_keywords(ocr_text)
        if keywords and len(keywords) > 3:
            parts.append(keywords)

    # Add confidence indicator for high-confidence classifications
    confidence = result.get('confidence')
    if confidence and confidence >= 0.7:
        pass  # Don't add anything, high confidence is the default
    elif confidence and confidence < 0.5:
        parts.append('uncertain')

    # Keep time portion if it exists (HHMMSS)
    time_match = re.search(r'_(\d{6})(?:_\d+)?$', original_name)
    if time_match:
        parts.append(time_match.group(1))

    # Handle duplicate suffix (_N)
    dup_match = re.search(r'_(\d+)$', original_name)
    if dup_match and not time_match:
        parts.append(dup_match.group(1))

    # Build new filename
    new_name = '_'.join(parts) + ext

    return new_name


def rename_with_descriptions(analysis_file: str, dry_run: bool = False) -> dict:
    """Rename files based on analysis results."""

    # Load analysis results
    with open(analysis_file, 'r') as f:
        data = json.load(f)

    results = data.get('results', [])

    print(f"\n{'='*60}")
    print(f"Adding Content Descriptions to Filenames {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")
    print(f"Files to process: {len(results)}\n")

    stats = defaultdict(int)
    rename_log = []

    for i, result in enumerate(results, 1):
        original_path = Path(result['path'])

        # Skip if file doesn't exist
        if not original_path.exists():
            stats['missing'] += 1
            continue

        # Skip if no content type identified
        if not result.get('content_type'):
            stats['no_content_type'] += 1
            continue

        # Generate new filename
        new_name = generate_descriptive_filename(result)
        new_path = original_path.parent / new_name

        # Skip if name unchanged
        if new_path == original_path:
            stats['unchanged'] += 1
            continue

        # Handle collisions
        if new_path.exists() and new_path != original_path:
            counter = 1
            stem = Path(new_name).stem
            ext = Path(new_name).suffix
            while new_path.exists():
                new_name = f"{stem}_{counter}{ext}"
                new_path = original_path.parent / new_name
                counter += 1

        # Perform rename
        try:
            if not dry_run:
                original_path.rename(new_path)

            stats['renamed'] += 1
            rename_log.append({
                'original': str(original_path),
                'new': str(new_path),
                'content_type': result.get('content_type'),
                'confidence': result.get('confidence')
            })

            if i <= 50 or i % 100 == 0:
                action = "Would rename" if dry_run else "Renamed"
                print(f"  {action}: {original_path.name} → {new_name}")

        except Exception as e:
            stats['errors'] += 1
            print(f"  Error: {original_path.name}: {e}")

    # Print summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}\n")
    print(f"Total processed: {len(results)}")
    print(f"Renamed: {stats['renamed']}")
    print(f"Unchanged: {stats['unchanged']}")
    print(f"No content type: {stats['no_content_type']}")
    print(f"Missing files: {stats['missing']}")
    print(f"Errors: {stats['errors']}")

    if dry_run:
        print(f"\n⚠️  This was a DRY RUN - no files were renamed")

    return {
        'stats': dict(stats),
        'log': rename_log
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Add content descriptions to renamed image filenames'
    )
    parser.add_argument(
        '--analysis-file',
        default=str(Path(__file__).parent.parent / 'results' / 'renamed_files_analysis.json'),
        help='Path to analysis JSON file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without renaming'
    )
    parser.add_argument(
        '--output-log',
        help='Save rename log to JSON file'
    )

    args = parser.parse_args()

    result = rename_with_descriptions(
        analysis_file=args.analysis_file,
        dry_run=args.dry_run
    )

    if args.output_log:
        with open(args.output_log, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nRename log saved to: {args.output_log}")


if __name__ == '__main__':
    main()
