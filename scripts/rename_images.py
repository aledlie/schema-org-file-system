#!/usr/bin/env python3
"""Unified CLIP-based image renamer.

Replaces image_content_renamer.py and screenshot_renamer.py. Select a profile
to control category vocabulary, folder mapping, and default organization mode.

Profiles:
  photo       — general photo content (sofa, dog, food, landscape...). Default
                mode: in-place rename.
  screenshot  — game-asset and software-UI vocabulary with folder routing.
                Default mode: folder.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from shared.clip_utils import CLIP_AVAILABLE
from shared.clip_classification import (
    classify_with_ocr_fallback,
    generate_filename as generate_clip_filename,
)
from shared.constants import (
    IMAGE_EXTENSIONS_WIDE,
    CLIP_OCR_FALLBACK_THRESHOLD,
    CLIP_REFINEMENT_MIN_CONFIDENCE,
    CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
)
from shared.file_ops import resolve_collision
from shared.file_organizer import FileOrganizer
from shared.filename_utils import is_generic_filename
from shared.ocr_classifier import extract_ocr_text
from shared.status import ProcessingStatus, create_result_dict

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from src.analyzers.image_metadata import ImageMetadataParser
from src.classifiers.content_classifier import ContentClassifier

try:
    from error_tracking import init_sentry
    ERROR_TRACKING_AVAILABLE = True
except ImportError:
    ERROR_TRACKING_AVAILABLE = False
    def init_sentry(*_args, **_kwargs):
        return False


# Backwards-compat alias
RenameStatus = ProcessingStatus

DEFAULT_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


@dataclass
class RenamerProfile:
    """Vocabulary and routing config for a renamer flavor."""
    name: str
    categories: List[str]
    default_mode: str = 'in-place'
    refinement_terms: Dict[str, List[str]] = field(default_factory=dict)
    category_folders: Dict[str, str] = field(default_factory=dict)
    short_names: Dict[str, str] = field(default_factory=dict)
    image_extensions: set = field(default_factory=lambda: set(IMAGE_EXTENSIONS_WIDE))
    skip_descriptive_names: bool = True  # photo profile skips already-named files
    verbose: bool = True


PHOTO_PROFILE = RenamerProfile(
    name='photo',
    default_mode='in-place',
    skip_descriptive_names=True,
    verbose=True,
    categories=[
        # Furniture & Home
        "sofa", "couch", "sectional", "chair", "table", "desk", "bed", "lamp",
        "bookshelf", "cabinet", "dresser", "nightstand", "ottoman", "bench",
        # Rooms
        "living room", "bedroom", "kitchen", "bathroom", "office", "patio", "porch",
        "dining room", "garage", "backyard", "garden",
        # People & Portraits
        "portrait", "selfie", "group photo", "family photo", "headshot",
        # Pets
        "dog", "cat", "pet", "puppy", "kitten",
        # Food & Drinks
        "food", "meal", "restaurant", "coffee", "dessert", "cooking",
        # Nature & Outdoors
        "landscape", "mountain", "beach", "ocean", "forest", "sunset", "sunrise",
        "flowers", "trees", "park", "lake", "river", "sky",
        # Travel & Architecture
        "building", "architecture", "city", "street", "landmark", "monument",
        "hotel", "airport", "bridge",
        # Events
        "party", "wedding", "birthday", "concert", "celebration", "graduation",
        # Documents & Screenshots
        "document", "screenshot", "receipt", "menu", "sign", "text",
        # Vehicles
        "car", "motorcycle", "bicycle", "airplane", "boat",
        # Art & Creative
        "art", "painting", "drawing", "illustration", "craft",
        # Technology
        "computer", "phone", "electronics", "gadget",
        # Sports & Activities
        "sports", "fitness", "hiking", "swimming", "yoga",
    ],
    refinement_terms={
        "sofa": ["leather sofa", "fabric sofa", "sectional sofa", "outdoor sofa", "modern sofa"],
        "living room": ["cozy living room", "modern living room", "minimalist living room"],
        "landscape": ["mountain landscape", "coastal landscape", "rural landscape", "urban landscape"],
        "food": ["breakfast", "lunch", "dinner", "snack", "appetizer"],
        "dog": ["golden retriever", "labrador", "german shepherd", "poodle", "bulldog"],
        "cat": ["tabby cat", "black cat", "white cat", "orange cat", "calico cat"],
    },
)


SCREENSHOT_PROFILE = RenamerProfile(
    name='screenshot',
    default_mode='folder',
    skip_descriptive_names=False,
    verbose=False,
    image_extensions=set(DEFAULT_IMAGE_EXTENSIONS),
    categories=[
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
    ],
    category_folders={
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
    },
    refinement_terms={
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
            "a red dragon", "a green dragon", "a blue dragon",
            "a fire-breathing dragon",
        ],
        "a game UI button or icon": [
            "a rounded button", "a square button",
            "a circular icon", "a highlighted button",
        ],
        "a weapon sprite (sword, bow, staff)": [
            "a sword sprite", "a bow sprite", "a staff sprite", "a magic wand",
        ],
        "a potion or magical item": [
            "a red potion", "a blue potion", "a green potion", "a health potion",
        ],
    },
    short_names={
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
    },
)


PROFILES = {
    'photo': PHOTO_PROFILE,
    'screenshot': SCREENSHOT_PROFILE,
}


class ImageAnalyzer:
    """Profile-driven CLIP+OCR image analyzer."""

    def __init__(self, profile: RenamerProfile):
        self.profile = profile
        self.content_classifier = ContentClassifier()
        self._metadata_parser = ImageMetadataParser()

    def _detect_number(self, image_path: Path) -> Optional[str]:
        text = extract_ocr_text(image_path, config='--psm 10 --oem 3') or ""
        if text and text.isdigit():
            return text
        match = re.match(r'^(\d+)_', image_path.stem)
        return match.group(1) if match else None

    def analyze_image(self, image_path: Path) -> dict:
        result = create_result_dict(image_path.name)
        result['folder'] = 'Uncategorized'
        result['detected_text'] = None
        result['top_scores'] = {}

        if self.profile.skip_descriptive_names and not is_generic_filename(image_path.name):
            result['status'] = ProcessingStatus.SKIPPED
            result['error'] = 'Already has descriptive name'
            return result

        clip_result = classify_with_ocr_fallback(
            image_path,
            self.profile.categories,
            ocr_threshold=CLIP_OCR_FALLBACK_THRESHOLD,
            content_classifier=self.content_classifier,
            refinement_terms=self.profile.refinement_terms,
            refinement_min_confidence=CLIP_REFINEMENT_MIN_CONFIDENCE,
            refinement_accept_confidence=CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
            verbose=self.profile.verbose,
        )

        if not clip_result:
            result['status'] = ProcessingStatus.NO_CONTENT
            result['error'] = 'Could not analyze content'
            return result

        category, confidence, all_scores = clip_result
        result['category'] = category
        result['confidence'] = confidence
        result['all_scores'] = all_scores
        result['top_scores'] = dict(sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:5])
        result['status'] = ProcessingStatus.PENDING

        if self.profile.category_folders:
            result['folder'] = self.profile.category_folders.get(category, 'Uncategorized')

        content_label = category
        if self.profile.name == 'screenshot':
            detected_num = self._detect_number(image_path)
            if detected_num:
                result['detected_text'] = detected_num
                if category == "a number or digit icon":
                    content_label = f"{category}_{detected_num}"

        result['new_name'] = generate_clip_filename(
            image_path, content_label, self._metadata_parser
        )
        return result


class ImageRenamer:
    """Drive FileOrganizer with a chosen profile."""

    def __init__(
        self,
        profile: RenamerProfile,
        source_dir: Path,
        output_dir: Optional[Path] = None,
        dry_run: bool = True,
        mode: Optional[str] = None,
        min_confidence: float = 0.30,
    ):
        self.profile = profile
        self.source_dir = Path(source_dir)
        self.output_dir = output_dir or self.source_dir
        self.dry_run = dry_run
        self.mode = mode or profile.default_mode
        self.min_confidence = min_confidence
        self.analyzer = ImageAnalyzer(profile)
        self.organizer = FileOrganizer(
            analyzer=self.analyzer,
            source_dir=self.source_dir,
            output_dir=self.output_dir,
            dry_run=dry_run,
            find_images_fn=self._find_images,
            mode=self.mode,
        )

    def _find_images(self) -> List[Path]:
        files = []
        for ext in self.profile.image_extensions:
            files.extend(self.source_dir.glob(f'*{ext}'))
            files.extend(self.source_dir.glob(f'*{ext.upper()}'))
        files = [f for f in files if f.is_file()]
        if self.profile.skip_descriptive_names:
            files = [f for f in files if is_generic_filename(f.name)]
        return sorted(files)

    def organize(self, limit: Optional[int] = None):
        if self.mode == 'folder' and self.profile.category_folders:
            original_analyze = self.analyzer.analyze_image

            def analyze_with_dest(image_path: Path) -> dict:
                result = original_analyze(image_path)
                if result.get('new_name'):
                    dest_folder = self.output_dir / result.get('folder', 'Uncategorized')
                    dest_path = resolve_collision(dest_folder / result['new_name'])
                    result['dest_folder'] = str(dest_folder)
                    result['dest_path'] = str(dest_path)
                return result

            self.analyzer.analyze_image = analyze_with_dest

        return self.organizer.organize(limit=limit, min_confidence=self.min_confidence)

    def save_results(self, output_file: Optional[Path] = None):
        self.organizer.save_results(output_file)


# Backwards-compatible shims for callers still importing the old class names.
class ImageContentRenamer:
    """Compat shim — prefer ImageRenamer(profile=PHOTO_PROFILE)."""

    IMAGE_EXTENSIONS = IMAGE_EXTENSIONS_WIDE

    def __init__(self, dry_run: bool = False, min_confidence: float = 0.30, mode: str = 'in-place'):
        self.dry_run = dry_run
        self.min_confidence = min_confidence
        self.mode = mode
        self._renamer: Optional[ImageRenamer] = None

    def process_directory(self, source_dir: Path, recursive: bool = False):
        if not CLIP_AVAILABLE:
            print("Error: CLIP not available. Install torch and transformers.")
            return
        if recursive:
            print("Warning: recursive mode not yet supported with FileOrganizer")
            return
        self._renamer = ImageRenamer(
            profile=PHOTO_PROFILE,
            source_dir=Path(source_dir),
            dry_run=self.dry_run,
            mode=self.mode,
            min_confidence=self.min_confidence,
        )
        self._renamer.organize()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default='~/Documents',
                        help='Source directory (default: ~/Documents)')
    parser.add_argument('--profile', choices=sorted(PROFILES),
                        default='photo',
                        help='Renamer profile (default: photo)')
    parser.add_argument('--output', '-o', help='Output directory (folder mode)')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of files')
    parser.add_argument('--dry-run', '-n', action='store_true', default=True,
                        help='Simulate without renaming (default)')
    parser.add_argument('--execute', '-x', action='store_true',
                        help='Actually perform rename/move')
    parser.add_argument('--mode', '-m', choices=['in-place', 'folder'],
                        help='Organization mode (default: per-profile)')
    parser.add_argument('--min-confidence', '-c', type=float, default=0.10,
                        help='Minimum confidence threshold')
    parser.add_argument('--sentry-dsn', help='Sentry DSN for error tracking')
    args = parser.parse_args()

    sentry_dsn = args.sentry_dsn or os.environ.get('FILE_SYSTEM_SENTRY_DSN')
    if sentry_dsn and ERROR_TRACKING_AVAILABLE:
        init_sentry(sentry_dsn)

    profile = PROFILES[args.profile]
    source_dir = Path(args.source).expanduser()
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    output_dir = Path(args.output).expanduser() if args.output else source_dir
    mode = args.mode or os.environ.get('FILE_ORGANIZE_MODE') or profile.default_mode
    dry_run = not args.execute

    renamer = ImageRenamer(
        profile=profile,
        source_dir=source_dir,
        output_dir=output_dir,
        dry_run=dry_run,
        mode=mode,
        min_confidence=args.min_confidence,
    )
    renamer.organize(limit=args.limit)
    renamer.save_results()


if __name__ == '__main__':
    main()
