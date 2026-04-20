#!/usr/bin/env python3
"""
Image Content Renamer - Rename images based on visual content analysis.

Uses CLIP vision model to analyze image content and generate descriptive filenames.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from shared.clip_utils import CLIP_AVAILABLE
from shared.clip_classification import classify_with_ocr_fallback
from shared.clip_naming import generate_filename as generate_clip_filename
from shared.confidence_gate import check_confidence
from shared.constants import IMAGE_EXTENSIONS_WIDE
from shared.file_ops import resolve_collision
from shared.filename_utils import is_generic_filename
from shared.ocr_utils import extract_ocr_text
from shared.status import ProcessingStatus, create_result_dict
from shared.file_organizer import FileOrganizer

from src.analyzers.image_metadata import ImageMetadataParser
from src.classifiers.content_classifier import ContentClassifier

# Backwards compatibility alias
RenameStatus = ProcessingStatus


class ImageAnalyzer:
    """Analyzes images using CLIP and OCR to identify content."""

    CONTENT_CATEGORIES = [
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
    ]

    _CLIP_OCR_FALLBACK_THRESHOLD = 0.10
    _CLIP_REFINEMENT_MIN_CONFIDENCE = 0.15
    _CLIP_REFINEMENT_ACCEPT_CONFIDENCE = 0.30

    REFINEMENT_TERMS = {
        "sofa": ["leather sofa", "fabric sofa", "sectional sofa", "outdoor sofa", "modern sofa"],
        "living room": ["cozy living room", "modern living room", "minimalist living room"],
        "landscape": ["mountain landscape", "coastal landscape", "rural landscape", "urban landscape"],
        "food": ["breakfast", "lunch", "dinner", "snack", "appetizer"],
        "dog": ["golden retriever", "labrador", "german shepherd", "poodle", "bulldog"],
        "cat": ["tabby cat", "black cat", "white cat", "orange cat", "calico cat"],
    }

    def __init__(self):
        self.content_classifier = ContentClassifier()
        self._metadata_parser = ImageMetadataParser()

    def analyze_image(self, image_path: Path) -> dict:
        """Analyze image and return result dict."""
        result = create_result_dict(image_path.name)

        if not is_generic_filename(image_path.name):
            result['status'] = ProcessingStatus.SKIPPED
            result['error'] = 'Already has descriptive name'
            return result

        clip_result = classify_with_ocr_fallback(
            image_path,
            self.CONTENT_CATEGORIES,
            ocr_threshold=self._CLIP_OCR_FALLBACK_THRESHOLD,
            content_classifier=self.content_classifier,
            refinement_terms=self.REFINEMENT_TERMS,
            refinement_min_confidence=self._CLIP_REFINEMENT_MIN_CONFIDENCE,
            refinement_accept_confidence=self._CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
            verbose=True,
        )

        if not clip_result:
            result['status'] = ProcessingStatus.NO_CONTENT
            result['error'] = 'Could not analyze content'
            return result

        content, confidence, all_scores = clip_result
        result['category'] = content
        result['confidence'] = confidence
        result['all_scores'] = all_scores
        result['new_name'] = generate_clip_filename(image_path, content, self._metadata_parser)
        result['status'] = ProcessingStatus.PENDING

        return result


class ImageContentRenamer:
    """Rename images based on visual content analysis using FileOrganizer."""

    IMAGE_EXTENSIONS = IMAGE_EXTENSIONS_WIDE

    def __init__(self, dry_run: bool = False, min_confidence: float = 0.30, mode: str = 'in-place'):
        self.dry_run = dry_run
        self.min_confidence = min_confidence
        self.mode = mode
        self.analyzer = ImageAnalyzer()
        self.organizer = FileOrganizer(
            analyzer=self.analyzer,
            source_dir=Path('.'),  # Will be set in process_directory
            dry_run=dry_run,
            find_images_fn=self._find_images,
            mode=mode,
        )

    def _find_images(self):
        """Find image files, filtering for generic names."""
        files = []
        for ext in self.IMAGE_EXTENSIONS:
            files.extend(self.organizer.source_dir.glob(f'*{ext}'))
            files.extend(self.organizer.source_dir.glob(f'*{ext.upper()}'))

        # Filter for generic filenames only
        return sorted([f for f in files if f.is_file() and is_generic_filename(f.name)])

    def process_directory(self, source_dir: Path, recursive: bool = False):
        """Process all images in a directory."""
        if not CLIP_AVAILABLE:
            print("Error: CLIP not available. Install torch and transformers.")
            return

        if recursive:
            print("Warning: recursive mode not yet supported with FileOrganizer")
            return

        self.organizer.source_dir = Path(source_dir)
        self.organizer.organize(min_confidence=self.min_confidence)


def main():
    import os
    parser = argparse.ArgumentParser(
        description="Rename images based on visual content analysis using CLIP"
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulate renaming without actually renaming files")
    parser.add_argument("--source", type=str, default="~/Documents",
                       help="Source directory to scan (default: ~/Documents)")
    parser.add_argument("--recursive", action="store_true",
                       help="Recursively scan subdirectories")
    parser.add_argument("--mode", type=str, default=None,
                       choices=['in-place', 'folder'],
                       help="Organization mode (in-place or folder-based)")
    parser.add_argument("--min-confidence", type=float, default=0.30,
                       help="Minimum confidence threshold (default: 0.30)")

    args = parser.parse_args()

    # Get mode from arg or environment variable
    mode = args.mode or os.environ.get('FILE_ORGANIZE_MODE', 'in-place')

    renamer = ImageContentRenamer(
        dry_run=args.dry_run,
        min_confidence=args.min_confidence,
        mode=mode
    )

    source_dir = Path(args.source).expanduser()
    if not source_dir.exists():
        print(f"Error: Directory not found: {source_dir}")
        return
    renamer.process_directory(source_dir, recursive=args.recursive)


if __name__ == "__main__":
    main()
