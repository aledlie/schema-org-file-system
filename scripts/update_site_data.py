#!/usr/bin/env python3
"""
Update _site data files from the latest organization report.

Generates:
- metadata.json: File metadata for the metadata viewer
- Updates timeline_data.json with latest session
- Updates index.html stats
"""

import json
from datetime import datetime
from pathlib import Path
from collections import Counter


def find_latest_report(results_dir: Path) -> Path:
    """Find the most recent labeled/merged organization report."""
    # Look for labeled reports first, then merged, then regular
    patterns = [
        "content_organization_report_labeled_*.json",
        "content_organization_report_merged_*.json",
        "content_organization_report_*.json"
    ]

    for pattern in patterns:
        files = sorted(results_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]

    raise FileNotFoundError("No organization report found")


def extract_metadata(report_path: Path) -> list[dict]:
    """Extract metadata array from organization report."""
    print(f"Loading report: {report_path}")

    with open(report_path) as f:
        report = json.load(f)

    results = report.get('results', [])

    # Transform results to metadata format
    metadata = []
    for r in results:
        item = {
            'source': r.get('source'),
            'destination': r.get('destination'),
            'status': r.get('status'),
            'category': r.get('category'),
            'subcategory': r.get('subcategory'),
            'schema': r.get('schema', {}),
            'extracted_text_length': r.get('extracted_text_length', 0),
            'company_name': r.get('company_name'),
            'image_metadata': r.get('image_metadata', {})
        }
        metadata.append(item)

    return metadata


def calculate_stats(metadata: list[dict]) -> dict:
    """Calculate statistics from metadata."""
    total = len(metadata)
    organized = sum(1 for m in metadata if m.get('status') == 'organized')
    already = sum(1 for m in metadata if m.get('status') == 'already_organized')

    categories = Counter(m.get('category') for m in metadata if m.get('category'))

    return {
        'total_files': total,
        'organized': organized,
        'already_organized': already,
        'success_rate': round(((organized + already) / total * 100) if total > 0 else 0, 1),
        'category_count': len(categories),
        'top_categories': categories.most_common(5)
    }


def update_index_html(site_dir: Path, stats: dict):
    """Update the landing page with latest stats."""
    index_path = site_dir / "index.html"

    if not index_path.exists():
        print(f"Warning: {index_path} not found, skipping")
        return

    content = index_path.read_text()

    # Update stats values
    replacements = [
        # Files Processed
        (r'<div class="stat-value">[\d,]+</div>\s*<div class="stat-label">Files Processed</div>',
         f'<div class="stat-value">{stats["total_files"]:,}</div>\n                <div class="stat-label">Files Processed</div>'),
        # Success Rate
        (r'<div class="stat-value">[\d.]+%</div>\s*<div class="stat-label">Success Rate</div>',
         f'<div class="stat-value">{stats["success_rate"]}%</div>\n                <div class="stat-label">Success Rate</div>'),
        # Categories
        (r'<div class="stat-value">\d+</div>\s*<div class="stat-label">Categories</div>',
         f'<div class="stat-value">{stats["category_count"]}</div>\n                <div class="stat-label">Categories</div>'),
        # Last Updated date
        (r'Last Updated: \w+ \d+, \d+',
         f'Last Updated: {datetime.now().strftime("%B %d, %Y")}'),
    ]

    import re
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    index_path.write_text(content)
    print(f"Updated {index_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Update _site data from latest report')
    parser.add_argument('--results-dir', '-r',
                        default='results',
                        help='Results directory')
    parser.add_argument('--site-dir', '-s',
                        default='_site',
                        help='Site directory')
    parser.add_argument('--report',
                        help='Specific report file to use')

    args = parser.parse_args()

    base_dir = Path(__file__).parent.parent
    results_dir = base_dir / args.results_dir
    site_dir = base_dir / args.site_dir

    print("=" * 60)
    print("UPDATE SITE DATA")
    print("=" * 60)

    # Find latest report
    if args.report:
        report_path = Path(args.report)
    else:
        report_path = find_latest_report(results_dir)

    print(f"\nUsing report: {report_path.name}")

    # Extract metadata
    metadata = extract_metadata(report_path)
    print(f"Extracted {len(metadata):,} file records")

    # Calculate stats
    stats = calculate_stats(metadata)
    print(f"\nStats:")
    print(f"  Total files: {stats['total_files']:,}")
    print(f"  Success rate: {stats['success_rate']}%")
    print(f"  Categories: {stats['category_count']}")

    # Save metadata.json
    metadata_path = site_dir / "metadata.json"
    print(f"\nSaving {metadata_path}...")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f)
    print(f"  Size: {metadata_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Update index.html
    print("\nUpdating index.html...")
    update_index_html(site_dir, stats)

    # Regenerate timeline data
    print("\nRegenerating timeline data...")
    import subprocess
    result = subprocess.run(
        ['python3', 'scripts/generate_timeline_data.py'],
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("  Timeline data regenerated")
    else:
        print(f"  Warning: {result.stderr}")

    print("\n" + "=" * 60)
    print("SITE DATA UPDATED")
    print("=" * 60)
    print(f"  metadata.json: {len(metadata):,} files")
    print(f"  index.html: Stats updated")
    print(f"  timeline_data.json: Regenerated")


if __name__ == "__main__":
    main()
