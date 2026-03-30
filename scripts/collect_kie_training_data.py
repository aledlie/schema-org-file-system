#!/usr/bin/env python3
"""Collect KIE training data from organized Financial/ documents.

Scans documents in the Financial/ folder, runs the OCR predictor to extract
word-level bounding boxes, and writes annotation JSON files to
``data/kie_annotations/`` for manual labeling.

Each annotation file contains::

    {
        "image_path": "relative/path/to/page.png",
        "words": [
            {"value": "ACME", "geometry": [[x1,y1],[x2,y2]], "class": ""},
            ...
        ]
    }

The ``class`` field is initially empty — fill it with one of the class names
from ``shared.kie_schema_mapping.KIE_FIELD_CLASSES`` to label the word for
training.

Usage::

    python scripts/collect_kie_training_data.py --source ~/Documents/Financial
    python scripts/collect_kie_training_data.py --source ~/Documents/Financial --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure scripts/shared is importable.
sys.path.insert(0, str(Path(__file__).parent))

from shared.ocr_utils import OCR_AVAILABLE, _get_predictor

try:
    from doctr.io import DocumentFile
except ImportError:
    DocumentFile = None

# Supported extensions for annotation collection.
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".heic"}
_PDF_EXTENSION = ".pdf"


def _extract_word_boxes(doc) -> list[dict]:
    """Run OCR and return word-level annotation dicts."""
    predictor = _get_predictor()
    result = predictor(doc)

    words: list[dict] = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    geometry = [list(pt) for pt in word.geometry] if hasattr(word, "geometry") else []
                    words.append({
                        "value": word.value,
                        "confidence": round(word.confidence, 4),
                        "geometry": geometry,
                        "class": "",  # to be labeled manually
                    })
    return words


def collect(source: Path, output_dir: Path, limit: int) -> int:
    """Collect annotations from *source* into *output_dir*.

    Returns the number of files processed.
    """
    if not OCR_AVAILABLE or DocumentFile is None:
        print("Error: docTR is not installed. Run: pip install python-doctr[torch]")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        f for f in source.rglob("*")
        if f.suffix.lower() in _IMAGE_EXTENSIONS | {_PDF_EXTENSION}
        and not f.name.startswith(".")
    )

    if limit:
        files = files[:limit]

    processed = 0
    for file_path in files:
        try:
            if file_path.suffix.lower() == _PDF_EXTENSION:
                doc = DocumentFile.from_pdf(str(file_path))
            else:
                doc = DocumentFile.from_images([str(file_path)])

            words = _extract_word_boxes(doc)
            if not words:
                print(f"  skip (no words): {file_path.name}")
                continue

            annotation = {
                "source_path": str(file_path),
                "image_path": file_path.name,
                "words": words,
            }

            out_name = file_path.stem + ".json"
            out_path = output_dir / out_name
            # Avoid overwriting existing annotations.
            if out_path.exists():
                out_path = output_dir / f"{file_path.stem}_{processed}.json"

            out_path.write_text(json.dumps(annotation, indent=2))
            processed += 1
            print(f"  [{processed}/{len(files)}] {file_path.name} -> {len(words)} words")

        except Exception as exc:
            print(f"  error: {file_path.name}: {exc}")

    print(f"\nDone. {processed} annotations written to {output_dir}")
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect KIE training data from organized documents.")
    parser.add_argument("--source", type=Path, default=Path.home() / "Documents" / "Financial",
                        help="Root folder to scan for documents (default: ~/Documents/Financial)")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "kie_annotations",
                        help="Output directory for annotation JSON files")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of files to process (0 = unlimited)")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: source directory does not exist: {args.source}")
        sys.exit(1)

    print(f"Collecting KIE annotations from: {args.source}")
    print(f"Output: {args.output_dir}")
    collect(args.source, args.output_dir, args.limit)


if __name__ == "__main__":
    main()
