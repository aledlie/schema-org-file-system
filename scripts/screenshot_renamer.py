#!/usr/bin/env python3
"""
Screenshot Renamer and Categorizer using CLIP Vision and OCR.

Analyzes screenshot images to:
1. Identify content (characters, numbers, UI elements, etc.)
2. Rename files based on detected content
3. Categorize into appropriate subdirectories
"""

import sys
import os
import shutil
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import json

from shared.clip_utils import CLIPClassifier, CLIP_AVAILABLE
from shared.clip_classification import classify_with_ocr_fallback
from shared.clip_naming import generate_filename as generate_clip_filename
from shared.confidence_gate import check_confidence
from shared.ocr_utils import extract_ocr_text, is_ocr_available
from shared.file_ops import resolve_collision
from shared.status import ProcessingStatus, create_result_dict, update_stats_from_status

# Add src directory to path for error tracking (portable)
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

try:
    from error_tracking import init_sentry, capture_error, track_operation
    ERROR_TRACKING_AVAILABLE = True
except ImportError:
    ERROR_TRACKING_AVAILABLE = False
    def init_sentry(*args, **kwargs): return False
    def capture_error(*args, **kwargs): pass
    def track_operation(*args, **kwargs):
        from contextlib import nullcontext
        return nullcontext()


