#!/usr/bin/env python3
"""
File Organization by Name and Path
Organizes files based purely on filename patterns and filepath information.
No content analysis, OCR, or AI vision processing.
"""

import os
import sys
import re
import shutil
import argparse
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, List, Optional, Tuple


class FileNameOrganizer:
    """Organize files based on filename and path patterns only."""

    def __init__(self, base_path: str, dry_run: bool = False):
        self.base_path = Path(base_path).expanduser()
        self.dry_run = dry_run
        self.stats = {
            'total_files': 0,
            'moved_files': 0,
            'skipped_files': 0,
            'errors': 0,
            'by_category': {}
        }

        # Extension mappings
        self.extension_map = {
            # Images
            'images': {
                'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'ico',
                'svg', 'heic', 'heif', 'tiff', 'tif', 'raw'
            },
            # Videos
            'videos': {
                'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm',
                'm4v', 'mpg', 'mpeg', '3gp'
            },
            # Audio
            'audio': {
                'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'wma',
                'opus', 'aiff', 'ape'
            },
            # Documents
            'documents': {
                'pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'pages',
                'tex', 'md', 'markdown'
            },
            # Spreadsheets
            'spreadsheets': {
                'xls', 'xlsx', 'csv', 'tsv', 'ods', 'numbers'
            },
            # Presentations
            'presentations': {
                'ppt', 'pptx', 'key', 'odp'
            },
            # Code
            'code': {
                'py', 'js', 'ts', 'jsx', 'tsx', 'java', 'c', 'cpp',
                'h', 'hpp', 'cs', 'go', 'rs', 'rb', 'php', 'swift',
                'kt', 'scala', 'r', 'sh', 'bash', 'zsh', 'fish',
                'html', 'css', 'scss', 'sass', 'less'
            },
            # Data
            'data': {
                'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg',
                'conf', 'config', 'plist', 'sql', 'db', 'sqlite'
            },
            # Archives
            'archives': {
                'zip', 'tar', 'gz', 'bz2', 'xz', 'rar', '7z', 'dmg',
                'pkg', 'deb', 'rpm', 'iso'
            },
            # Certificates & Keys
            'certificates': {
                'pem', 'key', 'crt', 'cer', 'p12', 'pfx', 'pub'
            },
            # Game files
            'game_files': {
                'sav', 'save', 'dat'
            },
            # Design
            'design': {
                'ai', 'psd', 'sketch', 'fig', 'xd', 'afdesign',
                'afphoto', 'afpub'
            },
            # 3D
            '3d': {
                'blend', 'obj', 'fbx', 'dae', 'stl', '3ds', 'max',
                'c4d', 'ma', 'mb'
            }
        }

        # Filename pattern categories
        self.filename_patterns = {
            # Artifact/build files (to be trashed)
            'artifacts_trash': [
                r'\.pyc$',
                r'\.pyo$',
                r'\.pyd$',
                r'__pycache__',
                r'\.egg-info$',
                r'\.dist-info$',
                r'\.so$',
                r'\.dylib$',
                r'\.dll$',
                r'\.o$',
                r'\.a$',
                r'\.lib$',
                r'\.node$',
                r'\.bcmap$',
                r'\.noe$',
                r'\.pfb$',
                r'\.otf$',
                r'\.ttf$',
                r'\.woff$',
                r'\.woff2$',
                r'\.eot$',
                r'\.proto$',
                r'\.def$',
                r'\.lark$',
                r'\.icns$',
                r'\.pack$',
                r'\.rev$',
                r'\.sample$',
                r'^\.DS_Store$',
                r'^\.npmignore',
                r'^\.gitignore',
                r'^\.coveragerc',
                r'^\.jshintrc',
                r'^\.babelrc',
                r'^\.hgeol$',
                r'^\.flake8$',
                r'\.cjs$',
                r'\.mjs$',
                r'\.d\.ts$',
                r'\.d\.cts$',
                r'\.d\.mts$',
                r'\.min\.js$',
                r'\.min\.css$',
                r'\.umd\.js$',
                r'\.esm\.js$',
                r'\.browser\.js$',
                r'\.worker\.js$',
                r'\.webworker\.js$',
            ],
            # Technical/build files
            'technical_build': [
                r'^tsserver$',
                r'^tsc$',
                r'^tsx$',
                r'^esbuild$',
                r'^node-which$',
                r'^mammoth$',
                r'^pdf-parse$',
                r'^\.eslintrc',
                r'^\.nycrc',
                r'^\.editorconfig',
                r'^\.travis\.yml$',
                r'^makefile$',
                r'\.tpl$',
            ],
            # LICENSE files
            'license_files': [
                r'^LICENSE',
                r'^license$',
            ],
            # README and documentation files
            'readme_files': [
                r'^README',
                r'^readme',
                r'^CHANGELOG',
                r'^changelog',
                r'^HISTORY',
                r'^History',
                r'^SECURITY\.md$',
                r'^CONTRIBUTING',
                r'^AUTHORS',
                r'^CONTRIBUTORS',
            ],
            # Technical documentation and templates
            'technical_docs': [
                r'^ISSUE_TEMPLATE',
                r'^PULL_REQUEST_TEMPLATE',
                r'^Bug_report',
                r'exception.*\.txt$',
                r'settings\.txt$',
                r'credits\.txt$',
            ],
            # Log files
            'log_files': [
                r'\.log$',
                r'^.*\.log\.',
            ],
            # AI-Generated images
            'ai_generated': [
                r'^ChatGPT Image',
                r'^DALL-E',
                r'^Midjourney',
                r'^Stable Diffusion',
                r'^AI Generated',
            ],
            # Screenshots
            'screenshots': [
                r'^screenshot[_\s]',
                r'^screen[_\s]?shot',
                r'^capture[_\s]',
                r'^scrnshot',
                r'^Screen Shot',
            ],
            # WhatsApp images
            'whatsapp': [
                r'^WhatsApp Image',
                r'^WhatsApp Video',
                r'^WA\d+',
            ],
            # Camera photos
            'camera_photos': [
                r'^IMG_\d+',
                r'^PXL_\d+',
                r'^DSC_\d+',
                r'^DCIM_\d+',
                r'^\d{8}_\d{6}',  # YYYYMMDD_HHMMSS
                r'^\d{14}',        # YYYYMMDDHHMMSS
                r'^\d{8}_[A-Za-z]+_\d{6}',  # YYYYMMDD_Location_HHMMSS
            ],
            # Social media downloads
            'social_media': [
                r'^\d+_\d+_\d+_\d+_\d+_n\.(jpg|jpeg)',  # Facebook pattern
                r'^unnamed\(\d+\)',
                r'-EDIT\.jpg$',
                r'-EDIT-EDIT',
            ],
            # Web templates
            'web_templates': [
                r'-webflow-template',
                r'-elderlycare-x-',
                r'-icon-purple-',
                r'-decoration-image-',
            ],
            # Game assets
            'game_assets': {
                'sprites': [
                    r'^\d+_f\.png$',      # Frame files
                    r'^\d+_f_\d+\.png$',
                    r'^char_[a-z]_\d+',   # Character sprites
                    r'^l_[a-z]\d+',       # Leg sprites
                    r'^c_[A-Z]{2}_',      # Compass sprites
                    r'^c_rug_',           # Rug sprites
                    r'^feet_',
                    r'^drake_',
                    r'^trap_',
                    r'^frame\d+',         # Frame files
                    r'^arm_',             # Arm sprites
                    r'^leg',              # Leg sprites
                    r'^legs_',
                    r'^torso_',           # Torso sprites
                    r'^wing_',            # Wing sprites
                    r'^head_',            # Head sprites
                    r'^tail_',            # Tail sprites
                    r'^item\d+',          # Item sprites
                    r'^grass_',           # Grass sprites
                    r'^shoulders_',       # Shoulder sprites
                ],
                'textures': [
                    r'^shadingOcclusion',
                    r'^bg_',
                    r'^texture-',
                ],
                'ui': [
                    r'^stat_',
                    r'^hp_mp_',
                    r'^book_',
                    r'^cur_',
                    r'^name_\d+',
                    r'^drop_\d+',
                    r'^medium_\d+',
                    r'^settings_',
                    r'^container_',
                ],
                'fonts': [
                    r'^cp437-',
                ],
                'items': [
                    r'^boomerang',
                    r'^cube',
                    r'^magic_hater',
                ],
            },
            # Location/timezone files
            'location_data': [
                r'^[A-Z][a-z]+_[A-Z][a-z]+$',  # Port_Moresby
                r'^[A-Z][a-z]+_\d{8}_\d{6}$',  # City_timestamp
            ],
            # Generic numbered files
            'numbered_generic': [
                r'^\d+\.png$',
                r'^\d+_\d+\.png$',
            ],
            # Logos (branding)
            'logos': [
                r'logo',
                r'-logo',
                r'_logo',
                r'logo-',
                r'logo_',
            ],
            # Icons
            'icons': [
                r'-icon-',
                r'^icon[-_]',
                r'fav\.png$',
            ],
            # Calendar/date
            'calendar': [
                r'^calendar-',
                r'-check-\d+\.svg$',
            ],
            # Medical
            'medical': [
                r'^medication-',
            ],
            # Emoji
            'emoji': [
                r'^1f\d{3}\.png$',  # Unicode emoji
            ],
        }

        # Filepath pattern categories
        self.filepath_patterns = {
            'game_assets': [
                r'/GameAssets/',
                r'/game[-_]assets/',
                r'/games?/',
            ],
            'downloads': [
                r'/Downloads/',
                r'/downloads/',
            ],
            'documents': [
                r'/Documents/',
                r'/docs?/',
            ],
            'pictures': [
                r'/Pictures/',
                r'/Photos/',
                r'/images?/',
            ],
            'desktop': [
                r'/Desktop/',
            ],
        }

    def categorize_by_extension(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """
        Categorize file by extension.
        Returns (category, subcategory) or None.
        """
        # Check for .map files specifically (source maps)
        if file_path.name.endswith('.js.map'):
            return ('Technical', 'JavaScript')
        elif file_path.name.endswith('.css.map'):
            return ('Technical', 'JavaScript')
        elif file_path.name.endswith('.ts.map'):
            return ('Technical', 'JavaScript')

        ext = file_path.suffix.lower().lstrip('.')

        for category, extensions in self.extension_map.items():
            if ext in extensions:
                # Map to destination paths
                if category == 'images':
                    return ('Media/Photos', 'Other')
                elif category == 'videos':
                    return ('Media/Videos', 'Recordings')
                elif category == 'audio':
                    return ('Media/Audio', 'Other')
                elif category == 'documents':
                    return ('Documents', 'General')
                elif category == 'spreadsheets':
                    return ('Data', 'Spreadsheets')
                elif category == 'presentations':
                    return ('Documents', 'Presentations')
                elif category == 'code':
                    return ('Technical', 'Code')
                elif category == 'data':
                    return ('Data', 'Configs')
                elif category == 'archives':
                    return ('Data', 'Archives')
                elif category == 'certificates':
                    return ('Technical', 'Certificates')
                elif category == 'game_files':
                    return ('GameAssets', 'SaveFiles')
                elif category == 'design':
                    return ('Creative', 'Design')
                elif category == '3d':
                    return ('Creative', '3D')

        return None

    def categorize_by_filename(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """
        Categorize file by filename patterns.
        Returns (category, subcategory) or None.
        """
        filename = file_path.name

        # Check artifacts/build files FIRST (highest priority - to be trashed)
        for pattern in self.filename_patterns['artifacts_trash']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('.Trash', 'BuildArtifacts')

        # Check technical/build files (high priority)
        for pattern in self.filename_patterns['technical_build']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Technical/Code', 'Other')

        # Check LICENSE files
        for pattern in self.filename_patterns['license_files']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Technical/Code', 'Other')

        # Check README and documentation files
        for pattern in self.filename_patterns['readme_files']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Technical', 'ReadMes')

        # Check log files (higher priority than technical docs)
        for pattern in self.filename_patterns['log_files']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Technical', 'Logs')

        # Check technical documentation and templates
        for pattern in self.filename_patterns['technical_docs']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Technical', 'Other')

        # Check AI-generated images (highest priority for these)
        for pattern in self.filename_patterns['ai_generated']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('AI-Generated', 'Images')

        # Check screenshots
        for pattern in self.filename_patterns['screenshots']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Media/Photos', 'Screenshots')

        # Check WhatsApp
        for pattern in self.filename_patterns['whatsapp']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Media/Photos', 'WhatsApp')

        # Check camera photos
        for pattern in self.filename_patterns['camera_photos']:
            if re.search(pattern, filename):
                return ('Media/Photos', 'Camera')

        # Check social media
        for pattern in self.filename_patterns['social_media']:
            if re.search(pattern, filename):
                return ('Media/Photos', 'Social_Media')

        # Check web templates
        for pattern in self.filename_patterns['web_templates']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Creative', 'WebTemplates')

        # Check game assets (priority order matters)
        game_patterns = self.filename_patterns['game_assets']

        # Check if image extension (for Games subdirectory in Media/Photos)
        is_image = file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']

        for pattern in game_patterns['sprites']:
            if re.search(pattern, filename):
                if is_image:
                    return ('Media/Photos', 'Games')
                return ('GameAssets', 'Sprites')

        for pattern in game_patterns['textures']:
            if re.search(pattern, filename):
                if is_image:
                    return ('Media/Photos', 'Games')
                return ('GameAssets', 'Textures')

        for pattern in game_patterns['ui']:
            if re.search(pattern, filename):
                if is_image:
                    return ('Media/Photos', 'Games')
                return ('GameAssets', 'UI')

        for pattern in game_patterns['fonts']:
            if re.search(pattern, filename):
                if is_image:
                    return ('Media/Photos', 'Games')
                return ('GameAssets', 'Fonts')

        for pattern in game_patterns['items']:
            if re.search(pattern, filename):
                if is_image:
                    return ('Media/Photos', 'Games')
                return ('GameAssets', 'Items')

        # Check logos (higher priority than icons)
        for pattern in self.filename_patterns['logos']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Creative', 'Branding')

        # Check icons
        for pattern in self.filename_patterns['icons']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Creative', 'Icons')

        # Check calendar
        for pattern in self.filename_patterns['calendar']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Creative', 'Icons')

        # Check medical
        for pattern in self.filename_patterns['medical']:
            if re.search(pattern, filename, re.IGNORECASE):
                return ('Medical', 'General')

        # Check emoji
        for pattern in self.filename_patterns['emoji']:
            if re.search(pattern, filename):
                return ('Creative', 'Emoji')

        # Check location data
        for pattern in self.filename_patterns['location_data']:
            if re.search(pattern, filename):
                return ('Data', 'LocationData')

        # Check generic numbered files (low priority)
        for pattern in self.filename_patterns['numbered_generic']:
            if re.search(pattern, filename):
                # Could be game assets
                return ('GameAssets', 'Sprites')

        return None

    def categorize_by_filepath(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """
        Categorize file by filepath patterns.
        Returns (category, subcategory) or None.
        """
        filepath_str = str(file_path)

        for category, patterns in self.filepath_patterns.items():
            for pattern in patterns:
                if re.search(pattern, filepath_str):
                    if category == 'game_assets':
                        return ('GameAssets', 'Other')
                    # Add more filepath-based categorization as needed

        return None

    def categorize_file(self, file_path: Path) -> Tuple[str, str]:
        """
        Categorize a file using filename and path patterns.
        Returns (category, subcategory).
        Priority: filename patterns > extension > filepath > uncategorized
        """
        # Priority 1: Filename patterns (most specific)
        result = self.categorize_by_filename(file_path)
        if result:
            return result

        # Priority 2: Extension
        result = self.categorize_by_extension(file_path)
        if result:
            return result

        # Priority 3: Filepath
        result = self.categorize_by_filepath(file_path)
        if result:
            return result

        # Default: Uncategorized
        return ('Uncategorized', 'Other')

    def get_destination_path(self, category: str, subcategory: str, filename: str) -> Path:
        """Get the full destination path for a file."""
        return self.base_path / category / subcategory / filename

    def move_file(self, source: Path, destination: Path) -> bool:
        """Move a file to its destination."""
        try:
            # Create destination directory
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Handle duplicates
            if destination.exists():
                # Add suffix to filename
                stem = destination.stem
                suffix = destination.suffix
                counter = 1
                while destination.exists():
                    new_name = f"{stem}_{counter}{suffix}"
                    destination = destination.parent / new_name
                    counter += 1

            if self.dry_run:
                print(f"  [DRY RUN] Would move to: {destination}")
            else:
                shutil.move(str(source), str(destination))
                print(f"  ✓ Moved to: {destination}")

            return True
        except Exception as e:
            print(f"  ✗ Error moving file: {e}")
            return False

    def organize_directory(self, source_dir: str, recursive: bool = False, limit: int = None):
        """Organize files in a directory."""
        source_path = Path(source_dir).expanduser()

        if not source_path.exists():
            print(f"Error: Source directory does not exist: {source_path}")
            return

        print("=" * 60)
        print("File Organization by Name and Path")
        print("=" * 60)
        print()
        print(f"Source: {source_path}")
        print(f"Base path: {self.base_path}")
        print(f"Recursive: {recursive}")
        print(f"Dry run: {self.dry_run}")
        if limit:
            print(f"Limit: {limit} files")
        print()

        # Collect files
        if recursive:
            files = list(source_path.rglob('*'))
        else:
            files = list(source_path.glob('*'))

        # Filter to files only
        files = [f for f in files if f.is_file()]

        # Apply limit
        if limit:
            files = files[:limit]

        self.stats['total_files'] = len(files)

        print(f"Found {len(files)} files to process")
        print()

        # Process files
        for i, file_path in enumerate(files, 1):
            print(f"[{i}/{len(files)}] {file_path.name}")

            try:
                # Categorize
                category, subcategory = self.categorize_file(file_path)

                # Get destination
                destination = self.get_destination_path(category, subcategory, file_path.name)

                print(f"  Category: {category}/{subcategory}")

                # Skip if already in correct location
                if file_path.parent == destination.parent:
                    print(f"  → Already in correct location")
                    self.stats['skipped_files'] += 1
                    continue

                # Move file
                if self.move_file(file_path, destination):
                    self.stats['moved_files'] += 1

                    # Update category stats
                    cat_key = f"{category}/{subcategory}"
                    self.stats['by_category'][cat_key] = self.stats['by_category'].get(cat_key, 0) + 1
                else:
                    self.stats['errors'] += 1

            except Exception as e:
                print(f"  ✗ Error processing file: {e}")
                self.stats['errors'] += 1

            print()

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print organization summary."""
        print()
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print()
        print(f"Total files: {self.stats['total_files']}")
        print(f"Moved: {self.stats['moved_files']}")
        print(f"Skipped (already in place): {self.stats['skipped_files']}")
        print(f"Errors: {self.stats['errors']}")
        print()

        if self.stats['by_category']:
            print("Files by category:")
            for category, count in sorted(self.stats['by_category'].items()):
                print(f"  {category}: {count}")

        # Save report
        if not self.dry_run and self.stats['moved_files'] > 0:
            self.save_report()

    def save_report(self):
        """Save organization report to JSON."""
        results_dir = Path(__file__).parent / 'results'
        results_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = results_dir / f'name_organization_report_{timestamp}.json'

        report = {
            'timestamp': timestamp,
            'base_path': str(self.base_path),
            'stats': self.stats,
        }

        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        print()
        print(f"Report saved: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Organize files by name and path patterns only',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Dry run (preview only)
  python3 file_organizer_by_name.py --dry-run --source ~/Documents/Uncategorized

  # Organize files
  python3 file_organizer_by_name.py --source ~/Documents/Uncategorized

  # Recursive with limit
  python3 file_organizer_by_name.py --source ~/Documents --recursive --limit 500

  # Custom base path
  python3 file_organizer_by_name.py --base-path ~/MyFiles --source ~/Downloads
        '''
    )

    parser.add_argument(
        '--source',
        required=True,
        help='Source directory to organize'
    )

    parser.add_argument(
        '--base-path',
        default='~/Documents',
        help='Base directory for organized files (default: ~/Documents)'
    )

    parser.add_argument(
        '--recursive',
        action='store_true',
        help='Process subdirectories recursively'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without moving files'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of files to process'
    )

    args = parser.parse_args()

    # Create organizer
    organizer = FileNameOrganizer(
        base_path=args.base_path,
        dry_run=args.dry_run
    )

    # Organize directory
    organizer.organize_directory(
        source_dir=args.source,
        recursive=args.recursive,
        limit=args.limit
    )


if __name__ == '__main__':
    main()
