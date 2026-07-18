#!/usr/bin/env python3
"""Reusable profiler for the content-classification hot path.

Runs the unified (or legacy) scorer over a set of files under cProfile and
reports wall-clock, per-file average, the top-N functions by self-time, a
grouped hotspot summary (OCR CNN / image-decode / face-detect / CLIP / ...),
and OCR-gate telemetry (how many images skipped OCR via ``--ocr-clip-topk``).

Because it drives the real ``ContentBasedFileOrganizer`` scorer path, it is
the tool to use for before/after comparisons of any classification-cost change
(OCR gating, signal reordering, new heavy signals).

Usage
-----
    # Profile a directory (unified scorer, no gate):
    python scripts/profile_pipeline.py --source ~/Documents/Media/Photos --limit 50

    # Compare the CLIP OCR gate on/off (run twice, diff the summaries):
    python scripts/profile_pipeline.py --source DIR --ocr-clip-topk 3
    python scripts/profile_pipeline.py --source DIR   # baseline

    # Machine-readable output for A/B harnesses:
    python scripts/profile_pipeline.py --source DIR --json results/prof.json

Trust the grouped hotspot summary and OCR-invocation counts over wall-clock:
OCR wall time is thermally noisy across repeated runs on laptops.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Allow ``from shared.x import y`` and src imports when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp", ".gif", ".bmp", ".tiff"}

# Substring buckets for the grouped hotspot summary. First match wins, so order
# matters (specific before generic). Keyed by display name.
_HOTSPOT_BUCKETS: List[tuple] = [
    ("OCR: CNN/detect", ("conv2d", "batch_norm", "max_pool", "relu_", "lstm",
                          "upsample", "craft", "getdetboxes", "doctr", "box_score",
                          "normalizemeanvariance")),
    ("Image decode", ("imread", "imagingdecoder", "heif", "thumbnail", "img.load",
                      "_upsample_bilinear2d_aa", "decode")),
    ("Face/composition", ("detectmultiscale", "warpaffine", "cascadeclassifier")),
    ("CLIP", ("clip", "open_clip", "encode_image", "encode_text")),
    ("Tensor move", ("'to' of", "'cpu' of", "tensorbase")),
    ("NumPy", ("numpy", "ufunc", "ndarray")),
]


@dataclass
class ProfileResult:
    scorer: str
    ocr_clip_topk: Optional[int]
    n_files: int
    n_images: int
    wall_seconds: float
    per_file_seconds: float
    ocr_invocations: int
    ocr_gated: int
    decisions: Dict[str, int] = field(default_factory=dict)
    hotspots: Dict[str, float] = field(default_factory=dict)
    top_functions: List[dict] = field(default_factory=list)


def collect_files(sources: List[str], limit: Optional[int]) -> List[Path]:
    files: List[Path] = []
    for src in sources:
        root = Path(src).expanduser()
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(p for p in root.rglob("*") if p.is_file()))
    files = [f for f in files if not f.name.startswith(".")]
    return files[:limit] if limit else files


def _build_organizer(scorer: str, ocr_clip_topk: Optional[int]):
    from file_organizer_content_based import ContentBasedFileOrganizer

    return ContentBasedFileOrganizer(
        base_path=None,
        enable_cost_tracking=False,
        db_path=None,
        scorer=scorer,
        ocr_clip_topk=ocr_clip_topk,
    )


def _make_classify(org, counters: Dict[str, int]) -> Callable[[Path], object]:
    """Return a per-file classify closure that records OCR telemetry.

    Wraps the organizer's own context build + scorer so the profile reflects
    the production hot path while exposing ``ocr_gated`` / whether OCR ran.
    """
    scorer = org._get_unified_scorer()

    def classify(path: Path):
        ctx = org._build_file_context(path)
        decision = scorer.classify(ctx)
        if ctx.ocr_gated:
            counters["ocr_gated"] += 1
        elif ctx.ocr_if_loaded is not None:
            counters["ocr_invocations"] += 1
        return decision

    return classify


def _bucketize(stats: pstats.Stats) -> Dict[str, float]:
    totals: Dict[str, float] = {name: 0.0 for name, _ in _HOTSPOT_BUCKETS}
    totals["Other"] = 0.0
    for (filename, _lineno, func), (_cc, _nc, tottime, _ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        hay = f"{filename}:{func}".lower()
        for name, needles in _HOTSPOT_BUCKETS:
            if any(n in hay for n in needles):
                totals[name] += tottime
                break
        else:
            totals["Other"] += tottime
    return {k: round(v, 3) for k, v in totals.items() if v > 0}


def _top_functions(stats: pstats.Stats, n: int) -> List[dict]:
    rows: List[dict] = []
    ordered = sorted(
        stats.stats.items(), key=lambda kv: kv[1][2], reverse=True  # type: ignore[index]
    )
    for (filename, lineno, func), (_cc, nc, tottime, cumtime, _callers) in ordered[:n]:
        short = Path(filename).name if filename not in ("~", "") else filename
        rows.append(
            {
                "func": f"{short}:{lineno}:{func}",
                "ncalls": nc,
                "tottime": round(tottime, 3),
                "cumtime": round(cumtime, 3),
            }
        )
    return rows


def profile(
    files: List[Path],
    *,
    scorer: str,
    ocr_clip_topk: Optional[int],
    top: int,
    warmup: bool = True,
) -> ProfileResult:
    org = _build_organizer(scorer, ocr_clip_topk)
    counters = {"ocr_invocations": 0, "ocr_gated": 0}
    classify = _make_classify(org, counters)
    decisions: Dict[str, int] = {}
    n_images = sum(1 for f in files if f.suffix.lower() in IMAGE_EXTS)

    # Warm lazy model loads so per-file numbers reflect steady state, not the
    # one-time easyocr/docTR/CLIP construction cost.
    if warmup and files:
        try:
            classify(files[0])
        except Exception:  # noqa: BLE001 — warmup best-effort
            pass

    def run_all() -> None:
        for f in files:
            try:
                d = classify(f)
                key = f"{d.category}/{d.subcategory}"
                decisions[key] = decisions.get(key, 0) + 1
            except Exception as exc:  # noqa: BLE001
                print(f"  ERR {f.name}: {exc}")

    # reset counters after warmup so they reflect the measured pass only
    counters["ocr_invocations"] = 0
    counters["ocr_gated"] = 0
    decisions.clear()

    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    run_all()
    pr.disable()
    wall = time.perf_counter() - t0

    stats = pstats.Stats(pr)
    return ProfileResult(
        scorer=scorer,
        ocr_clip_topk=ocr_clip_topk,
        n_files=len(files),
        n_images=n_images,
        wall_seconds=round(wall, 3),
        per_file_seconds=round(wall / max(len(files), 1), 3),
        ocr_invocations=counters["ocr_invocations"],
        ocr_gated=counters["ocr_gated"],
        decisions=dict(sorted(decisions.items(), key=lambda kv: -kv[1])),
        hotspots=dict(sorted(_bucketize(stats).items(), key=lambda kv: -kv[1])),
        top_functions=_top_functions(stats, top),
    )


def print_report(res: ProfileResult) -> None:
    print("\n" + "=" * 64)
    print(f"PROFILE  scorer={res.scorer}  ocr_clip_topk={res.ocr_clip_topk}")
    print("=" * 64)
    print(f"files={res.n_files} (images={res.n_images})  "
          f"wall={res.wall_seconds}s  per_file={res.per_file_seconds}s")
    print(f"OCR invocations={res.ocr_invocations}  OCR gated (skipped)={res.ocr_gated}")
    if res.n_images:
        pct = 100.0 * res.ocr_gated / res.n_images
        print(f"OCR-skip rate over images: {pct:.1f}%")
    print("\nHotspot summary (self-time seconds):")
    for name, secs in res.hotspots.items():
        print(f"  {name:20s} {secs:8.3f}")
    print(f"\nTop {len(res.top_functions)} functions by self-time:")
    for r in res.top_functions:
        print(f"  {r['tottime']:8.3f}  {r['ncalls']:>7}  {r['func']}")
    print("\nDecision distribution:")
    for key, cnt in list(res.decisions.items())[:15]:
        print(f"  {cnt:5d}  {key}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Profile the content classification hot path.")
    p.add_argument("--source", "--sources", nargs="+", dest="sources", required=True,
                   help="Directories or files to profile")
    p.add_argument("--limit", type=int, help="Max files to profile")
    p.add_argument("--scorer", default="unified", choices=["unified", "legacy", "shadow"])
    p.add_argument("--ocr-clip-topk", type=int, default=None,
                   help="Skip OCR unless a text-bearing label ranks in the top-K CLIP labels")
    p.add_argument("--top", type=int, default=20, help="Top-N functions to report")
    p.add_argument("--no-warmup", action="store_true", help="Skip the warmup file")
    p.add_argument("--json", dest="json_out", help="Write ProfileResult JSON to this path")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    files = collect_files(args.sources, args.limit)
    if not files:
        print("No files found under the given sources.")
        return
    res = profile(
        files,
        scorer=args.scorer,
        ocr_clip_topk=args.ocr_clip_topk,
        top=args.top,
        warmup=not args.no_warmup,
    )
    print_report(res)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(asdict(res), indent=2))
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
