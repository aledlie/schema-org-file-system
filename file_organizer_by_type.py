#!/usr/bin/env python3
"""
Simple file organizer based on file extensions and naming patterns.
Organizes files by type without OCR.
"""

import os
import shutil
from pathlib import Path
from collections import defaultdict
from datetime import datetime


class FileTypeOrganizer:
    """Organize files based on file type and naming patterns."""

    def __init__(self, base_path: str = None):
        """Initialize the organizer."""
        self.base_path = Path(base_path or os.path.expanduser("~/Documents"))
        self.stats = defaultdict(int)

        # File type to category mapping
        self.type_mapping = {
            # Images
            'Images/Photos': ['.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp', '.webp', '.svg'],

            # Documents
            'Documents/PDFs': ['.pdf'],
            'Documents/Word': ['.doc', '.docx'],
            'Documents/Excel': ['.xls', '.xlsx', '.csv'],
            'Documents/PowerPoint': ['.ppt', '.pptx'],
            'Documents/Text': ['.txt', '.md', '.rtf'],

            # Code
            'Code/Python': ['.py'],
            'Code/JavaScript': ['.js', '.jsx', '.mjs'],
            'Code/TypeScript': ['.ts', '.tsx'],
            'Code/Shell': ['.sh', '.bash', '.zsh'],
            'Code/Web': ['.html', '.css', '.scss', '.sass'],

            # Data/Config
            'Data/YAML': ['.yaml', '.yml'],
            'Data/JSON': ['.json'],
            'Data/XML': ['.xml'],
            'Data/Config': ['.conf', '.config', '.ini', '.env', '.toml'],

            # Media
            'Media/Audio': ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'],
            'Media/Video': ['.mp4', '.mov', '.avi', '.mkv', '.webm'],

            # Archives
            'Archives': ['.zip', '.tar', '.gz', '.rar', '.7z', '.bz2'],

            # Fonts
            'Fonts': ['.ttf', '.otf', '.woff', '.woff2'],

            # Other
            'Other/Executables': ['.exe', '.app', '.pkg', '.dmg'],
            'Other/Misc': ['.noe', '.tpl', '.lark', '.proto', '.rst'],
        }

    def get_category_for_file(self, file_path: Path) -> str:
        """Determine category based on file extension."""
        ext = file_path.suffix.lower()
        name_lower = file_path.name.lower()

        # Check for special naming patterns BEFORE general type mapping
        # Screenshots - check first so they don't get categorized as generic images
        if name_lower.startswith('screenshot'):
            return 'Images/Photos/Screenshots'

        # Game assets (lots of numbered/timestamped files)
        if any(pattern in name_lower for pattern in ['frame', 'item', 'segment', 'wing', 'arm', 'leg', 'head', 'torso']):
            return 'Images/Photos/GameAssets'

        # Check file type mappings
        for category, extensions in self.type_mapping.items():
            if ext in extensions:
                return category

        # Timezone files
        if file_path.suffix == '' and len(file_path.name.split('_')) == 1:
            # Could be timezone file
            return 'Data/Timezones'

        return 'Uncategorized'

    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_files = {'.DS_Store', '.localized', 'Thumbs.db', 'desktop.ini'}
        skip_dirs = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}

        if file_path.name.startswith('.') and file_path.name not in {'.gitignore', '.env.example'}:
            return True

        if file_path.name in skip_files:
            return True

        if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
            return True

        return False

    def organize_file(self, file_path: Path, dry_run: bool = False) -> dict:
        """Organize a single file based on type."""
        result = {
            'source': str(file_path),
            'status': 'skipped',
            'destination': None,
            'category': None
        }

        if self.should_skip_file(file_path):
            self.stats['skipped'] += 1
            return result

        if not file_path.is_file():
            self.stats['skipped'] += 1
            return result

        try:
            # Get category
            category = self.get_category_for_file(file_path)
            result['category'] = category

            # Create destination path
            dest_dir = self.base_path / category
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Handle duplicate filenames
            dest_path = dest_dir / file_path.name
            if dest_path.exists() and dest_path != file_path:
                stem = file_path.stem
                suffix = file_path.suffix
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_path = dest_dir / f"{stem}_{timestamp}{suffix}"

            # Skip if already in right place
            if file_path.parent == dest_dir:
                result['status'] = 'already_organized'
                result['destination'] = str(dest_path)
                self.stats['already_organized'] += 1
                return result

            # Move file if not dry run
            if not dry_run:
                shutil.move(str(file_path), str(dest_path))
                result['status'] = 'organized'
            else:
                result['status'] = 'would_organize'

            result['destination'] = str(dest_path)
            self.stats['organized'] += 1
            self.stats[f'category_{category}'] += 1

        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            self.stats['errors'] += 1
            print(f"  Error: {e}")

        return result

    def organize_directory(self, source_dir: str, dry_run: bool = False) -> dict:
        """Organize files from source directory."""
        results = []
        source_path = Path(source_dir).expanduser()

        print(f"\n{'='*60}")
        print(f"File Type Organization {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}\n")
        print(f"Source: {source_path}")
        print(f"Base: {self.base_path}\n")

        # Collect all files
        all_files = []
        for item in source_path.rglob('*'):
            if item.is_file() and not self.should_skip_file(item):
                all_files.append(item)

        print(f"Total files to process: {len(all_files)}\n")

        # Process each file
        for i, file_path in enumerate(all_files, 1):
            if i % 100 == 0:
                print(f"[{i}/{len(all_files)}] Processing...")

            result = self.organize_file(file_path, dry_run=dry_run)
            results.append(result)

        # Generate summary
        summary = {
            'total_files': len(all_files),
            'organized': self.stats['organized'],
            'already_organized': self.stats['already_organized'],
            'skipped': self.stats['skipped'],
            'errors': self.stats['errors'],
            'dry_run': dry_run,
            'results': results
        }

        return summary

    def print_summary(self, summary: dict):
        """Print organization summary."""
        print(f"\n{'='*60}")
        print("Organization Summary")
        print(f"{'='*60}\n")

        print(f"Total files processed: {summary['total_files']}")
        print(f"Successfully organized: {summary['organized']}")
        print(f"Already organized: {summary['already_organized']}")
        print(f"Skipped: {summary['skipped']}")
        print(f"Errors: {summary['errors']}")

        if summary['dry_run']:
            print("\n⚠️  This was a DRY RUN - no files were moved")

        # Category breakdown
        print(f"\n{'='*60}")
        print("Category Breakdown")
        print(f"{'='*60}\n")

        category_stats = defaultdict(int)
        for result in summary['results']:
            if result.get('category'):
                category_stats[result['category']] += 1

        for category, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"{category}: {count} files")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Organize files by type based on extensions'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate organization without moving files'
    )
    parser.add_argument(
        '--base-path',
        default='~/Documents',
        help='Base path for organized files (default: ~/Documents)'
    )
    parser.add_argument(
        '--source',
        default='~/Documents/Uncategorized',
        help='Source directory to organize (default: ~/Documents/Uncategorized)'
    )

    args = parser.parse_args()

    # Create organizer
    organizer = FileTypeOrganizer(base_path=args.base_path)

    # Organize directory
    summary = organizer.organize_directory(
        source_dir=args.source,
        dry_run=args.dry_run
    )

    # Print summary
    organizer.print_summary(summary)


if __name__ == '__main__':
    main()
