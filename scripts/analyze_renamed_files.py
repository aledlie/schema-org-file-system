#!/usr/bin/env python3
"""
Analyze renamed image files to generate descriptions using OCR and CLIP.
Identifies files that match the renaming pattern and provides content descriptions.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict

from shared.clip_utils import CLIP_AVAILABLE, CLIPClassifier
from shared.constants import CLIP_CATEGORY_PROMPTS, IMAGE_EXTENSIONS
from shared.ocr_classifier import extract_ocr_text, is_ocr_available


class RenamedFileAnalyzer:
    """Analyzes renamed files to generate descriptions."""

    # Pattern for files renamed by image_renamer_metadata.py
    # Format: YYYYMMDD_HHMMSS[_N].ext or YYYYMMDD_Location_HHMMSS[_N].ext
    RENAMED_PATTERNS = [
        r"^\d{8}_\d{6}(_\d+)?\.(jpg|jpeg|png|webp|gif|bmp|heic)$",  # 20190129_100453.png
        r"^\d{8}_[A-Za-z_]+_\d{6}(_\d+)?\.(jpg|jpeg|png|webp|gif|bmp|heic)$",  # 20190129_NewYork_100453.png  # noqa: E501
        r"^Screenshot_.*\.(jpg|jpeg|png|webp|gif|bmp|heic)$",  # Screenshot_*.png
    ]

    def __init__(self):
        """Initialize analyzer with OCR and CLIP models."""
        self.ocr_available = is_ocr_available()
        self.vision_available = CLIP_AVAILABLE
        self.classifier = None
        self.stats = defaultdict(int)

        if self.vision_available:
            try:
                self.classifier = CLIPClassifier()
            except Exception as e:
                print(f"Warning: Could not load CLIP model: {e}")
                self.vision_available = False

    def is_renamed_file(self, filename: str) -> bool:
        """Check if filename matches renamed pattern."""
        for pattern in self.RENAMED_PATTERNS:
            if re.match(pattern, filename, re.IGNORECASE):
                return True
        return False

    def classify_with_clip(self, image_path: Path) -> dict[str, float] | None:
        """Classify image content using CLIP."""
        if not self.vision_available or self.classifier is None:
            return None

        try:
            raw_results = self.classifier.classify_raw(image_path, CLIP_CATEGORY_PROMPTS)

            # Clean up category names for display
            results = {}
            for prompt, confidence in raw_results:
                clean_name = prompt.replace("a photo of ", "").replace(
                    "a screenshot of ", "screenshot: "
                )
                results[clean_name] = confidence

            return results

        except Exception:
            return None

    def get_top_classifications(
        self, classifications: dict[str, float], top_n: int = 3, threshold: float = 0.1
    ) -> list[tuple[str, float]]:
        """Get top classifications above threshold."""
        if not classifications:
            return []

        sorted_items = sorted(classifications.items(), key=lambda x: x[1], reverse=True)
        return [(k, v) for k, v in sorted_items[:top_n] if v >= threshold]

    def analyze_file(self, file_path: Path) -> Dict:
        """Analyze a single file and return description."""
        result = {
            "path": str(file_path),
            "filename": file_path.name,
            "size_kb": round(file_path.stat().st_size / 1024, 1),
            "ocr_text": None,
            "content_type": None,
            "confidence": None,
            "all_classifications": None,
            "description": None,
        }

        # Run CLIP classification
        classifications = self.classify_with_clip(file_path)
        if classifications:
            top_classes = self.get_top_classifications(classifications)
            if top_classes:
                result["content_type"] = top_classes[0][0]
                result["confidence"] = round(top_classes[0][1], 3)
                result["all_classifications"] = [(k, round(v, 3)) for k, v in top_classes]
                self.stats["clip_analyzed"] += 1

        # Run OCR for text detection
        ocr_text = extract_ocr_text(file_path)
        if ocr_text:
            result["ocr_text"] = ocr_text
            self.stats["ocr_text_found"] += 1

        # Generate description
        description_parts = []

        if result["content_type"]:
            description_parts.append(
                f"Content: {result['content_type']} ({result['confidence']:.0%} confident)"
            )

        if result["ocr_text"]:
            preview = (
                result["ocr_text"][:100] + "..."
                if len(result["ocr_text"]) > 100
                else result["ocr_text"]
            )
            description_parts.append(f'Text detected: "{preview}"')

        result["description"] = (
            " | ".join(description_parts) if description_parts else "No description available"
        )

        return result

    def find_renamed_files(self, source_dir: str, recursive: bool = True) -> list[Path]:
        """Find all files matching renamed patterns."""
        source_path = Path(source_dir).expanduser()
        renamed_files = []

        image_extensions = IMAGE_EXTENSIONS

        if recursive:
            all_files = []
            for ext in image_extensions:
                all_files.extend(source_path.rglob(f"*{ext}"))
                all_files.extend(source_path.rglob(f"*{ext.upper()}"))
        else:
            all_files = []
            for ext in image_extensions:
                all_files.extend(source_path.glob(f"*{ext}"))
                all_files.extend(source_path.glob(f"*{ext.upper()}"))

        for f in all_files:
            if self.is_renamed_file(f.name):
                renamed_files.append(f)

        return renamed_files

    def analyze_directory(
        self, source_dir: str, limit: int = None, output_file: str = None
    ) -> Dict:
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
                self.stats["analyzed"] += 1

                # Print progress for each file
                if result["content_type"]:
                    print(
                        f"  {file_path.name}: {result['content_type']} ({result['confidence']:.0%})"
                    )

            except Exception as e:
                print(f"  Error analyzing {file_path.name}: {e}")
                self.stats["errors"] += 1

        # Generate summary
        summary = {
            "total_found": len(renamed_files),
            "analyzed": self.stats["analyzed"],
            "clip_analyzed": self.stats["clip_analyzed"],
            "ocr_text_found": self.stats["ocr_text_found"],
            "errors": self.stats["errors"],
            "results": results,
        }

        # Save results
        if output_file:
            output_path = Path(output_file)

            if output_path.suffix == ".json":
                with open(output_path, "w") as f:
                    json.dump(summary, f, indent=2)
            elif output_path.suffix == ".csv":
                with open(output_path, "w", newline="") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=[
                            "filename",
                            "path",
                            "size_kb",
                            "content_type",
                            "confidence",
                            "ocr_text",
                            "description",
                        ],
                    )
                    writer.writeheader()
                    for r in results:
                        writer.writerow(
                            {
                                "filename": r["filename"],
                                "path": r["path"],
                                "size_kb": r["size_kb"],
                                "content_type": r["content_type"],
                                "confidence": r["confidence"],
                                "ocr_text": r["ocr_text"],
                                "description": r["description"],
                            }
                        )

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
        if summary["results"]:
            content_types = defaultdict(int)
            for r in summary["results"]:
                if r["content_type"]:
                    content_types[r["content_type"]] += 1

            if content_types:
                print("\nContent Type Breakdown:")
                for ctype, count in sorted(content_types.items(), key=lambda x: x[1], reverse=True)[
                    :10
                ]:
                    print(f"  {ctype}: {count}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze renamed image files using OCR and CLIP")
    parser.add_argument(
        "--source", default="~/Documents", help="Source directory to scan (default: ~/Documents)"
    )
    parser.add_argument("--limit", type=int, help="Limit number of files to analyze")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent.parent / "results" / "renamed_files_analysis.json"),
        help="Output file (JSON or CSV)",
    )

    args = parser.parse_args()

    # Create analyzer
    analyzer = RenamedFileAnalyzer()

    # Analyze files
    summary = analyzer.analyze_directory(
        source_dir=args.source, limit=args.limit, output_file=args.output
    )

    # Print summary
    analyzer.print_summary(summary)


if __name__ == "__main__":
    main()
