#!/usr/bin/env python3
"""Evaluate the CLIP-based OCR gate on a folder-labeled image corpus.

The gate (``organize-files content --ocr-clip-topk K``) skips OCR on an image
unless a text-bearing CLIP label ranks in its top-K labels. This tool measures
how well that ranking separates images that NEED OCR (documents, screenshots)
from text-free photos, so the K can be chosen against evidence rather than
guessed.

Ground truth is the folder each image already lives in — the organizer's own
past decisions. Directories are labeled text-bearing (OCR must run) or not.

Because cached CLIP scores are a near-uniform softmax (~0.05/label over 20
labels), absolute summed probability cannot separate the classes; the signal
is entirely in ranking. This tool therefore evaluates ranking formulations:

  top-k   keep OCR iff a text-bearing label is in the top-K CLIP labels
  margin  keep OCR iff max(text-label score) >= max(other score) - margin

Metrics per setting:
  recall = fraction of text-bearing images KEPT (OCR runs)   [want ~100%]
  skip   = fraction of text-free photos SKIPPED (OCR saved)  [the speed win]
  text_wrongly_skipped = text-bearing images that lost OCR    [the risk]

Usage
-----
    # Default corpus (the ~/Documents photo-library layout):
    python scripts/eval_ocr_gate.py

    # Custom corpus from JSON: [{"dir": "...", "text_bearing": true, "cap": 60}, ...]
    python scripts/eval_ocr_gate.py --corpus corpus.json --json results/gate_eval.json

Trust the top-k sweep to pick K; confirm the realized speed win with
scripts/profile_pipeline.py --ocr-clip-topk K.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.constants import CLIP_TEXT_BEARING_LABELS  # noqa: E402

IMG_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}

# Default corpus: folder = ground-truth label. text_bearing dirs hold images
# that genuinely need OCR; the rest are text-free photos where OCR is wasted.
_HOME = Path.home()
DEFAULT_CORPUS: List[dict] = [
    {"dir": _HOME / "Documents/Media/Photos/Screenshots", "text_bearing": True, "cap": 70},
    {"dir": _HOME / "Documents/Organization", "text_bearing": True, "cap": 60},
    {"dir": _HOME / "Documents/Media/Photos/Documents", "text_bearing": True, "cap": 20},
    {"dir": _HOME / "Documents/Media/Photos/Portraits", "text_bearing": False, "cap": 40},
    {"dir": _HOME / "Documents/Media/Photos/Stock", "text_bearing": False, "cap": 40},
    {"dir": _HOME / "Documents/Media/Photos/Products", "text_bearing": False, "cap": 40},
    {"dir": _HOME / "Documents/Media/Photos/Social", "text_bearing": False, "cap": 40},
    {"dir": _HOME / "Documents/Media/Photos/Other", "text_bearing": False, "cap": 40},
]

DEFAULT_TOPKS = (2, 3, 4, 5)
DEFAULT_MARGINS = (0.0, 0.0005, 0.001, 0.002, 0.003)


def load_corpus(path: Optional[str]) -> List[dict]:
    if not path:
        return DEFAULT_CORPUS
    specs = json.loads(Path(path).read_text())
    return [
        {
            "dir": Path(s["dir"]).expanduser(),
            "text_bearing": bool(s["text_bearing"]),
            "cap": int(s.get("cap", 0)) or None,
        }
        for s in specs
    ]


def gather(corpus: List[dict]) -> List[Tuple[Path, bool]]:
    items: List[Tuple[Path, bool]] = []
    for spec in corpus:
        root = Path(spec["dir"]).expanduser()
        if not root.exists():
            print(f"  (skip missing dir: {root})")
            continue
        found = sorted(
            p
            for p in root.rglob("*")
            if p.suffix.lower() in IMG_EXTS and not p.name.startswith(".")
        )
        cap = spec.get("cap")
        items += [(p, spec["text_bearing"]) for p in (found[:cap] if cap else found)]
    return items


def score_corpus(items: List[Tuple[Path, bool]], org) -> List[Tuple[Dict[str, float], bool]]:
    """Attach each image's CLIP label→score dict; drop images with no CLIP."""
    scored: List[Tuple[Dict[str, float], bool]] = []
    for path, is_text in items:
        clip = org._clip_scores_for_context(path)
        if clip:
            scored.append((clip, is_text))
    return scored


def confusion(
    scored: List[Tuple[Dict[str, float], bool]], keep_ocr: Callable[[Dict[str, float]], bool]
) -> dict:
    """keep_ocr(clip)->bool. Returns recall/skip and the two error counts."""
    text_kept = sum(1 for c, t in scored if t and keep_ocr(c))
    text_skipped = sum(1 for c, t in scored if t and not keep_ocr(c))
    photo_skipped = sum(1 for c, t in scored if not t and not keep_ocr(c))
    photo_kept = sum(1 for c, t in scored if not t and keep_ocr(c))
    n_text = text_kept + text_skipped
    n_photo = photo_skipped + photo_kept
    return {
        "recall": text_kept / n_text if n_text else 0.0,
        "skip": photo_skipped / n_photo if n_photo else 0.0,
        "text_wrongly_skipped": text_skipped,
        "photo_kept": photo_kept,
    }


