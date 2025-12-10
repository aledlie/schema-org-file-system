#!/usr/bin/env python3
"""
Update Organization Report with Labeled Category Data

This script updates the content_organization_report with category assignments
from the labeling sessions stored in the database.
"""

import json
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


def compute_file_id(filepath: str) -> str:
    """Compute the file ID (SHA-256 hash of the path)."""
    return hashlib.sha256(filepath.encode()).hexdigest()


def get_labeled_categories(db_path: str, ml_session: str) -> Tuple[Dict, Dict]:
    """
    Get file-to-category mappings from labeling sessions.
    These are manual corrections that should override ML predictions.

    The labeling sessions processed files BEFORE organization, so paths differ.
    We match by FILENAME since files were moved during organization.

    Args:
        db_path: Path to SQLite database
        ml_session: The main ML session ID to exclude

    Returns:
        Tuple of (path_dict, filename_dict) mapping to category info
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get ONLY labeling session data (manual corrections)
    # These are the ground truth labels from human review
    query_labeling = """
    SELECT f.original_path, f.filename, c.name, c.full_path
    FROM files f
    JOIN file_categories fc ON f.id = fc.file_id
    JOIN categories c ON fc.category_id = c.id
    WHERE f.session_id <> ?
    """

    cursor.execute(query_labeling, (ml_session,))

    labeled_by_path = {}
    labeled_by_filename = {}
    for row in cursor.fetchall():
        original_path, filename, category_name, full_path = row
        parts = full_path.split('/') if full_path else []
        parent_category = parts[0] if parts else category_name

        labeled_by_path[original_path] = (category_name, full_path, parent_category)
        # Index by filename for matching moved files
        labeled_by_filename[filename] = (category_name, full_path, parent_category)

    print(f"  - Labeling session records: {len(labeled_by_path)}")
    print(f"  - Unique filenames: {len(labeled_by_filename)}")

    conn.close()
    return labeled_by_path, labeled_by_filename


def update_report(report_path: str, labeled_data: Tuple[Dict, Dict], output_path: str) -> Dict:
    """
    Update the organization report with labeled category data.

    Args:
        report_path: Path to original report JSON
        labeled_data: Tuple of (path_dict, filename_dict) mapping to category info
        output_path: Path to save updated report

    Returns:
        Statistics about the update
    """
    labeled_by_path, labeled_by_filename = labeled_data

    print(f"Loading report from: {report_path}")
    with open(report_path, 'r') as f:
        report = json.load(f)

    results = report.get('results', [])

    stats = {
        'total_files': len(results),
        'updated': 0,
        'unchanged': 0,
        'matched_by_path': 0,
        'matched_by_filename': 0,
        'not_found': 0,
        'category_changes': {},
        'updated_files': []
    }

    for result in results:
        source = result.get('source', '')
        filename = Path(source).name if source else ''

        # Try to match by path first, then by filename
        match = None
        match_type = None
        if source in labeled_by_path:
            match = labeled_by_path[source]
            match_type = 'path'
        elif filename in labeled_by_filename:
            match = labeled_by_filename[filename]
            match_type = 'filename'

        if match:
            subcategory, full_path, parent_category = match
            old_category = result.get('category', 'unknown')
            old_subcategory = result.get('subcategory', 'unknown')

            if match_type == 'path':
                stats['matched_by_path'] += 1
            else:
                stats['matched_by_filename'] += 1

            # Only update if different
            if old_subcategory != subcategory or old_category != parent_category:
                # Track the change
                change_key = f"{old_category}/{old_subcategory} -> {parent_category}/{subcategory}"
                stats['category_changes'][change_key] = stats['category_changes'].get(change_key, 0) + 1

                # Update the result
                result['category'] = parent_category
                result['subcategory'] = subcategory
                result['label_source'] = 'database_verified'

                stats['updated'] += 1
                stats['updated_files'].append({
                    'path': source,
                    'old': f"{old_category}/{old_subcategory}",
                    'new': f"{parent_category}/{subcategory}"
                })
            else:
                stats['unchanged'] += 1
        else:
            stats['not_found'] += 1

    # Update report metadata
    report['label_update_timestamp'] = datetime.now().isoformat()
    report['labeled_files_count'] = stats['updated']
    report['total_matched'] = stats['matched_by_path'] + stats['matched_by_filename']

    # Save updated report
    print(f"Saving updated report to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Update organization report with labeled categories')
    parser.add_argument('--report', '-r',
                        default='results/content_organization_report_20251209_104237.json',
                        help='Path to original organization report')
    parser.add_argument('--database', '-d',
                        default='results/file_organization.db',
                        help='Path to SQLite database')
    parser.add_argument('--output', '-o',
                        help='Output path (default: timestamped in results/)')
    parser.add_argument('--ml-session',
                        default='a6b07a390a11312d8306bcd3589c20572c146747338809c1d0ad5af53edd40bb',
                        help='Session ID for the main ML run with labels')

    args = parser.parse_args()

    # Generate output path with timestamp
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f'results/content_organization_report_labeled_{timestamp}.json'

    print("=" * 60)
    print("UPDATE ORGANIZATION REPORT WITH LABELED CATEGORIES")
    print("=" * 60)

    # Get labeled categories from database
    print("\nFetching labeled categories from database...")
    labeled_data = get_labeled_categories(args.database, args.ml_session)
    labeled_by_path, labeled_by_filename = labeled_data
    print(f"Found {len(labeled_by_path)} labeled files by path")
    print(f"Found {len(labeled_by_filename)} unique filenames")

    # Update the report
    print("\nUpdating report...")
    stats = update_report(args.report, labeled_data, output_path)

    # Print summary
    print("\n" + "-" * 40)
    print("UPDATE SUMMARY")
    print("-" * 40)
    print(f"Total files in report: {stats['total_files']:,}")
    print(f"Matched by path: {stats['matched_by_path']:,}")
    print(f"Matched by filename: {stats['matched_by_filename']:,}")
    print(f"Files updated: {stats['updated']:,}")
    print(f"Files unchanged: {stats['unchanged']:,}")
    print(f"Files not found in DB: {stats['not_found']:,}")

    if stats['category_changes']:
        print("\n" + "-" * 40)
        print("CATEGORY CHANGES")
        print("-" * 40)
        for change, count in sorted(stats['category_changes'].items(), key=lambda x: -x[1]):
            print(f"  {change}: {count} files")

    print("\n" + "-" * 40)
    print(f"Updated report saved to: {output_path}")
    print("=" * 60)

    return output_path


if __name__ == "__main__":
    main()
