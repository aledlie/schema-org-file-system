#!/usr/bin/env python3
"""
Analyze organization report to extract and summarize detected people and companies.
"""

import json
from collections import defaultdict
from pathlib import Path

def analyze_report(report_path: str):
    """Analyze the organization report for people and company names."""

    with open(report_path, 'r') as f:
        data = json.load(f)

    # Track unique people and companies with file references
    people_to_files = defaultdict(list)
    companies_to_files = defaultdict(list)

    # Track files by category
    files_with_people = []
    files_with_companies = []

    # Analyze each file
    for result in data['results']:
        filename = Path(result['source']).name

        # Extract people names
        if result.get('people_names'):
            for person in result['people_names']:
                people_to_files[person].append({
                    'file': filename,
                    'category': result.get('category', 'unknown'),
                    'destination': result.get('destination', '')
                })
            files_with_people.append({
                'file': filename,
                'people': result['people_names'],
                'category': result.get('category', 'unknown'),
                'destination': result.get('destination', '')
            })

        # Extract company names
        if result.get('company_name'):
            company = result['company_name']
            companies_to_files[company].append({
                'file': filename,
                'category': result.get('category', 'unknown'),
                'destination': result.get('destination', '')
            })
            files_with_companies.append({
                'file': filename,
                'company': company,
                'category': result.get('category', 'unknown'),
                'destination': result.get('destination', '')
            })

    # Generate report
    print("\n" + "="*60)
    print("PEOPLE & COMPANY NAME DETECTION REPORT")
    print("="*60)

    print(f"\nTotal files processed: {data['total_files']}")
    print(f"Files with detected people: {len(files_with_people)}")
    print(f"Files with detected companies: {len(files_with_companies)}")
    print(f"Unique people detected: {len(people_to_files)}")
    print(f"Unique companies detected: {len(companies_to_files)}")

    # People detection summary
    print("\n" + "="*60)
    print("DETECTED PEOPLE (Alphabetical)")
    print("="*60)

    for person in sorted(people_to_files.keys()):
        files = people_to_files[person]
        print(f"\n{person}:")
        print(f"  Found in {len(files)} file(s)")
        for file_info in files[:3]:  # Show first 3 files
            print(f"    - {file_info['file']} ({file_info['category']})")
        if len(files) > 3:
            print(f"    ... and {len(files) - 3} more")

    # Company detection summary
    print("\n" + "="*60)
    print("DETECTED COMPANIES (Alphabetical)")
    print("="*60)

    for company in sorted(companies_to_files.keys()):
        files = companies_to_files[company]
        print(f"\n{company}:")
        print(f"  Found in {len(files)} file(s)")
        for file_info in files[:3]:  # Show first 3 files
            print(f"    - {file_info['file']} ({file_info['category']})")
        if len(files) > 3:
            print(f"    ... and {len(files) - 3} more")

    # Files with most detections
    print("\n" + "="*60)
    print("FILES WITH MULTIPLE PEOPLE DETECTED")
    print("="*60)

    multi_people = [f for f in files_with_people if len(f['people']) > 1]
    multi_people.sort(key=lambda x: len(x['people']), reverse=True)

    for file_info in multi_people[:10]:  # Top 10
        print(f"\n{file_info['file']}:")
        print(f"  Category: {file_info['category']}")
        print(f"  People detected ({len(file_info['people'])}): {', '.join(file_info['people'][:5])}")
        if len(file_info['people']) > 5:
            print(f"    ... and {len(file_info['people']) - 5} more")

    # Category breakdown
    print("\n" + "="*60)
    print("DETECTION BY CATEGORY")
    print("="*60)

    category_stats = defaultdict(lambda: {'people': 0, 'companies': 0})

    for file_info in files_with_people:
        category_stats[file_info['category']]['people'] += 1

    for file_info in files_with_companies:
        category_stats[file_info['category']]['companies'] += 1

    for category in sorted(category_stats.keys()):
        stats = category_stats[category]
        print(f"\n{category.capitalize()}:")
        print(f"  Files with people: {stats['people']}")
        print(f"  Files with companies: {stats['companies']}")

if __name__ == '__main__':
    report_path = 'results/downloads_organization_report.json'
    analyze_report(report_path)
