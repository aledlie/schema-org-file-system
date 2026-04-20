#!/usr/bin/env python3
"""
Image Content Renamer - Rename images based on visual content analysis.

Uses CLIP vision model to analyze image content and generate descriptive filenames.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from enum import Enum
from pathlib import Path

from shared.clip_utils import CLIP_AVAILABLE
from shared.clip_classification import classify_with_ocr_fallback
from shared.constants import IMAGE_EXTENSIONS_WIDE
from shared.file_ops import resolve_collision
from shared.filename_utils import is_generic_filename
from shared.ocr_utils import is_ocr_available

from src.analyzers.image_metadata import ImageMetadataParser
from src.classifiers.content_classifier import ContentClassifier


class RenameStatus(Enum):
    PENDING = 'pending'
    SKIPPED = 'skipped'
    RENAMED = 'renamed'
    WOULD_RENAME = 'would_rename'
    NO_CONTENT = 'no_content'
    LOW_CONFIDENCE = 'low_confidence'
    ERROR = 'error'


class ImageContentRenamer:
    """Rename images based on visual content analysis."""

    IMAGE_EXTENSIONS = IMAGE_EXTENSIONS_WIDE

    # Content categories for CLIP classification
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

    # Screenshot-specific subcategories not covered by the Schema.org
    # taxonomy in ContentClassifier.  These are checked first; if none
    # match, the fallback delegates to ContentClassifier.classify_content().

    # CLIP confidence below this triggers OCR fallback
    _CLIP_OCR_FALLBACK_THRESHOLD = 0.10
    # Minimum CLIP confidence to attempt refinement with more specific terms
    _CLIP_REFINEMENT_MIN_CONFIDENCE = 0.15
    # Minimum confidence for a refined term to be accepted
    _CLIP_REFINEMENT_ACCEPT_CONFIDENCE = 0.30
    # Minimum confidence to proceed with renaming
    _RENAME_CONFIDENCE_THRESHOLD = 0.30

    # More specific descriptions for refinement
    REFINEMENT_TERMS = {
        "sofa": ["leather sofa", "fabric sofa", "sectional sofa", "outdoor sofa", "modern sofa"],
        "living room": ["cozy living room", "modern living room", "minimalist living room"],
        "landscape": ["mountain landscape", "coastal landscape", "rural landscape", "urban landscape"],
        "food": ["breakfast", "lunch", "dinner", "snack", "appetizer"],
        "dog": ["golden retriever", "labrador", "german shepherd", "poodle", "bulldog"],
        "cat": ["tabby cat", "black cat", "white cat", "orange cat", "calico cat"],
    }

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.content_classifier = ContentClassifier()
        self._metadata_parser = ImageMetadataParser()
        self.stats = {
            'total': 0,
            'renamed': 0,
            'skipped': 0,
            'errors': 0,
            'no_content': 0,
        }

        # OCR text from the last classify_by_ocr call, exposed so the
        # organizer can reuse it instead of re-running OCR.
        self._last_ocr_text: str | None = None

    def analyze_image(
        self, image_path: Path
    ) -> tuple[str, float, dict[str, float]] | None:
        """
        Analyze image content using CLIP, falling back to OCR when
        CLIP confidence is below threshold.

        Returns ``(category, confidence, all_scores)`` or ``None``.
        ``all_scores`` is empty for CLIP-only results.
        """
        result = classify_with_ocr_fallback(
            image_path,
            self.CONTENT_CATEGORIES,
            ocr_threshold=self._CLIP_OCR_FALLBACK_THRESHOLD,
            content_classifier=self.content_classifier,
            refinement_terms=self.REFINEMENT_TERMS,
            refinement_min_confidence=self._CLIP_REFINEMENT_MIN_CONFIDENCE,
            refinement_accept_confidence=self._CLIP_REFINEMENT_ACCEPT_CONFIDENCE,
            collect_all_scores=False,
            verbose=True,
        )

        # Extract OCR text if used (via side effect of verbose logging)
        # Note: OCR text is not returned by classify_with_ocr_fallback,
        # so we cache None here. If needed, extend the function to return it.
        self._last_ocr_text = None

        return result

    def generate_filename(self, image_path: Path, content: str) -> str:
        """Generate a new filename based on content analysis."""
        clean_content = re.sub(r'[^a-z0-9_]', '', content.lower().replace(" ", "_"))

        dt = self._metadata_parser.extract_datetime(image_path)
        if dt is None:
            try:
                dt = datetime.fromtimestamp(image_path.stat().st_mtime)
            except Exception:
                dt = None
        date_str = dt.strftime("%Y%m%d") if dt else None

        ext = image_path.suffix.lower()
        if date_str:
            return f"{date_str}_{clean_content}{ext}"
        return f"{clean_content}{ext}"

    def should_rename(self, filename: str) -> bool:
        """Check if file has a generic name that should be renamed."""
        return is_generic_filename(filename)

    def rename_file(self, file_path: Path) -> dict:
        """Analyze and rename a single image file."""
        self._last_ocr_text = None

        result = {
            'original': file_path.name,
            'new_name': None,
            'content': None,
            'confidence': None,
            'all_scores': {},
            'status': RenameStatus.PENDING,
            'error': None,
        }

        if not self.should_rename(file_path.name):
            result['status'] = RenameStatus.SKIPPED
            result['error'] = 'Already has descriptive name'
            self.stats['skipped'] += 1
            return result

        analysis = self.analyze_image(file_path)
        if not analysis:
            result['status'] = RenameStatus.NO_CONTENT
            result['error'] = 'Could not analyze content'
            self.stats['no_content'] += 1
            return result

        content, confidence, all_scores = analysis
        result['content'] = content
        result['confidence'] = confidence
        result['all_scores'] = all_scores

        # OCR-fallback matches below this gate produce unreliable labels
        # that mislead downstream classification.
        if confidence < self._RENAME_CONFIDENCE_THRESHOLD:
            result['status'] = RenameStatus.LOW_CONFIDENCE
            result['error'] = f'Confidence too low: {confidence:.1%}'
            self.stats['skipped'] += 1
            return result

        new_name = self.generate_filename(file_path, content)
        result['new_name'] = new_name
        new_path = file_path.parent / new_name

        if not self.dry_run:
            try:
                file_path.rename(new_path)
                result['status'] = RenameStatus.RENAMED
                self.stats['renamed'] += 1
            except FileExistsError:
                # Concurrent collision: resolve and retry once
                new_path = resolve_collision(new_path)
                new_name = new_path.name
                result['new_name'] = new_name
                try:
                    file_path.rename(new_path)
                    result['status'] = RenameStatus.RENAMED
                    self.stats['renamed'] += 1
                except Exception as e:
                    result['status'] = RenameStatus.ERROR
                    result['error'] = str(e)
                    self.stats['errors'] += 1
            except Exception as e:
                result['status'] = RenameStatus.ERROR
                result['error'] = str(e)
                self.stats['errors'] += 1
        else:
            result['status'] = RenameStatus.WOULD_RENAME
            self.stats['renamed'] += 1

        return result

    def process_directory(self, source_dir: Path, recursive: bool = False):
        """Process all images in a directory."""
        print(f"\n{'=' * 60}")
        print(f"Image Content Renamer {'(DRY RUN)' if self.dry_run else ''}")
        print(f"{'=' * 60}\n")

        if not CLIP_AVAILABLE:
            print("Error: CLIP not available. Install torch and transformers.")
            return

        print(f"Scanning: {source_dir}")
        print(f"Recursive: {recursive}\n")

        # Find all image files
        if recursive:
            seen: set[Path] = set()
            files = []
            for ext in self.IMAGE_EXTENSIONS:
                for pattern in (f"*{ext}", f"*{ext.upper()}"):
                    for f in source_dir.rglob(pattern):
                        if f not in seen:
                            seen.add(f)
                            files.append(f)
        else:
            files = [f for f in source_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in self.IMAGE_EXTENSIONS]

        self.stats['total'] = len(files)
        print(f"Total image files: {len(files)}")

        # Filter for generic filenames
        generic_files = [f for f in files if self.should_rename(f.name)]
        print(f"Generic filenames to process: {len(generic_files)}\n")

        for i, file_path in enumerate(generic_files, 1):
            print(f"[{i}/{len(generic_files)}] {file_path.name}")
            result = self.rename_file(file_path)
            self._print_result(result)

        # Print summary
        self._print_summary()

    def _print_result(self, result: dict) -> None:
        """Dispatch result to the appropriate status formatter."""
        status = result['status']
        if status in (RenameStatus.RENAMED, RenameStatus.WOULD_RENAME):
            prefix = "  → Would rename:" if status == RenameStatus.WOULD_RENAME else "  ✓ Renamed:"
            print(f"{prefix} {result['original']} → {result['new_name']}")
            print(f"    Content: {result['content']} ({result['confidence']:.1%})")
            self._print_all_scores(result.get('all_scores', {}), result['content'])
        elif status == RenameStatus.SKIPPED:
            print(f"  ⊘ Skipped: {result['error']}")
        elif status == RenameStatus.LOW_CONFIDENCE:
            print(f"  ⊘ Low confidence: {result['content']} ({result['confidence']:.1%})")
            self._print_all_scores(result.get('all_scores', {}), result.get('content'))
        elif status == RenameStatus.NO_CONTENT:
            print("  ⚠ No content detected")
        elif status == RenameStatus.ERROR:
            print(f"  ✗ Error: {result['error']}")

    @staticmethod
    def _print_all_scores(all_scores: dict[str, float], winner: str | None) -> None:
        """Print ranked confidence scores for all matched categories."""
        if not all_scores:
            return
        ranked = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
        # Winner label may be "category_subcategory"; match on prefix too.
        winner_base = winner.split('_')[0] if winner else None
        parts = []
        for cat, score in ranked:
            is_winner = cat == winner or cat == winner_base
            marker = "*" if is_winner else " "
            parts.append(f"{marker}{cat}: {score:.0%}")
        print(f"    Scores: {' | '.join(parts)}")

    def _print_summary(self):
        """Print processing summary."""
        print(f"\n{'=' * 60}")
        print("Renaming Summary")
        print(f"{'=' * 60}\n")
        print(f"Total image files: {self.stats['total']}")
        print(f"Successfully renamed: {self.stats['renamed']}")
        print(f"Skipped: {self.stats['skipped']}")
        print(f"No content detected: {self.stats['no_content']}")
        print(f"Errors: {self.stats['errors']}")

        if self.dry_run:
            print(f"\n⚠️  This was a DRY RUN - no files were renamed")


def main():
    parser = argparse.ArgumentParser(
        description="Rename images based on visual content analysis using CLIP"
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulate renaming without actually renaming files")
    parser.add_argument("--source", type=str, default="~/Documents",
                       help="Source directory to scan (default: ~/Documents)")
    parser.add_argument("--recursive", action="store_true",
                       help="Recursively scan subdirectories")
    parser.add_argument("--file", type=str,
                       help="Process a single file instead of directory")

    args = parser.parse_args()

    renamer = ImageContentRenamer(dry_run=args.dry_run)

    if args.file:
        file_path = Path(args.file).expanduser()
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            return
        print(f"\nAnalyzing: {file_path.name}")
        result = renamer.rename_file(file_path)
        if result['content']:
            print(f"Content: {result['content']} ({result['confidence']:.1%})")
        if result['new_name']:
            print(f"New name: {result['new_name']}")
    else:
        source_dir = Path(args.source).expanduser()
        if not source_dir.exists():
            print(f"Error: Directory not found: {source_dir}")
            return
        renamer.process_directory(source_dir, recursive=args.recursive)


if __name__ == "__main__":
    main()
