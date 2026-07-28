#!/usr/bin/env python3
"""Equalize encoding across the scene-probe corpus so format can't proxy for class.

The corpus accumulated its classes from different sources, and the sources are
distinguishable from the pixels alone: ``place/`` is 100% JPEG at 256px (Places365
samples), while the hand-collected ``graphic/`` images are mostly PNG at ~1536px.
That makes file format and resolution partially predictive of the label, so a
probe can score well by keying on the nuisance variable rather than on scene
content. Grommelt et al. (arXiv:2403.17608) measured exactly this on
generated-image detectors -- their GenImage real half is JPEG, the fake half PNG
-- and found ~11pp of apparent cross-generator skill evaporated once compression
and dimensions were equalized. Their prescription is what this script implements:
draw every class through the same encoder at the same size.

Normalization: decode, resize so the longest side is exactly
``_TARGET_LONGEST_SIDE``, re-encode as JPEG at ``_JPEG_QUALITY``. Every image then
carries the same compression signature and the same dimension scale. 256px is
chosen because CLIP ViT-B-32 preprocesses to 224x224 -- resolution above ~256 never
reaches the model, so the downscale costs the embedding essentially nothing while
collapsing a 206..2886px spread into one value.

Output goes to a parallel tree (``results/scene_labels_norm/``) rather than over
the source: four of the five class dirs hold gitignored personal images with no
other copy in the repo. Pass ``--in-place`` to overwrite instead.

The pass reports an **encoding-leakage audit** before and after: a logistic
regression fit on encoding metadata *only* (format, dimensions, aspect, file
size, bytes-per-pixel -- no pixels), scored against the majority-class baseline.
If that model beats the baseline, the label is partly recoverable from encoding.
Driving it down to baseline is the point of the pass.

    python scripts/normalize_scene_corpus.py                 # audit + write norm tree
    python scripts/normalize_scene_corpus.py --audit-only    # measure, write nothing
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _ROOT / "results/scene_labels"
_DST_ROOT = _ROOT / "results/scene_labels_norm"
_CLASSES = ("neither", "interior", "exterior", "place", "graphic")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

_TARGET_LONGEST_SIDE = 256  # CLIP ViT-B-32 sees 224x224; above ~256 is discarded
_JPEG_QUALITY = 90
_AUDIT_FOLDS = 5
_SEED = 0

# Encoding formats scored in the leakage audit; anything else lands in "other".
_AUDIT_FORMATS = ("JPEG", "PNG", "WEBP")


def _iter_images(class_dir: Path) -> List[Path]:
    return sorted(
        p for p in class_dir.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )


def _encoding_features(path: Path) -> Optional[List[float]]:
    """Metadata-only feature row: no pixel content, purely how the file is stored."""
    previous_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None  # oversized images must still be audited
        with Image.open(path) as img:
            fmt, (width, height) = img.format, img.size
    except Exception:
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
    if not width or not height:
        return None
    nbytes = path.stat().st_size
    onehot = [1.0 if fmt == f else 0.0 for f in _AUDIT_FORMATS]
    onehot.append(0.0 if fmt in _AUDIT_FORMATS else 1.0)
    return onehot + [
        float(width),
        float(height),
        float(max(width, height)),
        float(min(width, height)),
        width / height,
        float(nbytes),
        nbytes / (width * height),
    ]


def audit_leakage(root: Path) -> Optional[Tuple[float, float, int]]:
    """How well can class be predicted from encoding metadata alone?

    Returns ``(accuracy, majority_baseline, n)``. Accuracy at or below the
    baseline means encoding carries no usable class signal.
    """
    rows: List[List[float]] = []
    labels: List[int] = []
    for idx, name in enumerate(_CLASSES):
        class_dir = root / name
        if not class_dir.is_dir():
            continue
        for path in _iter_images(class_dir):
            feats = _encoding_features(path)
            if feats is not None:
                rows.append(feats)
                labels.append(idx)
    if len(set(labels)) < 2:
        return None

    features = np.asarray(rows, dtype=float)
    target = np.asarray(labels)
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=_SEED)),
        ]
    )
    acc = float(cross_val_score(model, features, target, cv=_AUDIT_FOLDS).mean())
    base = float(
        cross_val_score(
            DummyClassifier(strategy="most_frequent"), features, target, cv=_AUDIT_FOLDS
        ).mean()
    )
    return acc, base, len(target)


def _report(label: str, result: Optional[Tuple[float, float, int]]) -> None:
    if result is None:
        print(f"  {label}: not enough data")
        return
    acc, base, n = result
    lift = acc - base
    verdict = "LEAKY" if lift > 0.05 else "clean"
    print(
        f"  {label:<8s} encoding-only accuracy {acc:.3f} vs majority baseline "
        f"{base:.3f}  (lift {lift:+.3f}, n={n}) -> {verdict}"
    )


def normalize_image(src: Path, dst: Path) -> bool:
    """Decode, downscale to the common size, re-encode at the common quality.

    Pillow's >178M-pixel bomb guard raises during ``convert()``/``resize()`` on
    oversized corpus images (a full-bleed event map hit it at 194M px), which
    would silently drop them from the normalized tree. The guard is lifted for
    the decode and restored after — the same trade
    ``CLIPClassifier._thumbnail_oversized`` makes for the production path. Not
    thread-safe (global mutation); this pass is single-threaded.
    """
    previous_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(src) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            scale = _TARGET_LONGEST_SIDE / float(max(width, height))
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = rgb.resize(size, Image.Resampling.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            resized.save(dst, "JPEG", quality=_JPEG_QUALITY)
        return True
    except Exception as exc:
        print(f"    {src.name}: {type(exc).__name__} {exc}", file=sys.stderr)
        return False
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", default=str(_SRC_ROOT), help="source corpus root")
    ap.add_argument("--dst", default=str(_DST_ROOT), help="normalized output root")
    ap.add_argument("--in-place", action="store_true", help="overwrite the source corpus")
    ap.add_argument("--audit-only", action="store_true", help="measure leakage, write nothing")
    args = ap.parse_args(argv)

    src_root = Path(args.src)
    dst_root = src_root if args.in_place else Path(args.dst)

    print("Encoding-leakage audit — can class be predicted from file metadata alone?")
    before = audit_leakage(src_root)
    _report("before", before)

    if args.audit_only:
        return 0

    if not args.in_place and dst_root.exists():
        shutil.rmtree(dst_root)

    print(
        f"\nNormalizing -> {dst_root}  (JPEG q{_JPEG_QUALITY}, longest side {_TARGET_LONGEST_SIDE})"
    )
    counts: Dict[str, int] = {}
    for name in _CLASSES:
        class_dir = src_root / name
        if not class_dir.is_dir():
            continue
        written = 0
        for path in _iter_images(class_dir):
            dst = (dst_root / name / path.relative_to(class_dir)).with_suffix(".jpg")
            if normalize_image(path, dst):
                written += 1
                if args.in_place and path.suffix.lower() != ".jpg":
                    path.unlink()  # the re-encode landed at .jpg; drop the original
        counts[name] = written
        print(f"  {name:9s} {written:4d}")

    print("\nRe-audit after normalization:")
    _report("after", audit_leakage(dst_root))
    print(f"\nTotal {sum(counts.values())} images.")
    if not args.in_place:
        flags = " ".join(f"--{n} {dst_root / n}" for n in _CLASSES if counts.get(n))
        print("\nGather from the normalized tree:")
        print(f"  python scripts/prototype_scene_probe.py gather {flags}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
