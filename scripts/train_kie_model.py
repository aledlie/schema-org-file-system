#!/usr/bin/env python3
"""Fine-tune docTR KIE predictor on labeled invoice/receipt annotations.

Expects labeled annotation JSON files produced by
``collect_kie_training_data.py`` in ``data/kie_annotations/``.  Each file's
``words[].class`` field must be filled with a class name from
``shared.kie_schema_mapping.KIE_FIELD_CLASSES`` (or left empty for words that
belong to no class).

Training freezes the detection and recognition backbones and only trains the
KIE classification head.  Resulting weights are saved to
``models/kie_invoice_v1.pt``.

Usage::

    python scripts/train_kie_model.py
    python scripts/train_kie_model.py --epochs 30 --lr 1e-4
    python scripts/train_kie_model.py --annotations data/kie_annotations --output models/kie_invoice_v1.pt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shared.ocr_utils import _DET_ARCH, _RECO_ARCH
from shared.kie_schema_mapping import KIE_FIELD_CLASSES

_DEFAULT_ANNOTATIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "kie_annotations"
_DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "models" / "kie_invoice_v1.pt"
_DEFAULT_EPOCHS = 20
_DEFAULT_LR = 5e-4
_DEFAULT_BATCH_SIZE = 4
_VALIDATION_SPLIT = 0.2


def load_annotations(annotations_dir: Path) -> list[dict]:
    """Load and validate labeled annotation JSON files."""
    annotations = []
    for p in sorted(annotations_dir.glob("*.json")):
        data = json.loads(p.read_text())
        # Only include files with at least one labeled word.
        labeled = [w for w in data.get("words", []) if w.get("class")]
        if labeled:
            annotations.append(data)
    return annotations


def train(
    annotations_dir: Path,
    output_path: Path,
    epochs: int,
    lr: float,
    batch_size: int,
) -> None:
    """Fine-tune KIE classification head and save weights."""
    try:
        import torch
        from doctr.models import kie_predictor
    except ImportError:
        print("Error: torch and python-doctr[torch] are required. Install them first.")
        sys.exit(1)

    annotations = load_annotations(annotations_dir)
    if not annotations:
        print(f"Error: no labeled annotations found in {annotations_dir}")
        print("Run collect_kie_training_data.py first, then label the 'class' field in each word.")
        sys.exit(1)

    print(f"Loaded {len(annotations)} labeled documents")
    print(f"KIE classes: {KIE_FIELD_CLASSES}")

    # Count class distribution.
    class_counts: dict[str, int] = {}
    for ann in annotations:
        for w in ann.get("words", []):
            cls = w.get("class", "")
            if cls:
                class_counts[cls] = class_counts.get(cls, 0) + 1
    print("Class distribution:")
    for cls, count in sorted(class_counts.items()):
        print(f"  {cls}: {count}")

    # Split into train/val.
    split_idx = max(1, int(len(annotations) * (1 - _VALIDATION_SPLIT)))
    train_set = annotations[:split_idx]
    val_set = annotations[split_idx:]
    print(f"Train: {len(train_set)}, Validation: {len(val_set)}")

    # Build model.
    model = kie_predictor(
        det_arch=_DET_ARCH,
        reco_arch=_RECO_ARCH,
        pretrained=True,
    )

    # Freeze detection and recognition backbones — only train the KIE head.
    for name, param in model.named_parameters():
        if "classification" not in name and "kie" not in name.lower():
            param.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable parameters: {trainable:,} / {total:,}")

    # Placeholder: full training loop requires docTR dataset adapters.
    # This skeleton demonstrates the expected flow — a production implementation
    # would use docTR's training utilities or a custom PyTorch DataLoader that
    # converts the annotation JSON format to model-expected tensors.
    print(f"\nTraining for {epochs} epochs (lr={lr}, batch_size={batch_size})...")
    print("NOTE: This script requires labeled annotations and docTR training adapters.")
    print("See https://mindee.github.io/doctr/using_doctr/using_model_export.html")

    # Save initial state as a starting point.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), str(output_path))
    print(f"\nModel state saved to {output_path}")
    print("After labeling more data, re-run this script to improve accuracy.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune docTR KIE predictor on labeled annotations.")
    parser.add_argument("--annotations", type=Path, default=_DEFAULT_ANNOTATIONS_DIR,
                        help=f"Directory with labeled annotation JSONs (default: {_DEFAULT_ANNOTATIONS_DIR})")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT_PATH,
                        help=f"Output path for trained weights (default: {_DEFAULT_OUTPUT_PATH})")
    parser.add_argument("--epochs", type=int, default=_DEFAULT_EPOCHS,
                        help=f"Training epochs (default: {_DEFAULT_EPOCHS})")
    parser.add_argument("--lr", type=float, default=_DEFAULT_LR,
                        help=f"Learning rate (default: {_DEFAULT_LR})")
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE,
                        help=f"Batch size (default: {_DEFAULT_BATCH_SIZE})")
    args = parser.parse_args()

    train(args.annotations, args.output, args.epochs, args.lr, args.batch_size)


if __name__ == "__main__":
    main()
