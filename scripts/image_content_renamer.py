#!/usr/bin/env python3
"""
Image Content Renamer - Rename images based on visual content analysis.

Uses CLIP vision model to analyze image content and generate descriptive filenames.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    pass

from shared.clip_utils import CLIPClassifier, CLIP_AVAILABLE
from shared.constants import IMAGE_EXTENSIONS_WIDE
from shared.file_ops import resolve_collision
from shared.ocr_utils import extract_ocr_text, is_ocr_available

from src.classifiers.content_classifier import ContentClassifier


_EXIF_TAG_DATETIME_ORIGINAL = 36867  # DateTimeOriginal
_EXIF_TAG_DATETIME = 306             # DateTime


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
    _SCREENSHOT_KEYWORDS: dict[str, list[str]] = {
        'dashboard': [
            'daily requests', 'monthly cost', 'active alerts', 'latency',
            'trace pipeline', 'provider costs', 'dashboard', 'metrics',
            'monitoring', 'uptime', 'throughput',
        ],
        'terminal_session': [
            'completed:', 'next steps:', 'blocked by', 'npm run', 'git ',
            'curl ', 'http 2', 'signup successful', 'deploy', '$ ',
            'insert --', 'bash(', 'command:', 'exit code',
        ],
        'error_log': [
            'error:', 'traceback', 'exception', 'stack trace', 'fatal',
            'panic:', 'segfault', 'core dumped',
        ],
        'api_response': [
            '"jwt":', '"token":', '"userid":', 'http 200', 'http 201',
            'http 400', 'http 500', 'response:', 'status:',
            'content-type:', 'application/json',
        ],
    }

    # Minimum keyword hits for screenshot-specific matching
    _SCREENSHOT_MIN_HITS = 2

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
        self.classifier = None
        self.content_classifier = ContentClassifier()
        self.stats = {
            'total': 0,
            'renamed': 0,
            'skipped': 0,
            'errors': 0,
            'no_content': 0,
        }

        if CLIP_AVAILABLE:
            self.classifier = CLIPClassifier()

    # CLIP confidence below this triggers OCR fallback
    _CLIP_OCR_FALLBACK_THRESHOLD = 0.10

    def analyze_image(self, image_path: Path) -> tuple[str, float] | None:
        """
        Analyze image content using CLIP, falling back to OCR when
        CLIP confidence is below threshold.

        Returns:
            Tuple of (best_category, confidence) or None if analysis fails
        """
        clip_result = self._analyze_clip(image_path)

        if clip_result and clip_result[1] >= self._CLIP_OCR_FALLBACK_THRESHOLD:
            return clip_result

        # CLIP absent or low confidence — try OCR keyword classification
        ocr_result = self.classify_by_ocr(image_path)
        if ocr_result:
            print(f"  ↪ OCR fallback: {ocr_result[0]} ({ocr_result[1]:.0%})")
            return ocr_result

        return clip_result

    def _analyze_clip(self, image_path: Path) -> tuple[str, float] | None:
        """Run CLIP vision classification."""
        if not CLIP_AVAILABLE or self.classifier is None:
            return None

        try:
            top_category, top_confidence = self.classifier.top_match(
                image_path, self.CONTENT_CATEGORIES
            )

            if top_category in self.REFINEMENT_TERMS and top_confidence > 0.15:
                refined = self._refine_category(image_path, top_category)
                if refined:
                    return refined

            return (top_category, top_confidence)

        except Exception as e:
            print(f"  Error analyzing image: {e}")
            return None

    def classify_by_ocr(self, image_path: Path) -> tuple[str, float] | None:
        """Classify image by OCR text extraction.

        First checks screenshot-specific patterns (dashboard, terminal, etc.),
        then falls back to ContentClassifier's Schema.org keyword taxonomy.

        Returns (category, confidence) or None if OCR fails or no match.
        """
        if not is_ocr_available():
            return None

        text = extract_ocr_text(image_path, max_chars=1000)
        if not text:
            return None

        text_lower = text.lower()

        # Pass 1: screenshot-specific subcategories
        best_category = None
        best_hits = 0
        best_total = 0

        for category, keywords in self._SCREENSHOT_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text_lower)
            if hits > best_hits:
                best_hits = hits
                best_total = len(keywords)
                best_category = category

        if best_hits >= self._SCREENSHOT_MIN_HITS:
            return (best_category, best_hits / best_total)

        # Pass 2: Schema.org taxonomy via ContentClassifier
        category, subcategory, _company, _people = (
            self.content_classifier.classify_content(text, image_path.name)
        )

        if category != 'uncategorized':
            label = f"{category}_{subcategory}" if subcategory != 'other' else category
            # Approximate confidence from keyword density
            keyword_count = sum(
                1 for kw in self.content_classifier.patterns.get(category, {}).get('keywords', [])
                if kw in text_lower
            )
            total_keywords = len(
                self.content_classifier.patterns.get(category, {}).get('keywords', [])
            )
            confidence = keyword_count / total_keywords if total_keywords else 0.0
            return (label, confidence)

        return None

    def _refine_category(self, image_path: Path, category: str) -> tuple[str, float] | None:
        """Refine the category with more specific terms."""
        refinements = self.REFINEMENT_TERMS.get(category, [])
        if not refinements:
            return None

        top_term, top_confidence = self.classifier.top_match(image_path, refinements)

        if top_confidence > 0.3:
            return (top_term, top_confidence)
        return None

    def generate_filename(self, image_path: Path, content: str, confidence: float) -> str:
        """Generate a new filename based on content analysis."""
        # Clean up content for filename
        clean_content = content.lower().replace(" ", "_")
        clean_content = re.sub(r'[^a-z0-9_]', '', clean_content)

        # Try to get date from file metadata
        date_str = self._get_date_string(image_path)

        # Build filename
        ext = image_path.suffix.lower()

        if date_str:
            new_name = f"{date_str}_{clean_content}{ext}"
        else:
            new_name = f"{clean_content}{ext}"

        return new_name

    def _get_date_string(self, image_path: Path) -> str | None:
        """Extract date from image EXIF or file modification time."""
        try:
            with Image.open(image_path) as image:
                exif = image._getexif()
            if exif:
                for tag_id in [_EXIF_TAG_DATETIME_ORIGINAL, _EXIF_TAG_DATETIME]:
                    if tag_id in exif:
                        date_str = exif[tag_id]
                        dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                        return dt.strftime("%Y%m%d")
        except Exception:
            pass

        # Fallback to file modification time
        try:
            mtime = image_path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%Y%m%d")
        except Exception:
            return None

    def should_rename(self, filename: str) -> bool:
        """Check if file has a generic name that should be renamed."""
        stem = Path(filename).stem.lower()

        generic_patterns = [
            r'^screenshot[\s_-]',
            r'^img_\d+',
            r'^pxl_\d+',
            r'^dsc_?\d+',
            r'^dcim_\d+',
            r'^\d{8}_\d{6}',
            r'^\d+$',
            r'^[a-f0-9]{32}',
            r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            r'^image\d*$',
            r'^photo\d*$',
            r'^unnamed',
        ]

        for pattern in generic_patterns:
            if re.match(pattern, stem):
                return True
        return False

    def rename_file(self, file_path: Path) -> dict:
        """Analyze and rename a single image file."""
        result = {
            'original': file_path.name,
            'new_name': None,
            'content': None,
            'confidence': None,
            'status': 'pending',
            'error': None,
        }

        # Check if already has descriptive name
        if not self.should_rename(file_path.name):
            result['status'] = 'skipped'
            result['error'] = 'Already has descriptive name'
            self.stats['skipped'] += 1
            return result

        # Analyze content
        analysis = self.analyze_image(file_path)
        if not analysis:
            result['status'] = 'no_content'
            result['error'] = 'Could not analyze content'
            self.stats['no_content'] += 1
            return result

        content, confidence = analysis
        result['content'] = content
        result['confidence'] = confidence

        # Skip if confidence is too low
        if confidence < 0.10:
            result['status'] = 'low_confidence'
            result['error'] = f'Confidence too low: {confidence:.1%}'
            self.stats['skipped'] += 1
            return result

        # Generate new filename
        new_name = self.generate_filename(file_path, content, confidence)
        result['new_name'] = new_name

        # Handle duplicates
        new_path = file_path.parent / new_name
        if new_path.exists() and new_path != file_path:
            new_path = resolve_collision(new_path)
            new_name = new_path.name
            result['new_name'] = new_name

        # Perform rename
        if not self.dry_run:
            try:
                file_path.rename(new_path)
                result['status'] = 'renamed'
                self.stats['renamed'] += 1
            except Exception as e:
                result['status'] = 'error'
                result['error'] = str(e)
                self.stats['errors'] += 1
        else:
            result['status'] = 'would_rename'
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
            files = []
            for ext in self.IMAGE_EXTENSIONS:
                files.extend(source_dir.rglob(f"*{ext}"))
                files.extend(source_dir.rglob(f"*{ext.upper()}"))
        else:
            files = [f for f in source_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in self.IMAGE_EXTENSIONS]

        self.stats['total'] = len(files)
        print(f"Total image files: {len(files)}")

        # Filter for generic filenames
        generic_files = [f for f in files if self.should_rename(f.name)]
        print(f"Generic filenames to process: {len(generic_files)}\n")

        # Process each file
        for i, file_path in enumerate(generic_files, 1):
            print(f"[{i}/{len(generic_files)}] {file_path.name}")
            result = self.rename_file(file_path)

            if result['status'] in ('renamed', 'would_rename'):
                prefix = "  → Would rename:" if self.dry_run else "  ✓ Renamed:"
                print(f"{prefix} {result['original']} → {result['new_name']}")
                print(f"    Content: {result['content']} ({result['confidence']:.1%})")
            elif result['status'] == 'skipped':
                print(f"  ⊘ Skipped: {result['error']}")
            elif result['status'] == 'low_confidence':
                print(f"  ⊘ Low confidence: {result['content']} ({result['confidence']:.1%})")
            elif result['status'] == 'no_content':
                print(f"  ⚠ No content detected")
            elif result['status'] == 'error':
                print(f"  ✗ Error: {result['error']}")

        # Print summary
        self._print_summary()

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
