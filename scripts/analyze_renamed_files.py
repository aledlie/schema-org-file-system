#!/usr/bin/env python3
"""
Analyze renamed image files to generate descriptions using OCR and CLIP.
Identifies files that match the renaming pattern and provides content descriptions.
"""

import os
import sys
import re
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add src directory to path (portable)
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# OCR imports
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True

    # HEIC support
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: OCR not available. Install pytesseract, Pillow")

# Vision imports
try:
    from transformers import CLIPProcessor, CLIPModel
    import torch
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    print("Warning: Vision analysis not available. Install transformers, torch")


class RenamedFileAnalyzer:
    """Analyzes renamed files to generate descriptions."""

    # Pattern for files renamed by image_renamer_metadata.py
    # Format: YYYYMMDD_HHMMSS[_N].ext or YYYYMMDD_Location_HHMMSS[_N].ext
    RENAMED_PATTERNS = [
        r'^\d{8}_\d{6}(_\d+)?\.(jpg|jpeg|png|webp|gif|bmp|heic)$',  # 20190129_100453.png
        r'^\d{8}_[A-Za-z_]+_\d{6}(_\d+)?\.(jpg|jpeg|png|webp|gif|bmp|heic)$',  # 20190129_NewYork_100453.png
        r'^Screenshot_.*\.(jpg|jpeg|png|webp|gif|bmp|heic)$',  # Screenshot_*.png
    ]

    # CLIP categories for image classification
    CLIP_CATEGORIES = [
        # Scene types
        "a photo of a landscape or nature scene",
        "a photo of a cityscape or urban scene",
        "a photo of an interior room",
        "a photo of food or a meal",
        "a photo of people or portrait",
        "a photo of an animal or pet",
        "a photo of a document or text",
        "a photo of artwork or illustration",
        "a photo of a product or object",
        "a photo of a vehicle or transportation",
        "a screenshot of a computer screen",
        "a screenshot of a mobile phone",
        "a photo of a building or architecture",
        "a photo of an event or celebration",
        "a photo of sports or physical activity",
        "a photo of a game or entertainment",
        "a diagram or chart",
        "a meme or social media image",
        "a logo or brand image",
        "abstract art or pattern",
    ]

    def __init__(self):
        """Initialize analyzer with OCR and CLIP models."""
        self.ocr_available = OCR_AVAILABLE
        self.vision_available = VISION_AVAILABLE
        self.model = None
        self.processor = None
        self.stats = defaultdict(int)

        if self.vision_available:
            try:
                print("Loading CLIP model for image analysis...")
                self.model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
                self.processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
                print("CLIP model loaded successfully")
            except Exception as e:
                print(f"Warning: Could not load CLIP model: {e}")
                self.vision_available = False

    def is_renamed_file(self, filename: str) -> bool:
        """Check if filename matches renamed pattern."""
        for pattern in self.RENAMED_PATTERNS:
            if re.match(pattern, filename, re.IGNORECASE):
                return True
        return False

    def extract_ocr_text(self, image_path: Path, max_chars: int = 500) -> Optional[str]:
        """Extract text from image using OCR."""
        if not self.ocr_available:
            return None

        try:
            img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')

            text = pytesseract.image_to_string(img, timeout=10)

            # Clean up text
            text = ' '.join(text.split())

            if len(text) > max_chars:
                text = text[:max_chars] + "..."

            return text if text.strip() else None

        except Exception as e:
            return None

    def classify_with_clip(self, image_path: Path) -> Optional[Dict[str, float]]:
        """Classify image content using CLIP."""
        if not self.vision_available or self.model is None:
            return None

        try:
            image = Image.open(image_path)

            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Process image with CLIP
            inputs = self.processor(
                text=self.CLIP_CATEGORIES,
                images=image,
                return_tensors="pt",
                padding=True
            )

            with torch.no_grad():
                outputs = self.model(**inputs)
                logits_per_image = outputs.logits_per_image
                probs = logits_per_image.softmax(dim=1)

            # Get results
            results = {}
            for i, category in enumerate(self.CLIP_CATEGORIES):
                # Clean up category name for display
                clean_name = category.replace("a photo of ", "").replace("a screenshot of ", "screenshot: ")
                results[clean_name] = float(probs[0][i])

            return results

        except Exception as e:
            return None

    def get_top_classifications(self, classifications: Dict[str, float], top_n: int = 3, threshold: float = 0.1) -> List[Tuple[str, float]]:
        """Get top classifications above threshold."""
        if not classifications:
            return []

        sorted_items = sorted(classifications.items(), key=lambda x: x[1], reverse=True)
        return [(k, v) for k, v in sorted_items[:top_n] if v >= threshold]

    def analyze_file(self, file_path: Path) -> Dict:
        """Analyze a single file and return description."""
        result = {
            'path': str(file_path),
            'filename': file_path.name,
            'size_kb': round(file_path.stat().st_size / 1024, 1),
            'ocr_text': None,
            'content_type': None,
            'confidence': None,
            'all_classifications': None,
            'description': None
        }

        # Run CLIP classification
        classifications = self.classify_with_clip(file_path)
        if classifications:
            top_classes = self.get_top_classifications(classifications)
            if top_classes:
                result['content_type'] = top_classes[0][0]
                result['confidence'] = round(top_classes[0][1], 3)
                result['all_classifications'] = [(k, round(v, 3)) for k, v in top_classes]
                self.stats['clip_analyzed'] += 1

        # Run OCR for text detection
        ocr_text = self.extract_ocr_text(file_path)
        if ocr_text:
            result['ocr_text'] = ocr_text
            self.stats['ocr_text_found'] += 1

        # Generate description
        description_parts = []

        if result['content_type']:
            description_parts.append(f"Content: {result['content_type']} ({result['confidence']:.0%} confident)")

        if result['ocr_text']:
            preview = result['ocr_text'][:100] + "..." if len(result['ocr_text']) > 100 else result['ocr_text']
            description_parts.append(f"Text detected: \"{preview}\"")

        result['description'] = " | ".join(description_parts) if description_parts else "No description available"

        return result

    def find_renamed_files(self, source_dir: str, recursive: bool = True) -> List[Path]:
        """Find all files matching renamed patterns."""
        source_path = Path(source_dir).expanduser()
        renamed_files = []

        image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.heic'}

        if recursive:
            all_files = []
            for ext in image_extensions:
                all_files.extend(source_path.rglob(f'*{ext}'))
                all_files.extend(source_path.rglob(f'*{ext.upper()}'))
        else:
            all_files = []
            for ext in image_extensions:
                all_files.extend(source_path.glob(f'*{ext}'))
                all_files.extend(source_path.glob(f'*{ext.upper()}'))

        for f in all_files:
            if self.is_renamed_file(f.name):
                renamed_files.append(f)

        return renamed_files

    def analyze_directory(self, source_dir: str, limit: int = None, output_file: str = None) -> Dict:
        """Analyze all renamed files in directory."""
        print(f"\n{'='*60}")
        print("Renamed File Content Analyzer")
        print(f"{'='*60}\n")

        # Find renamed files
        print(f"Scanning: {source_dir}")
        renamed_files = self.find_renamed_files(source_dir)

        print(f"Found {len(renamed_files)} renamed files to analyze\n")

        if limit:
            renamed_files = renamed_files[:limit]
            print(f"Limiting to first {limit} files\n")

        results = []

        for i, file_path in enumerate(renamed_files, 1):
            if i % 25 == 0 or i == 1:
                print(f"[{i}/{len(renamed_files)}] Analyzing...")

            try:
                result = self.analyze_file(file_path)
                results.append(result)
                self.stats['analyzed'] += 1

                # Print progress for each file
                if result['content_type']:
                    print(f"  {file_path.name}: {result['content_type']} ({result['confidence']:.0%})")

            except Exception as e:
                print(f"  Error analyzing {file_path.name}: {e}")
                self.stats['errors'] += 1

        # Generate summary
        summary = {
            'total_found': len(renamed_files),
            'analyzed': self.stats['analyzed'],
            'clip_analyzed': self.stats['clip_analyzed'],
            'ocr_text_found': self.stats['ocr_text_found'],
            'errors': self.stats['errors'],
            'results': results
        }

        # Save results
        if output_file:
            output_path = Path(output_file)

            if output_path.suffix == '.json':
                with open(output_path, 'w') as f:
                    json.dump(summary, f, indent=2)
            elif output_path.suffix == '.csv':
                with open(output_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['filename', 'path', 'size_kb', 'content_type', 'confidence', 'ocr_text', 'description'])
                    writer.writeheader()
                    for r in results:
                        writer.writerow({
                            'filename': r['filename'],
                            'path': r['path'],
                            'size_kb': r['size_kb'],
                            'content_type': r['content_type'],
                            'confidence': r['confidence'],
                            'ocr_text': r['ocr_text'],
                            'description': r['description']
                        })

            print(f"\nResults saved to: {output_path}")

        return summary

    def print_summary(self, summary: Dict):
        """Print analysis summary."""
        print(f"\n{'='*60}")
        print("Analysis Summary")
        print(f"{'='*60}\n")

        print(f"Total renamed files found: {summary['total_found']}")
        print(f"Successfully analyzed: {summary['analyzed']}")
        print(f"CLIP classifications: {summary['clip_analyzed']}")
        print(f"OCR text detected: {summary['ocr_text_found']}")
        print(f"Errors: {summary['errors']}")

        # Content type breakdown
        if summary['results']:
            content_types = defaultdict(int)
            for r in summary['results']:
                if r['content_type']:
                    content_types[r['content_type']] += 1

            if content_types:
                print(f"\nContent Type Breakdown:")
                for ctype, count in sorted(content_types.items(), key=lambda x: x[1], reverse=True)[:10]:
                    print(f"  {ctype}: {count}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Analyze renamed image files using OCR and CLIP'
    )
    parser.add_argument(
        '--source',
        default='~/Documents',
        help='Source directory to scan (default: ~/Documents)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of files to analyze'
    )
    parser.add_argument(
        '--output',
        default=str(Path(__file__).parent.parent / 'results' / 'renamed_files_analysis.json'),
        help='Output file (JSON or CSV)'
    )

    args = parser.parse_args()

    # Create analyzer
    analyzer = RenamedFileAnalyzer()

    # Analyze files
    summary = analyzer.analyze_directory(
        source_dir=args.source,
        limit=args.limit,
        output_file=args.output
    )

    # Print summary
    analyzer.print_summary(summary)


if __name__ == '__main__':
    main()
