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
import re
from pathlib import Path
from typing import Dict, Optional

from shared.clip_utils import CLIP_AVAILABLE
from shared.clip_classification import classify_with_ocr_fallback
from shared.clip_naming import generate_filename as generate_clip_filename
from shared.confidence_gate import check_confidence
from shared.ocr_utils import extract_ocr_text, is_ocr_available
from shared.file_ops import resolve_collision
from shared.status import ProcessingStatus, create_result_dict
from shared.file_organizer import FileOrganizer

# Add src directory to path for error tracking (portable)
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.classifiers.content_classifier import ContentClassifier

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
    # Minimum CLIP confidence to attempt refinement with more specific terms
    _CLIP_REFINEMENT_MIN_CONFIDENCE = 0.15
    # Minimum confidence for a refined term to be accepted
    _CLIP_REFINEMENT_ACCEPT_CONFIDENCE = 0.30

    def __init__(self):
        self.vision_available = CLIP_AVAILABLE
        self.ocr_available = is_ocr_available()
        self.content_classifier = ContentClassifier()

        # Base game asset categories for CLIP classification (game-specific)
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

        # Refinement terms for more specific classification
        self.refinement_terms = {
            "a game character sprite": [
                "a warrior or knight character",
                "a dragon or monster sprite",
                "a skeleton or undead character",
                "a goblin or troll character",
                "a fairy or magical creature",
                "a wizard or mage character",
                "a spider or insect creature",
                "a robot or mechanical character",
                "an animal character sprite",
            ],
            "a warrior or knight character": [
                "a knight in full armor",
                "a warrior with a sword",
                "a knight with a shield",
            ],
            "a dragon or monster sprite": [
                "a red dragon",
                "a green dragon",
                "a blue dragon",
                "a fire-breathing dragon",
            ],
            "a game UI button or icon": [
                "a rounded button",
                "a square button",
                "a circular icon",
                "a highlighted button",
            ],
            "a weapon sprite (sword, bow, staff)": [
                "a sword sprite",
                "a bow sprite",
                "a staff sprite",
                "a magic wand",
            ],
            "a potion or magical item": [
                "a red potion",
                "a blue potion",
                "a green potion",
                "a health potion",
            ],
        }

        # Short name prefixes for renaming
        self.short_names = {
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
            content_classifier=self.content_classifier,
            refinement_terms=self.refinement_terms,
            refinement_min_confidence=self._CLIP_REFINEMENT_MIN_CONFIDENCE,
            refinement_accept_confidence=self._CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
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

    def __init__(self, source_dir: Path, output_dir: Path = None, dry_run: bool = True, mode: str = 'folder'):
        self.source_dir = Path(source_dir)
        self.output_dir = output_dir or self.source_dir
        self.dry_run = dry_run
        self.mode = mode
        analyzer = ScreenshotAnalyzer()
        self.organizer = FileOrganizer(
            analyzer=analyzer,
            source_dir=self.source_dir,
            output_dir=self.output_dir,
            dry_run=dry_run,
            find_images_fn=self._find_images,
            mode=mode,
        )

    def _find_images(self):
        """Find all image files in source directory."""
        extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
        images = []
        for ext in extensions:
            images.extend(self.source_dir.glob(f'*{ext}'))
            images.extend(self.source_dir.glob(f'*{ext.upper()}'))
        return sorted(images)

    def organize(self, limit: int = None, min_confidence: float = 0.1):
        """
        Organize all images in source directory.

        Args:
            limit: Maximum number of images to process
            min_confidence: Minimum confidence to accept classification

        Returns:
            List of processing results
        """
        # For folder mode, enhance analyzer results with dest paths
        if self.mode == 'folder':
            original_analyze = self.organizer.analyzer.analyze_image

            def analyze_with_dest(image_path):
                result = original_analyze(image_path)
                # Determine destination
                dest_folder = self.output_dir / result['folder']
                dest_path = dest_folder / result['new_name']
                # Handle name collisions
                dest_path = resolve_collision(dest_path)
                result['dest_folder'] = str(dest_folder)
                result['dest_path'] = str(dest_path)
                return result

            self.organizer.analyzer.analyze_image = analyze_with_dest

        return self.organizer.organize(limit=limit, min_confidence=min_confidence)

    def save_results(self, output_file: Path = None):
        """Save results to JSON file."""
        self.organizer.save_results(output_file)


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
        '--mode', '-m',
        type=str,
        default=None,
        choices=['folder', 'in-place'],
        help='Organization mode (folder-based or in-place rename)'
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

    # Get mode from arg or environment variable
    mode = args.mode or os.environ.get('FILE_ORGANIZE_MODE', 'folder')

    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    # Run organizer
    organizer = ScreenshotOrganizer(
        source_dir=source_dir,
        output_dir=output_dir,
        dry_run=dry_run,
        mode=mode
    )

    results = organizer.organize(
        limit=args.limit,
        min_confidence=args.min_confidence
    )

    # Save results
    organizer.save_results()


if __name__ == '__main__':
    main()
