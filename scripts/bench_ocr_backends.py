#!/usr/bin/env python3
"""Benchmark easyocr vs docTR accuracy on a labeled screenshot dataset.

Validates the premise behind the easyocr integration: that easyocr is more
accurate than docTR on screenshots and mobile UI text. Without this, the
unconditional easyocr preference in extract_screenshot_text() is unjustified.

Usage
-----
    # Run on a directory tree of labeled screenshots:
    python scripts/bench_ocr_backends.py --input ~/Documents/Screenshots/

    # Compare against a JSON label file (maps filename -> ground-truth-text):
    python scripts/bench_ocr_backends.py --input ~/testset/ --labels labels.json

    # Save results to JSON:
    python scripts/bench_ocr_backends.py --input ~/testset/ --output results/ocr_bench.json

Label file format
-----------------
JSON object mapping relative filenames to ground-truth text strings:
    {"screenshot_001.png": "Settings Notifications Do Not Disturb", ...}

When no label file is provided, the script measures throughput and text
yield (fraction of images that produced non-empty output) rather than
character-error-rate.

Output
------
Per-backend metrics printed to stdout:
    - images processed
    - yield % (images with non-empty text / total)
    - median / p95 latency (seconds per image)
    - char-error-rate (if labels provided)

The results inform whether to keep the unconditional easyocr preference,
switch to a fallback ordering, or gate by image characteristics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Allow running from project root without installing the package.
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# ---------------------------------------------------------------------------
# Character Error Rate (CER)
# ---------------------------------------------------------------------------

def _cer(ref: str, hyp: str) -> float:
    """Compute character-level Levenshtein distance / len(ref).

    Returns 0.0 when both strings are empty. Returns 1.0 when ref is empty
    but hyp is non-empty (full insertion error).
    """
    ref = ref.strip()
    hyp = (hyp or "").strip()
    if not ref and not hyp:
        return 0.0
    if not ref:
        return 1.0
    # Wagner-Fischer dynamic programming
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[m] / max(n, m)


# ---------------------------------------------------------------------------
# Backend wrappers
# ---------------------------------------------------------------------------

def _run_easyocr(image_path: Path) -> Optional[str]:
    from shared.ocr_easyocr import extract_text_easyocr
    return extract_text_easyocr(image_path)


def _run_doctr(image_path: Path) -> Optional[str]:
    from shared.ocr_classifier import extract_ocr_text
    return extract_ocr_text(image_path)


BACKENDS = {
    "easyocr": _run_easyocr,
    "doctr": _run_doctr,
}


# ---------------------------------------------------------------------------
# Metrics accumulator
# ---------------------------------------------------------------------------

class _Metrics:
    def __init__(self) -> None:
        self.total = 0
        self.yielded = 0  # produced non-empty text
        self.latencies: list[float] = []
        self.cer_values: list[float] = []

    def record(self, text: Optional[str], elapsed: float, ref: Optional[str]) -> None:
        self.total += 1
        self.latencies.append(elapsed)
        if text:
            self.yielded += 1
        if ref is not None:
            self.cer_values.append(_cer(ref, text or ""))

    def summary(self) -> dict:
        sorted_lat = sorted(self.latencies)
        n = len(sorted_lat)
        median = sorted_lat[n // 2] if n else 0.0
        p95 = sorted_lat[int(n * 0.95)] if n else 0.0
        result: dict = {
            "images": self.total,
            "yield_pct": round(100 * self.yielded / self.total, 1) if self.total else 0.0,
            "median_latency_s": round(median, 3),
            "p95_latency_s": round(p95, 3),
        }
        if self.cer_values:
            result["mean_cer"] = round(sum(self.cer_values) / len(self.cer_values), 4)
            result["median_cer"] = round(sorted(self.cer_values)[len(self.cer_values) // 2], 4)
        return result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _collect_images(input_dir: Path) -> list[Path]:
    images = [
        p for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    images.sort()
    return images


def _load_labels(labels_path: Optional[Path]) -> dict[str, str]:
    if labels_path is None:
        return {}
    with labels_path.open() as fh:
        return json.load(fh)


def run_benchmark(
    input_dir: Path,
    labels: dict[str, str],
    backends: list[str],
    limit: Optional[int],
) -> dict[str, dict]:
    images = _collect_images(input_dir)
    if limit:
        images = images[:limit]

    if not images:
        print(f"No images found under {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Benchmarking {len(images)} images from {input_dir}")

    results: dict[str, _Metrics] = {b: _Metrics() for b in backends}

    for img in images:
        ref = labels.get(img.name) or labels.get(str(img.relative_to(input_dir)))
        for backend in backends:
            fn = BACKENDS[backend]
            t0 = time.perf_counter()
            text = None
            try:
                text = fn(img)
            except Exception as exc:
                logger.warning("%s failed on %s: %s", backend, img.name, exc)
            elapsed = time.perf_counter() - t0
            results[backend].record(text, elapsed, ref if labels else None)

    return {b: m.summary() for b, m in results.items()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Benchmark easyocr vs docTR on a screenshot test set.",
    )
    p.add_argument("--input", required=True, type=Path,
                   help="Directory of screenshot images to test.")
    p.add_argument("--labels", type=Path, default=None,
                   help="JSON file mapping filename -> ground-truth text (enables CER).")
    p.add_argument("--output", type=Path, default=None,
                   help="Write JSON results to this path.")
    p.add_argument("--backends", nargs="+", default=list(BACKENDS),
                   choices=list(BACKENDS),
                   help="Which backends to benchmark (default: all).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of images (useful for quick smoke tests).")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    labels = _load_labels(args.labels)
    results = run_benchmark(args.input, labels, args.backends, args.limit)

    # Print table
    header = f"{'Backend':<12} {'Images':>8} {'Yield%':>8} {'Median(s)':>10} {'P95(s)':>8}"
    if labels:
        header += f" {'Mean CER':>10} {'Med CER':>9}"
    print(header)
    print("-" * len(header))
    for backend, m in results.items():
        row = (
            f"{backend:<12} {m['images']:>8} {m['yield_pct']:>7.1f}%"
            f" {m['median_latency_s']:>10.3f} {m['p95_latency_s']:>8.3f}"
        )
        if labels:
            row += f" {m.get('mean_cer', 'n/a'):>10} {m.get('median_cer', 'n/a'):>9}"
        print(row)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