class ScreenshotAnalyzer:
    """Analyzes screenshots using CLIP and OCR to identify content."""

    # CLIP confidence below this triggers OCR fallback
    _CLIP_OCR_FALLBACK_THRESHOLD = 0.10

    def __init__(self):
        self.vision_available = CLIP_AVAILABLE
        self.ocr_available = is_ocr_available()

        # Define game asset categories for CLIP classification
        self.game_categories = [
            # Software/App Screenshots (check first to avoid game misclassification)
            "a software dashboard or admin panel",
            "a terminal or command line interface",
            "a code editor or IDE screenshot",
            "a web browser screenshot",
            "a chat or messaging application",
            "a settings or preferences screen",
            "an e-commerce or online shopping page",
            "a product listing or retail website",
            "a documentation or technical guide page",
            "a marketing or landing page website",
            "an infographic or diagram with text",
            # Characters
            "a game character sprite",
            "a warrior or knight character",
            "a dragon or monster sprite",
            "a skeleton or undead character",
            "a goblin or troll character",
            "a fairy or magical creature",
            "a wizard or mage character",
            "a spider or insect creature",
            "a robot or mechanical character",
            "an animal character sprite",
            # Numbers/UI
            "a number or digit icon",
            "a game UI button or icon",
            "a menu icon or symbol",
            "a coin or currency icon",
            "a health or status bar",
            "a power-up or bonus item",
            # Items
            "a weapon sprite (sword, bow, staff)",
            "an armor or shield sprite",
            "a potion or magical item",
            "a treasure chest or container",
            # Environment
            "a tile or terrain sprite",
            "a building or structure sprite",
            "a tree or plant sprite",
            # Effects
            "a magical effect or particle",
            "an explosion or fire effect",
        ]

        # Simplified categories for folder organization
        self.category_mapping = {
            # Software/App Screenshots
            "a software dashboard or admin panel": "Software/Dashboards",
            "a terminal or command line interface": "Software/Terminal",
            "a code editor or IDE screenshot": "Software/CodeEditors",
            "a web browser screenshot": "Software/Browser",
            "a chat or messaging application": "Software/Chat",
            "a settings or preferences screen": "Software/Settings",
            "an e-commerce or online shopping page": "Software/Shopping",
            "a product listing or retail website": "Software/Shopping",
            "a documentation or technical guide page": "Software/Documentation",
            "a marketing or landing page website": "Software/Marketing",
            "an infographic or diagram with text": "Software/Infographics",
            # Game Characters
            "a game character sprite": "Characters/Generic",
            "a warrior or knight character": "Characters/Warriors",
            "a dragon or monster sprite": "Characters/Monsters",
            "a skeleton or undead character": "Characters/Undead",
            "a goblin or troll character": "Characters/Creatures",
            "a fairy or magical creature": "Characters/Magical",
            "a wizard or mage character": "Characters/Mages",
            "a spider or insect creature": "Characters/Creatures",
            "a robot or mechanical character": "Characters/Robots",
            "an animal character sprite": "Characters/Animals",
            "a number or digit icon": "UI/Numbers",
            "a game UI button or icon": "UI/Buttons",
            "a menu icon or symbol": "UI/Icons",
            "a coin or currency icon": "UI/Currency",
            "a health or status bar": "UI/StatusBars",
            "a power-up or bonus item": "Items/PowerUps",
            "a weapon sprite (sword, bow, staff)": "Items/Weapons",
            "an armor or shield sprite": "Items/Armor",
            "a potion or magical item": "Items/Potions",
            "a treasure chest or container": "Items/Containers",
            "a tile or terrain sprite": "Environment/Terrain",
            "a building or structure sprite": "Environment/Buildings",
            "a tree or plant sprite": "Environment/Nature",
            "a magical effect or particle": "Effects/Magic",
            "an explosion or fire effect": "Effects/Explosions",
        }

        # Short name prefixes for renaming
        self. = {
            # Software/App Screenshots
            "a software dashboard or admin panel": "dashboard",
            "a terminal or command line interface": "terminal",
            "a code editor or IDE screenshot": "code",
            "a web browser screenshot": "browser",
            "a chat or messaging application": "chat",
            "a settings or preferences screen": "settings",
            "an e-commerce or online shopping page": "shop",
            "a product listing or retail website": "product",
            "a documentation or technical guide page": "docs",
            "a marketing or landing page website": "landing",
            "an infographic or diagram with text": "infographic",
            # Game Characters
            "a game character sprite": "char",
            "a warrior or knight character": "warrior",
            "a dragon or monster sprite": "dragon",
            "a skeleton or undead character": "skeleton",
            "a goblin or troll character": "goblin",
            "a fairy or magical creature": "fairy",
            "a wizard or mage character": "wizard",
            "a spider or insect creature": "spider",
            "a robot or mechanical character": "robot",
            "an animal character sprite": "animal",
            "a number or digit icon": "num",
            "a game UI button or icon": "btn",
            "a menu icon or symbol": "icon",
            "a coin or currency icon": "coin",
            "a health or status bar": "status",
            "a power-up or bonus item": "powerup",
            "a weapon sprite (sword, bow, staff)": "weapon",
            "an armor or shield sprite": "armor",
            "a potion or magical item": "potion",
            "a treasure chest or container": "chest",
            "a tile or terrain sprite": "tile",
            "a building or structure sprite": "building",
            "a tree or plant sprite": "plant",
            "a magical effect or particle": "magic_fx",
            "an explosion or fire effect": "explosion",
        }

    def extract_text_ocr(self, image_path: Path) -> str:
        """Extract text from image using OCR."""
        return extract_ocr_text(image_path, config='--psm 10 --oem 3') or ""

    def detect_number(self, image_path: Path) -> Optional[str]:
        """Try to detect if image contains a number."""
        # First try OCR
        text = self.extract_text_ocr(image_path)

        # Check if it's a number
        if text and text.isdigit():
            return text

        # Check filename for number hints
        filename = image_path.stem
        # Extract leading number from filename like "30_20251120..."
        match = re.match(r'^(\d+)_', filename)
        if match:
            num = match.group(1)
            # This might be the actual content if it's a number icon
            return num

        return None

    

    def analyze_image(self, image_path: Path) -> Dict:
        """
        Fully analyze an image and return rename/category info.

        Returns:
            Dict with: category, folder, new_name, confidence, detected_text, status
        """
        result = create_result_dict(image_path.name)
        result['folder'] = 'Uncategorized'
        result['detected_text'] = None
        result['top_scores'] = {}

        # Classify with CLIP and OCR fallback
        clip_result = classify_with_ocr_fallback(
            image_path,
            self.game_categories,
            ocr_threshold=self._CLIP_OCR_FALLBACK_THRESHOLD,
            verbose=False,
        )

        if clip_result:
            best_category, confidence, scores = clip_result
            result['status'] = ProcessingStatus.PENDING
        else:
            best_category, confidence, scores = "unknown", 0.0, {}
            result['status'] = ProcessingStatus.NO_CONTENT

        result['category'] = best_category
        result['confidence'] = confidence
        result['top_scores'] = dict(sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5])

        # Get folder mapping
        result['folder'] = self.category_mapping.get(best_category, 'Uncategorized')

        # Try to detect numbers
        detected_num = self.detect_number(image_path)
        if detected_num:
            result['detected_text'] = detected_num

        # Generate new name with detected number as suffix if available
        if detected_num and best_category == "a number or digit icon":
            content_label = f"{best_category}_{detected_num}"
        else:
            content_label = best_category

        result['new_name'] = generate_clip_filename(image_path, content_label)

        return result


