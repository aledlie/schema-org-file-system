#!/usr/bin/env python3
"""
Intelligent File Organizer using Schema.org metadata system.

Organizes files from Desktop and Downloads into ~/Documents
with a structured hierarchy based on file types and metadata.
"""

import sys
import os
import shutil
import mimetypes
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from urllib.parse import quote

# Add src directory to path
sys.path.insert(0, '/Users/alyshialedlie/schema-org-file-system/src')

from generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from base import PropertyType
from enrichment import MetadataEnricher
from validator import SchemaValidator
from integration import SchemaRegistry


class FileOrganizer:
    """Organize files using Schema.org metadata."""

    def __init__(self, base_path: str = None):
        """Initialize the organizer."""
        self.base_path = Path(base_path or os.path.expanduser("~/Documents"))
        self.enricher = MetadataEnricher()
        self.validator = SchemaValidator()
        self.registry = SchemaRegistry()
        self.stats = defaultdict(int)

        # Define organization structure
        self.category_paths = {
            'images': {
                'screenshots': 'Images/Screenshots',
                'photos': 'Images/Photos',
                'graphics': 'Images/Graphics',
                'other': 'Images/Other'
            },
            'documents': {
                'pdf': 'Documents/PDFs',
                'word': 'Documents/Word',
                'spreadsheets': 'Documents/Spreadsheets',
                'presentations': 'Documents/Presentations',
                'text': 'Documents/Text',
                'markdown': 'Documents/Markdown',
                'other': 'Documents/Other'
            },
            'media': {
                'videos': 'Media/Videos',
                'audio': 'Media/Audio',
                'music': 'Media/Music',
                'other': 'Media/Other'
            },
            'archives': {
                'zip': 'Archives/Compressed',
                'other': 'Archives/Other'
            },
            'software': {
                'installers': 'Software/Installers',
                'packages': 'Software/Packages',
                'other': 'Software/Other'
            },
            'code': {
                'python': 'Code/Python',
                'javascript': 'Code/JavaScript',
                'other': 'Code/Other'
            },
            'data': {
                'json': 'Data/JSON',
                'csv': 'Data/CSV',
                'databases': 'Data/Databases',
                'other': 'Data/Other'
            },
            'research': {
                'papers': 'Research/Papers',
                'notes': 'Research/Notes',
                'other': 'Research/Other'
            },
            'other': 'Other'
        }

    def detect_file_category(self, file_path: Path) -> Tuple[str, str, str]:
        """
        Detect file category and subcategory.

        Returns:
            Tuple of (main_category, subcategory, schema_type)
        """
        mime_type = self.enricher.detect_mime_type(str(file_path))
        file_name = file_path.name.lower()
        file_ext = file_path.suffix.lower()

        # Images
        if mime_type and mime_type.startswith('image/'):
            if 'screenshot' in file_name or file_name.startswith('screen'):
                return ('images', 'screenshots', 'ImageObject')
            elif file_ext in ['.jpg', '.jpeg', '.heic']:
                return ('images', 'photos', 'Photograph')
            else:
                return ('images', 'graphics', 'ImageObject')

        # Documents
        elif mime_type in ['application/pdf']:
            # Check if in research directory
            if 'research' in str(file_path.parent).lower():
                return ('research', 'papers', 'ScholarlyArticle')
            return ('documents', 'pdf', 'DigitalDocument')

        elif mime_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                           'application/msword']:
            return ('documents', 'word', 'DigitalDocument')

        elif mime_type in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                           'application/vnd.ms-excel']:
            return ('documents', 'spreadsheets', 'DigitalDocument')

        elif mime_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation',
                           'application/vnd.ms-powerpoint']:
            return ('documents', 'presentations', 'DigitalDocument')

        elif file_ext == '.md':
            if 'research' in str(file_path.parent).lower():
                return ('research', 'notes', 'Article')
            return ('documents', 'markdown', 'Article')

        elif mime_type and mime_type.startswith('text/'):
            return ('documents', 'text', 'DigitalDocument')

        # Media
        elif mime_type and mime_type.startswith('video/'):
            return ('media', 'videos', 'VideoObject')

        elif mime_type and mime_type.startswith('audio/'):
            if 'music' in file_name or file_ext in ['.mp3', '.m4a', '.flac']:
                return ('media', 'music', 'MusicRecording')
            return ('media', 'audio', 'AudioObject')

        # Archives
        elif mime_type in ['application/zip', 'application/x-zip-compressed'] or file_ext == '.zip':
            return ('archives', 'zip', 'DigitalDocument')

        elif file_ext in ['.tar', '.gz', '.bz2', '.7z', '.rar']:
            return ('archives', 'other', 'DigitalDocument')

        # Software
        elif file_ext in ['.dmg', '.pkg', '.exe', '.msi', '.deb', '.rpm']:
            return ('software', 'installers', 'SoftwareApplication')

        # Code
        elif file_ext == '.py':
            return ('code', 'python', 'SoftwareSourceCode')

        elif file_ext in ['.js', '.ts', '.jsx', '.tsx']:
            return ('code', 'javascript', 'SoftwareSourceCode')

        # Data
        elif file_ext == '.json':
            return ('data', 'json', 'Dataset')

        elif file_ext == '.csv':
            return ('data', 'csv', 'Dataset')

        elif file_ext in ['.db', '.sqlite', '.sqlite3']:
            return ('data', 'databases', 'Dataset')

        # Default
        return ('other', 'other', 'CreativeWork')

    def generate_schema(self, file_path: Path, schema_type: str) -> Dict:
        """Generate Schema.org metadata for a file."""
        # Get file stats
        stats = file_path.stat()
        mime_type = self.enricher.detect_mime_type(str(file_path))
        # Use a simple HTTP URL placeholder that passes validation
        # We'll store the actual file path in a custom property
        file_url = f"https://localhost/files/{quote(file_path.name)}"
        actual_path = str(file_path.absolute())

        # Select appropriate generator and set basic info based on type
        if schema_type in ['ImageObject', 'Photograph']:
            generator = ImageGenerator(schema_type)
            generator.set_basic_info(
                name=file_path.name,
                content_url=file_url,
                encoding_format=mime_type or 'image/png',
                description=f"{schema_type}: {file_path.name}"
            )

        elif schema_type == 'VideoObject':
            generator = VideoGenerator()
            generator.set_basic_info(
                name=file_path.name,
                content_url=file_url,
                upload_date=datetime.fromtimestamp(stats.st_ctime),
                description=f"{schema_type}: {file_path.name}"
            )

        elif schema_type in ['AudioObject', 'MusicRecording']:
            generator = AudioGenerator(schema_type)
            generator.set_basic_info(
                name=file_path.name,
                content_url=file_url,
                description=f"{schema_type}: {file_path.name}"
            )

        elif schema_type == 'SoftwareSourceCode':
            generator = CodeGenerator()
            # CodeGenerator uses different method signature
            generator.set_basic_info(
                name=file_path.name,
                programming_language=self.detect_programming_language(file_path),
                description=f"{schema_type}: {file_path.name}"
            )
            generator.set_property("url", file_url, PropertyType.URL)

        elif schema_type == 'Dataset':
            generator = DatasetGenerator()
            generator.set_basic_info(
                name=file_path.name,
                description=f"{schema_type}: {file_path.name}",
                url=file_url
            )

        elif schema_type in ['DigitalDocument', 'Article', 'ScholarlyArticle']:
            generator = DocumentGenerator(schema_type)
            generator.set_basic_info(
                name=file_path.name,
                description=f"{schema_type}: {file_path.name}"
            )
            generator.set_file_info(
                encoding_format=mime_type or 'application/octet-stream',
                url=file_url,
                content_size=stats.st_size
            )

        else:
            generator = DocumentGenerator()
            generator.set_basic_info(
                name=file_path.name,
                description=f"File: {file_path.name}"
            )
            generator.set_file_info(
                encoding_format=mime_type or 'application/octet-stream',
                url=file_url,
                content_size=stats.st_size
            )

        # Set dates for all types
        try:
            generator.set_dates(
                created=datetime.fromtimestamp(stats.st_ctime),
                modified=datetime.fromtimestamp(stats.st_mtime)
            )
        except Exception:
            pass  # Some generators may not support set_dates

        # Add image-specific metadata
        if isinstance(generator, ImageGenerator):
            try:
                # Try to get image dimensions if PIL is available
                from PIL import Image
                with Image.open(file_path) as img:
                    generator.set_dimensions(img.width, img.height)
                    # Try to get EXIF data
                    exif = img.getexif()
                    if exif:
                        exif_dict = {}
                        for tag_id, value in exif.items():
                            if isinstance(value, (str, int, float)):
                                exif_dict[str(tag_id)] = value
                        if exif_dict:
                            generator.set_property('exifData', exif_dict)
            except ImportError:
                pass  # PIL not available
            except Exception:
                pass  # Can't read image

        # Add the actual file path as a custom property
        try:
            generator.set_property('filePath', actual_path, PropertyType.TEXT)
        except Exception:
            pass

        return generator.to_dict()

    def detect_programming_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.jsx': 'JavaScript',
            '.tsx': 'TypeScript',
            '.java': 'Java',
            '.cpp': 'C++',
            '.c': 'C',
            '.go': 'Go',
            '.rs': 'Rust',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
        }
        return ext_map.get(file_path.suffix.lower(), 'Unknown')

    def get_destination_path(self, file_path: Path, category: str, subcategory: str) -> Path:
        """Get the destination path for a file."""
        if category in self.category_paths:
            if isinstance(self.category_paths[category], dict):
                if subcategory in self.category_paths[category]:
                    relative_path = self.category_paths[category][subcategory]
                else:
                    relative_path = self.category_paths[category].get('other', 'Other')
            else:
                relative_path = self.category_paths[category]
        else:
            relative_path = 'Other'

        dest_dir = self.base_path / relative_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle duplicate filenames
        dest_path = dest_dir / file_path.name
        if dest_path.exists() and dest_path != file_path:
            # Add timestamp to filename
            stem = file_path.stem
            suffix = file_path.suffix
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = dest_dir / f"{stem}_{timestamp}{suffix}"

        return dest_path

    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_files = {'.DS_Store', '.localized', 'Thumbs.db', 'desktop.ini'}
        skip_dirs = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}

        # Skip hidden files (except specific ones we want to keep)
        if file_path.name.startswith('.') and file_path.name not in {'.gitignore', '.env.example'}:
            return True

        # Skip system files
        if file_path.name in skip_files:
            return True

        # Skip if in skip directories
        if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
            return True

        return False

    def organize_file(self, file_path: Path, dry_run: bool = False) -> Dict:
        """
        Organize a single file.

        Args:
            file_path: Path to the file
            dry_run: If True, don't actually move files

        Returns:
            Dictionary with organization details
        """
        result = {
            'source': str(file_path),
            'status': 'skipped',
            'reason': None,
            'destination': None,
            'schema': None
        }

        # Skip if should be skipped
        if self.should_skip_file(file_path):
            result['reason'] = 'system_file'
            self.stats['skipped'] += 1
            return result

        # Skip if not a file
        if not file_path.is_file():
            result['reason'] = 'not_file'
            self.stats['skipped'] += 1
            return result

        try:
            # Detect category
            category, subcategory, schema_type = self.detect_file_category(file_path)

            # Generate schema
            schema = self.generate_schema(file_path, schema_type)

            # Validate schema
            validation_report = self.validator.validate(schema)

            # Get destination path
            dest_path = self.get_destination_path(file_path, category, subcategory)

            # Skip if already in the right place
            if file_path == dest_path:
                result['status'] = 'already_organized'
                result['destination'] = str(dest_path)
                result['schema'] = schema
                self.stats['already_organized'] += 1
                return result

            # Move file if not dry run
            if not dry_run:
                shutil.move(str(file_path), str(dest_path))

                # Register schema with new path
                schema['url'] = f"file://{dest_path.absolute()}"
                self.registry.register(
                    str(dest_path),
                    schema,
                    metadata={
                        'category': category,
                        'subcategory': subcategory,
                        'organized_date': datetime.now().isoformat(),
                        'is_valid': validation_report.is_valid()
                    }
                )

            result['status'] = 'organized' if not dry_run else 'would_organize'
            result['destination'] = str(dest_path)
            result['schema'] = schema
            result['category'] = category
            result['subcategory'] = subcategory
            result['is_valid'] = validation_report.is_valid()

            self.stats['organized'] += 1
            self.stats[f'{category}_{subcategory}'] += 1

        except Exception as e:
            result['status'] = 'error'
            result['reason'] = str(e)
            self.stats['errors'] += 1

        return result

    def scan_directory(self, directory: Path) -> List[Path]:
        """Scan directory for files to organize."""
        files = []

        try:
            for item in directory.rglob('*'):
                if item.is_file() and not self.should_skip_file(item):
                    files.append(item)
        except PermissionError:
            print(f"Permission denied: {directory}")

        return files

    def organize_directories(self, source_dirs: List[str], dry_run: bool = False) -> Dict:
        """
        Organize files from multiple source directories.

        Args:
            source_dirs: List of directory paths to organize
            dry_run: If True, simulate organization without moving files

        Returns:
            Dictionary with organization results
        """
        results = []

        print(f"\n{'='*60}")
        print(f"File Organization {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}\n")

        # Scan all directories
        all_files = []
        for source_dir in source_dirs:
            source_path = Path(source_dir).expanduser()
            if source_path.exists():
                print(f"Scanning: {source_path}")
                files = self.scan_directory(source_path)
                all_files.extend(files)
                print(f"  Found {len(files)} files")
            else:
                print(f"Directory not found: {source_path}")

        print(f"\nTotal files to process: {len(all_files)}\n")

        # Organize each file
        for i, file_path in enumerate(all_files, 1):
            print(f"[{i}/{len(all_files)}] Processing: {file_path.name}")
            result = self.organize_file(file_path, dry_run=dry_run)
            results.append(result)

            if result['status'] == 'organized' or result['status'] == 'would_organize':
                print(f"  → {result['destination']}")
            elif result['status'] == 'error':
                print(f"  ✗ Error: {result['reason']}")

        # Generate summary
        summary = {
            'total_files': len(all_files),
            'organized': self.stats['organized'],
            'already_organized': self.stats['already_organized'],
            'skipped': self.stats['skipped'],
            'errors': self.stats['errors'],
            'dry_run': dry_run,
            'results': results,
            'registry_stats': self.registry.get_statistics() if not dry_run else None
        }

        return summary

    def print_summary(self, summary: Dict):
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

        for category, count in sorted(category_stats.items()):
            print(f"{category.capitalize()}: {count} files")

        if summary.get('registry_stats'):
            print(f"\n{'='*60}")
            print("Schema Registry")
            print(f"{'='*60}\n")
            stats = summary['registry_stats']
            print(f"Total schemas: {stats['total_schemas']}")
            print(f"Types: {', '.join(stats['types'])}")

    def save_report(self, summary: Dict, output_path: str = None):
        """Save detailed organization report to JSON."""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/organization_report_{timestamp}.json"

        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"\nDetailed report saved to: {output_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Organize files using Schema.org metadata'
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
        '--sources',
        nargs='+',
        default=['~/Desktop', '~/Downloads'],
        help='Source directories to organize (default: ~/Desktop ~/Downloads)'
    )
    parser.add_argument(
        '--report',
        help='Path to save detailed JSON report'
    )

    args = parser.parse_args()

    # Create organizer
    organizer = FileOrganizer(base_path=args.base_path)

    # Organize directories
    summary = organizer.organize_directories(
        source_dirs=args.sources,
        dry_run=args.dry_run
    )

    # Print summary
    organizer.print_summary(summary)

    # Save report if requested
    if args.report or not args.dry_run:
        organizer.save_report(summary, args.report)


if __name__ == '__main__':
    main()
