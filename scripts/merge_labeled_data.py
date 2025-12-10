#!/usr/bin/env python3
"""
Merge Labeled Data from Database Sessions into Organization Report

This script combines:
1. Existing report data (from the main ML run)
2. Additional labeled data from labeling sessions (manual corrections)

The result is an enriched dataset with more diverse labeled examples.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def get_labeling_session_data(db_path: str, ml_session: str) -> List[Dict]:
    """
    Get labeled file data from labeling sessions (non-ML sessions).

    Args:
        db_path: Path to SQLite database
        ml_session: Session ID to exclude (the main ML run)

    Returns:
        List of file records with labels
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
    SELECT
        f.original_path,
        f.filename,
        f.file_extension,
        f.mime_type,
        f.file_size,
        f.schema_type,
        f.extracted_text,
        f.extracted_text_length,
        c.name as subcategory,
        c.full_path as full_category_path,
        f.session_id
    FROM files f
    JOIN file_categories fc ON f.id = fc.file_id
    JOIN categories c ON fc.category_id = c.id
    WHERE f.session_id <> ?
    """

    cursor.execute(query, (ml_session,))

    records = []
    for row in cursor.fetchall():
        full_path = row['full_category_path'] or ''
        parts = full_path.split('/') if full_path else []
        parent_category = parts[0] if parts else row['subcategory']

        record = {
            'source': row['original_path'],
            'status': 'organized',
            'reason': None,
            'destination': row['original_path'],  # Use original path as destination
            'schema': {
                '@context': 'https://schema.org',
                '@type': row['schema_type'] or 'DigitalDocument',
                'name': row['filename'],
                'description': row['filename'],
                'filePath': row['original_path']
            },
            'extracted_text_length': row['extracted_text_length'] or 0,
            'company_name': None,
            'people_names': [],
            'image_metadata': {},
            'category': parent_category,
            'subcategory': row['subcategory'],
            'is_valid': True,
            'label_source': 'manual_labeling',
            'session_id': row['session_id']
        }
        records.append(record)

    conn.close()
    return records


def merge_reports(report_path: str, labeling_data: List[Dict], output_path: str) -> Dict:
    """
    Merge labeling session data into the organization report.

    Args:
        report_path: Path to original report JSON
        labeling_data: List of labeled file records
        output_path: Path to save merged report

    Returns:
        Statistics about the merge
    """
    print(f"Loading report from: {report_path}")
    with open(report_path, 'r') as f:
        report = json.load(f)

    results = report.get('results', [])

    # Build set of existing sources to avoid duplicates
    existing_sources = set(r.get('source', '') for r in results)
    existing_filenames = set(Path(r.get('source', '')).name for r in results if r.get('source'))

    stats = {
        'original_count': len(results),
        'labeling_records': len(labeling_data),
        'added': 0,
        'skipped_duplicate_path': 0,
        'skipped_duplicate_filename': 0,
        'categories_added': {}
    }

    # Add labeling session records that aren't already in the report
    for record in labeling_data:
        source = record.get('source', '')
        filename = Path(source).name if source else ''

        if source in existing_sources:
            stats['skipped_duplicate_path'] += 1
            continue

        if filename in existing_filenames:
            stats['skipped_duplicate_filename'] += 1
            continue

        # Add the record
        results.append(record)
        existing_sources.add(source)
        existing_filenames.add(filename)
        stats['added'] += 1

        # Track category distribution
        cat_key = f"{record['category']}/{record['subcategory']}"
        stats['categories_added'][cat_key] = stats['categories_added'].get(cat_key, 0) + 1

    # Update report metadata
    report['results'] = results
    report['total_files'] = len(results)
    report['merge_timestamp'] = datetime.now().isoformat()
    report['labeling_records_added'] = stats['added']

    # Save merged report
    print(f"Saving merged report to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Merge labeled data from database into report')
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
                        help='Session ID to exclude (main ML run)')

    args = parser.parse_args()

    # Generate output path with timestamp
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f'results/content_organization_report_merged_{timestamp}.json'

    print("=" * 60)
    print("MERGE LABELED DATA INTO ORGANIZATION REPORT")
    print("=" * 60)

    # Get labeling session data
    print("\nFetching labeled data from database...")
    labeling_data = get_labeling_session_data(args.database, args.ml_session)
    print(f"Found {len(labeling_data)} labeled records from labeling sessions")

    # Merge the data
    print("\nMerging data...")
    stats = merge_reports(args.report, labeling_data, output_path)

    # Print summary
    print("\n" + "-" * 40)
    print("MERGE SUMMARY")
    print("-" * 40)
    print(f"Original report files: {stats['original_count']:,}")
    print(f"Labeling session records: {stats['labeling_records']:,}")
    print(f"Records added: {stats['added']:,}")
    print(f"Skipped (duplicate path): {stats['skipped_duplicate_path']:,}")
    print(f"Skipped (duplicate filename): {stats['skipped_duplicate_filename']:,}")
    print(f"Final total files: {stats['original_count'] + stats['added']:,}")

    if stats['categories_added']:
        print("\n" + "-" * 40)
        print("CATEGORIES ADDED")
        print("-" * 40)
        for cat, count in sorted(stats['categories_added'].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} files")

    print("\n" + "-" * 40)
    print(f"Merged report saved to: {output_path}")
    print("=" * 60)

    return output_path


if __name__ == "__main__":
    main()
