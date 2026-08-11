#!/usr/bin/env python3
"""Measure OCR recall on text-bearing HEIC files.

Runs both OCR backends (easyocr, docTR) against a directory of HEIC images,
forcing OCR to run on every file regardless of the CLIP gate, and reports the
fraction from which text was extracted.

This is the measurement the HEIC decode fix (2026-08-11) needed but never got:
the 12 unit tests verify the *hand-off shape* (an ndarray reaches each backend
instead of a file path), not whether the backends return usable text.

Why "force OCR regardless of gate"
------------------------------------
The CLIP OCR gate (--ocr-clip-topk K=3) skips OCR for images whose CLIP labels
do not include a text-bearing category.  On a photo-heavy HEIC corpus the gate
would skip most files, making recall look low regardless of the decode fix.
The recall question is specifically "given that OCR runs, does it extract text?"
-- so the gate must be bypassed for the measurement to be informative.

After collecting results, run eval_ocr_gate.py with a HEIC-only corpus spec to
separately measure how often the gate correctly keeps vs skips OCR on HEICs.

Usage
-----
    # All files in the directory are assumed to be text-bearing:
    python scripts/eval_heic_ocr_recall.py --source DIR

    # Provide ground truth to distinguish text-bearing from photo-only HEICs:
    python scripts/eval_heic_ocr_recall.py --source DIR \\
        --ground-truth labels.json

    # Write a JSON results file:
    python scripts/eval_heic_ocr_recall.py --source DIR --json results/heic_recall.json

Ground-truth JSON format
------------------------
A JSON object mapping file basename (case-insensitive) to bool:

    {
      "IMG_1234.HEIC": true,
      "photo_beach.heic": false
    }

true  = the file contains readable text (should produce OCR output)
false = the file is text-free (OCR output is not expected)

Files not present in the map are treated as text-bearing (assumed to have text)
unless --skip-unlabeled is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.constants import HEIC_HEIF_EXTENSIONS  # noqa: E402
from shared.ocr_easyocr import (  # noqa: E402
    EASYOCR_AVAILABLE,
    extract_text_easyocr,
)
from shared.ocr_classifier import (  # noqa: E402
    OCR_AVAILABLE,
    extract_ocr_text,
)


@dataclass
class FileResult:
    path: Path
    text_bearing: bool  # ground-truth label
    easyocr_text: Optional[str]
    easyocr_elapsed_ms: float
    doctr_text: Optional[str]
    doctr_elapsed_ms: float

    @property
    def any_text(self) -> bool:
        return bool(self.easyocr_text or self.doctr_text)

    @property
    def easyocr_found(self) -> bool:
        return bool(self.easyocr_text)

    @property
    def doctr_found(self) -> bool:
        return bool(self.doctr_text)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "text_bearing": self.text_bearing,
            "easyocr_text": self.easyocr_text,
            "easyocr_elapsed_ms": round(self.easyocr_elapsed_ms, 1),
            "doctr_text": self.doctr_text,
            "doctr_elapsed_ms": round(self.doctr_elapsed_ms, 1),
            "any_text": self.any_text,
        }


@dataclass
class Summary:
    n_total: int = 0
    n_text_bearing: int = 0
    n_photo_only: int = 0
    # recalls are over text-bearing files only
    easyocr_hits: int = 0
    doctr_hits: int = 0
    either_hits: int = 0
    # false positives: text found on labeled photo-only files
    easyocr_fp: int = 0
    doctr_fp: int = 0
    # timing
    easyocr_total_ms: float = 0.0
    doctr_total_ms: float = 0.0
    file_results: list[FileResult] = field(default_factory=list)

    def record(self, r: FileResult) -> None:
        self.n_total += 1
        self.file_results.append(r)
        self.easyocr_total_ms += r.easyocr_elapsed_ms
        self.doctr_total_ms += r.doctr_elapsed_ms
        if r.text_bearing:
            self.n_text_bearing += 1
            if r.easyocr_found:
                self.easyocr_hits += 1
            if r.doctr_found:
                self.doctr_hits += 1
            if r.any_text:
                self.either_hits += 1
        else:
            self.n_photo_only += 1
            if r.easyocr_found:
                self.easyocr_fp += 1
            if r.doctr_found:
                self.doctr_fp += 1

    def recall(self, hits: int) -> float:
        return hits / self.n_text_bearing if self.n_text_bearing else 0.0

    def print_report(self) -> None:
        tb = self.n_text_bearing
        po = self.n_photo_only
        print("\nHEIC OCR recall report")
        print(f"  files: {self.n_total}  text-bearing: {tb}  photo-only: {po}")
        if not tb:
            print("  (no text-bearing files — nothing to measure)")
            return
        print()
        print(
            f"  easyocr  recall: {self.recall(self.easyocr_hits):>6.1%}  "
            f"({self.easyocr_hits}/{tb})  "
            f"avg {self.easyocr_total_ms / self.n_total:.0f} ms/file  "
            f"{'(not installed)' if not EASYOCR_AVAILABLE else ''}"
        )
        print(
            f"  doctr    recall: {self.recall(self.doctr_hits):>6.1%}  "
            f"({self.doctr_hits}/{tb})  "
            f"avg {self.doctr_total_ms / self.n_total:.0f} ms/file  "
            f"{'(not installed)' if not OCR_AVAILABLE else ''}"
        )
        print(
            f"  either   recall: {self.recall(self.either_hits):>6.1%}  "
            f"({self.either_hits}/{tb})"
        )
        if po:
            print()
            print(f"  easyocr  false-positives: {self.easyocr_fp}/{po}")
            print(f"  doctr    false-positives: {self.doctr_fp}/{po}")

        missed = [r for r in self.file_results if r.text_bearing and not r.any_text]
        if missed:
            print(f"\n  text-bearing files with no OCR output ({len(missed)}):")
            for r in missed:
                print(f"    {r.path.name}")

    def to_dict(self) -> dict:
        tb = self.n_text_bearing
        return {
            "n_total": self.n_total,
            "n_text_bearing": tb,
            "n_photo_only": self.n_photo_only,
            "easyocr_recall": self.recall(self.easyocr_hits),
            "doctr_recall": self.recall(self.doctr_hits),
            "either_recall": self.recall(self.either_hits),
            "easyocr_fp": self.easyocr_fp,
            "doctr_fp": self.doctr_fp,
            "easyocr_available": EASYOCR_AVAILABLE,
            "doctr_available": OCR_AVAILABLE,
            "files": [r.to_dict() for r in self.file_results],
        }


def load_ground_truth(path: Optional[str]) -> dict[str, bool]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"ground-truth file must be a JSON object, got {type(data).__name__}")
    return {k.lower(): bool(v) for k, v in data.items()}


def gather_heic_files(source: Path) -> list[Path]:
    return sorted(
        p
        for p in source.rglob("*")
        if p.suffix.lower() in HEIC_HEIF_EXTENSIONS and not p.name.startswith(".")
    )


def run_easyocr(path: Path, max_chars: int) -> tuple[Optional[str], float]:
    if not EASYOCR_AVAILABLE:
        return None, 0.0
    t0 = time.perf_counter()
    text = extract_text_easyocr(path, max_chars=max_chars)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return text, elapsed_ms


def run_doctr(path: Path, max_chars: int) -> tuple[Optional[str], float]:
    if not OCR_AVAILABLE:
        return None, 0.0
    t0 = time.perf_counter()
    text = extract_ocr_text(path, max_chars=max_chars)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return text, elapsed_ms


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Measure OCR recall on text-bearing HEIC files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage")[0].rstrip(),
    )
    p.add_argument("--source", required=True, help="Directory containing HEIC files")
    p.add_argument(
        "--ground-truth",
        dest="ground_truth",
        help="JSON file mapping basename→bool (true=text-bearing); see script docstring",
    )
    p.add_argument(
        "--skip-unlabeled",
        action="store_true",
        help="Skip files absent from the ground-truth map (default: treat as text-bearing)",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=500,
        help="Truncate extracted text at this many characters (0=no limit, default 500)",
    )
    p.add_argument("--json", dest="json_out", help="Write results JSON to this path")
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-file OCR output",
    )
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    source = Path(args.source).expanduser()
    if not source.exists():
        print(f"error: source directory does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    gt = load_ground_truth(args.ground_truth)
    files = gather_heic_files(source)
    if not files:
        print(f"No HEIC files found under {source}")
        return

    print(f"Found {len(files)} HEIC file(s) under {source}")
    if not EASYOCR_AVAILABLE:
        print("  easyocr not installed — easyocr column will be empty")
    if not OCR_AVAILABLE:
        print("  doctr not installed — doctr column will be empty")
    print()

    summary = Summary()
    for path in files:
        key = path.name.lower()
        if gt:
            if key in gt:
                text_bearing = gt[key]
            elif args.skip_unlabeled:
                print(f"  skip (unlabeled): {path.name}")
                continue
            else:
                text_bearing = True  # assume text-bearing by default
        else:
            text_bearing = True

        easyocr_text, easyocr_ms = run_easyocr(path, args.max_chars)
        doctr_text, doctr_ms = run_doctr(path, args.max_chars)

        result = FileResult(
            path=path,
            text_bearing=text_bearing,
            easyocr_text=easyocr_text,
            easyocr_elapsed_ms=easyocr_ms,
            doctr_text=doctr_text,
            doctr_elapsed_ms=doctr_ms,
        )
        summary.record(result)

        if args.verbose:
            label = "text" if text_bearing else "photo"
            print(f"  [{label}] {path.name}")
            if easyocr_text:
                snippet = easyocr_text[:80].replace("\n", " ")
                print(f"    easyocr: {snippet!r}")
            else:
                print("    easyocr: (no text)")
            if doctr_text:
                snippet = doctr_text[:80].replace("\n", " ")
                print(f"    doctr:   {snippet!r}")
            else:
                print("    doctr:   (no text)")

    summary.print_report()

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary.to_dict(), indent=2))
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