def _topk_keep(labels: frozenset, k: int) -> Callable[[Dict[str, float]], bool]:
    def keep(clip: Dict[str, float]) -> bool:
        top = sorted(clip, key=lambda lbl: clip[lbl], reverse=True)[:k]
        return any(lbl in labels for lbl in top)

    return keep


def _margin_keep(labels: frozenset, margin: float) -> Callable[[Dict[str, float]], bool]:
    def keep(clip: Dict[str, float]) -> bool:
        max_text = max((s for lbl, s in clip.items() if lbl in labels), default=0.0)
        max_other = max((s for lbl, s in clip.items() if lbl not in labels), default=0.0)
        return max_text >= max_other - margin

    return keep


def evaluate(scored, labels, topks, margins) -> dict:
    n_text = sum(1 for _, t in scored if t)
    n_photo = sum(1 for _, t in scored if not t)
    topk_rows = {k: confusion(scored, _topk_keep(labels, k)) for k in topks}
    margin_rows = {m: confusion(scored, _margin_keep(labels, m)) for m in margins}

    def best_text_rank(clip: Dict[str, float]) -> int:
        order = sorted(clip, key=lambda lbl: clip[lbl], reverse=True)
        for i, lbl in enumerate(order):
            if lbl in labels:
                return i
        return len(order)

    def pctl(vals: List[int], q: float) -> float:
        vals = sorted(vals)
        return vals[int(q * (len(vals) - 1))] if vals else -1

    ranks_text = [best_text_rank(c) for c, t in scored if t]
    ranks_photo = [best_text_rank(c) for c, t in scored if not t]
    return {
        "n_scored": len(scored),
        "n_text": n_text,
        "n_photo": n_photo,
        "topk": topk_rows,
        "margin": margin_rows,
        "rank_p10_p50_p90": {
            "text": [pctl(ranks_text, 0.1), pctl(ranks_text, 0.5), pctl(ranks_text, 0.9)],
            "photo": [pctl(ranks_photo, 0.1), pctl(ranks_photo, 0.5), pctl(ranks_photo, 0.9)],
        },
    }


def print_report(res: dict, labels: frozenset) -> None:
    print(f"\nscored={res['n_scored']}  text-bearing={res['n_text']}  photo={res['n_photo']}")
    print(f"text-bearing CLIP labels ({len(labels)}): {sorted(labels)}\n")
    print("top-k gate (keep OCR iff a text label is in top-K):")
    print(f"  {'K':>3} {'recall':>8} {'skip':>8} {'text_skipped':>13} {'photo_kept':>11}")
    for k, r in res["topk"].items():
        print(
            f"  {k:>3} {r['recall']:>7.1%} {r['skip']:>7.1%} "
            f"{r['text_wrongly_skipped']:>13} {r['photo_kept']:>11}"
        )
    print("\nmargin gate (keep OCR iff max_text >= max_other - margin):")
    print(f"  {'margin':>7} {'recall':>8} {'skip':>8} {'text_skipped':>13} {'photo_kept':>11}")
    for m, r in res["margin"].items():
        print(
            f"  {m:>7.4f} {r['recall']:>7.1%} {r['skip']:>7.1%} "
            f"{r['text_wrongly_skipped']:>13} {r['photo_kept']:>11}"
        )
    rk = res["rank_p10_p50_p90"]
    print("\nrank of best text-bearing label (0=argmax); p10/p50/p90:")
    print(f"  text-bearing: {rk['text']}")
    print(f"  photos:       {rk['photo']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evaluate the CLIP OCR gate on a labeled corpus.")
    p.add_argument(
        "--corpus", help="JSON list of {dir, text_bearing, cap}; default = photo library"
    )
    p.add_argument(
        "--topk", type=int, nargs="+", default=list(DEFAULT_TOPKS), help="top-K values to sweep"
    )
    p.add_argument(
        "--margin",
        type=float,
        nargs="+",
        default=list(DEFAULT_MARGINS),
        help="margin values to sweep",
    )
    p.add_argument("--json", dest="json_out", help="Write the eval result JSON here")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    from file_organizer_content_based import ContentBasedFileOrganizer

    args = build_parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    items = gather(corpus)
    if not items:
        print("No labeled images found.")
        return
    org = ContentBasedFileOrganizer(base_path=None, enable_cost_tracking=False, db_path=None)
    scored = score_corpus(items, org)
    if not scored:
        print("No images produced CLIP scores (vision unavailable?).")
        return
    res = evaluate(scored, CLIP_TEXT_BEARING_LABELS, args.topk, args.margin)
    print_report(res, CLIP_TEXT_BEARING_LABELS)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        # JSON-safe: stringify margin float keys
        out = dict(res)
        out["margin"] = {f"{m:.4f}": v for m, v in res["margin"].items()}
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
