#!/usr/bin/env python3
"""
Simple file organizer based on file extensions and naming patterns.
Organizes files by type without OCR.
"""

import shutil
import sys
from pathlib import Path
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.cli_inputs import TypeInputs

# shared/ lives in scripts/ and the canonical classifier in src/ — ensure both
# resolve when this file is imported directly (e.g. in tests that add scripts/
# to sys.path themselves).
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.file_ops import resolve_collision  # noqa: E402
from shared.file_ops import should_skip_file as _shared_should_skip_file  # noqa: E402
from src.organizers.mime_classifier import classify_by_mime  # noqa: E402
from src.organizers.category_config import CATEGORY_PATHS  # noqa: E402

# Miscellaneous known formats with no canonical format category. Bucketed to
# 'Other' (vs 'Uncategorized' for truly-unknown extensions) to preserve intent.
_MISC_EXTENSIONS = {'.tpl', '.proto', '.rst', '.noe', '.lark'}


class FileTypeOrganizer:
    """Organize files based on file type and naming patterns."""

    def __init__(self, base_path: str = None):
        """Initialize the organizer."""
        self.base_path = Path(base_path or "~/Documents").expanduser()
        self.stats = defaultdict(int)

    def get_category_for_file(self, file_path: Path) -> str:
        """Determine the destination folder for a file.

        Name/structure heuristics run first (screenshots, game assets,
        extension-less timezone data); the format itself is then resolved by the
        canonical ``classify_by_mime`` (extension-only, ``mime_type=None``) and
        mapped to a destination via ``CATEGORY_PATHS``.
        """
        ext = file_path.suffix.lower()
        name_lower = file_path.name.lower()

        # Special naming/structure patterns BEFORE format classification
        # Screenshots - check first so they don't get categorized as generic images
        if name_lower.startswith('screenshot'):
            return 'Images/Photos/Screenshots'

        # Game assets (lots of numbered/timestamped files)
        if any(pattern in name_lower for pattern in ['frame', 'item', 'segment', 'wing', 'arm', 'leg', 'head', 'torso']):
            return 'Images/Photos/GameAssets'

        # Extension-less single-token files (e.g. timezone data)
        if file_path.suffix == '' and len(file_path.name.split('_')) == 1:
            return 'Data/Timezones'

        category, subcategory, _ = classify_by_mime(file_path, None)
        return self._resolve_category_path(category, subcategory, ext)

    @staticmethod
    def _resolve_category_path(category: str, subcategory: str, ext: str) -> str:
        """Map a (category, subcategory) pair to a destination folder string.

        Mirrors ``ContentOrganizer.get_destination_path`` resolution against
        ``CATEGORY_PATHS``. Files the classifier cannot place (``('other',
        'other')``) go to 'Other' for known-but-uncategorized formats and
        'Uncategorized' for everything else, preserving the prior fallback split.
        """
        if (category, subcategory) == ('other', 'other'):
            return 'Other' if ext in _MISC_EXTENSIONS else 'Uncategorized'
        node = CATEGORY_PATHS.get(category)
        if isinstance(node, dict):
            return node.get(subcategory) or node.get('other', f'{category.capitalize()}/Other')
        if isinstance(node, str):
            return node
        return 'Uncategorized'

    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped (delegates to shared.file_ops.should_skip_file)."""
        return _shared_should_skip_file(file_path)

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

            # Handle duplicate filenames — delegate to the shared incrementing counter
            dest_path = dest_dir / file_path.name
            if dest_path.exists() and dest_path != file_path:
                dest_path = resolve_collision(dest_path)

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


def run(args: "TypeInputs") -> None:
    """Typed entry point: organize by extension from validated CLI inputs.

    ``args`` is the frozen ``src.cli_inputs.TypeInputs`` dataclass built
    from the options ``src.cli.add_type_arguments`` defines (the single
    source for this command, shared with the unified CLI).
    """
    organizer = FileTypeOrganizer(base_path=args.base_path)

    for source_dir in args.sources:
        summary = organizer.organize_directory(
            source_dir=source_dir,
            dry_run=args.dry_run
        )
        organizer.print_summary(summary)


def main():
    """Standalone entry point (argument definitions shared with organize-files)."""
    import argparse

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.cli import add_type_arguments
    from src.cli_inputs import TypeInputs

    parser = argparse.ArgumentParser(
        description='Organize files by type based on extensions'
    )
    add_type_arguments(parser)
    run(TypeInputs.from_namespace(parser.parse_args()))


if __name__ == '__main__':
    main()