class ScreenshotOrganizer:
    """Organizes screenshots by renaming and categorizing them."""

    def __init__(self, source_dir: Path, output_dir: Path = None, dry_run: bool = True):
        self.source_dir = Path(source_dir)
        self.output_dir = output_dir or self.source_dir
        self.dry_run = dry_run
        self.analyzer = ScreenshotAnalyzer()
        self.results = []
        self.stats = defaultdict(int)

    def find_images(self) -> List[Path]:
        """Find all image files in source directory."""
        extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
        images = []

        for ext in extensions:
            images.extend(self.source_dir.glob(f'*{ext}'))
            images.extend(self.source_dir.glob(f'*{ext.upper()}'))

        return sorted(images)

    def process_image(self, image_path: Path) -> Dict:
        """Process a single image."""
        result = self.analyzer.analyze_image(image_path)

        # Determine destination
        dest_folder = self.output_dir / result['folder']
        dest_path = dest_folder / result['new_name']

        # Handle name collisions
        dest_path = resolve_collision(dest_path)

        result['dest_folder'] = str(dest_folder)
        result['dest_path'] = str(dest_path)

        return result

    def organize(self, limit: int = None, min_confidence: float = 0.1) -> List[Dict]:
        """
        Organize all images in source directory.

        Args:
            limit: Maximum number of images to process
            min_confidence: Minimum confidence to accept classification

        Returns:
            List of processing results
        """
        images = self.find_images()

        if limit:
            images = images[:limit]

        total = len(images)
        print(f"\n{'='*60}")
        print(f"Screenshot Renamer & Organizer")
        print(f"{'='*60}")
        print(f"Source: {self.source_dir}")
        print(f"Output: {self.output_dir}")
        print(f"Images: {total}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"{'='*60}\n")

        self.stats['total'] = total

        for i, image_path in enumerate(images, 1):
            print(f"[{i}/{total}] Processing: {image_path.name}")

            try:
                result = self.process_image(image_path)
                
                # Check confidence gate
                gate = check_confidence(result['category'], result['confidence'], min_confidence)
                if not gate.accepted:
                    result['status'] = ProcessingStatus.LOW_CONFIDENCE
                    result['error'] = gate.reason
                    update_stats_from_status(self.stats, result['status'])
                    print(f"  ⊘ {gate.reason}")
                    self.results.append(result)
                    continue
                
                result['status'] = ProcessingStatus.RENAMED if not self.dry_run else ProcessingStatus.WOULD_RENAME
                self.results.append(result)

                # Update stats
                self.stats['processed'] = self.stats.get('processed', 0) + 1
                self.stats[result['folder']] = self.stats.get(result['folder'], 0) + 1

                # Show result
                conf_str = f"{result['confidence']*100:.1f}%"
                print(f"  → {result['folder']}/{result['new_name']} ({conf_str})")

                # Actually move/rename if not dry run
                if not self.dry_run:
                    dest_folder = Path(result['dest_folder'])
                    dest_path = Path(result['dest_path'])

                    # Create destination folder
                    dest_folder.mkdir(parents=True, exist_ok=True)

                    # Copy or move file
                    shutil.copy2(image_path, dest_path)
                    self.stats['moved'] = self.stats.get('moved', 0) + 1
                    update_stats_from_status(self.stats, result['status'])

            except Exception as e:
                print(f"  ✗ Error: {e}")
                self.stats['errors'] = self.stats.get('errors', 0) + 1
                if ERROR_TRACKING_AVAILABLE:
                    capture_error(e, context={'file': str(image_path)})

        self.print_summary()
        return self.results

    def print_summary(self):
        """Print organization summary."""
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total processed: {self.stats['processed']}")

        if not self.dry_run:
            print(f"Files moved: {self.stats['moved']}")

        print(f"Errors: {self.stats['errors']}")

        print(f"\nBy Category:")
        for key, count in sorted(self.stats.items()):
            if key not in ('processed', 'moved', 'errors') and '/' in key:
                print(f"  {key}: {count}")

    def save_results(self, output_file: Path = None):
        """Save results to JSON file."""
        if output_file is None:
            output_file = self.output_dir / 'organization_results.json'

        with open(output_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'source_dir': str(self.source_dir),
                'output_dir': str(self.output_dir),
                'dry_run': self.dry_run,
                'stats': dict(self.stats),
                'results': self.results
            }, f, indent=2)

        print(f"\nResults saved to: {output_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Rename and categorize screenshot images using AI vision'
    )
    parser.add_argument(
        'source',
        nargs='?',
        default='~/Documents/ImageObject/Screenshot',
        help='Source directory containing screenshots'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output directory (default: same as source with subdirectories)'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        help='Limit number of images to process'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        default=True,
        help='Dry run - show what would be done without making changes (default)'
    )
    parser.add_argument(
        '--execute', '-x',
        action='store_true',
        help='Actually execute the rename/move operations'
    )
    parser.add_argument(
        '--min-confidence', '-c',
        type=float,
        default=0.1,
        help='Minimum confidence threshold (default: 0.1)'
    )
    parser.add_argument(
        '--sentry-dsn',
        help='Sentry DSN for error tracking'
    )

    args = parser.parse_args()

    # Initialize Sentry if available
    sentry_dsn = args.sentry_dsn or os.environ.get('FILE_SYSTEM_SENTRY_DSN')
    if sentry_dsn and ERROR_TRACKING_AVAILABLE:
        init_sentry(sentry_dsn)

    # Resolve paths
    source_dir = Path(args.source).expanduser()
    output_dir = Path(args.output).expanduser() if args.output else source_dir

    # Determine dry run mode
    dry_run = not args.execute

    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    # Run organizer
    organizer = ScreenshotOrganizer(
        source_dir=source_dir,
        output_dir=output_dir,
        dry_run=dry_run
    )

    results = organizer.organize(
        limit=args.limit,
        min_confidence=args.min_confidence
    )

    # Save results
    organizer.save_results()


if __name__ == '__main__':
    main()
