#!/usr/bin/env python3
"""C1 interior-probe prototype — linear probe on cached CLIP embeddings.

Prototype for docs/reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md (Option
C1): test whether the frozen open_clip ``ViT-B-32`` embeddings the pipeline
already caches are linearly separable for interior-vs-not, without touching the
backbone or invalidating the cache.

Two modes:

  gather   Build a labeled manifest CSV (path,label,source,reviewed) from
           directory-per-class roots, explicit files, and/or the graph DB
           (results/file_organization.db). DB images are weak candidates — the
           existing detector produced NO interior positives, so the DB is a
           negatives source; interiors must be hand-supplied via --interior.

  eval     Load each manifest row's embedding via the production cache
           (scripts/shared/clip_cache: cache hit, else encode + store), fit an
           L2-regularized logistic regression (sklearn, StandardScaler +
           class-balanced) with stratified k-fold CV, and report ROC-AUC /
           average-precision / a threshold sweep. Also scores the reference
           render for contrast with the zero-shot coin-flip (0.516) measured in
           the analysis.

Run from the project root so ``from shared.x import y`` resolves (the CLI entry
point does this automatically).
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Reuse the exact production cache so embeddings are byte-identical and this
# script also warms the cache for future runs.
from shared.clip_cache import (  # noqa: E402
    _cache_path,
    _file_identity,
    _load_embedding,
    _save_embedding,
)
from shared.clip_utils import get_clip_classifier  # noqa: E402

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".avif", ".bmp", ".gif", ".tiff"}
_DEFAULT_MANIFEST = Path("results/interior_probe_labels.csv")
_DEFAULT_DB = Path("results/file_organization.db")
_REFERENCE_IMAGE = Path(
    os.path.expanduser("~/Downloads/ChatGPT Image Oct 31, 2025, 01_30_52 PM.png")
)
# Zero-shot binary interior-vs-outdoor score for the reference render, measured
# in the durable-fix analysis — the bar a learned probe must beat.
_ZERO_SHOT_BASELINE = 0.5161
_SEED = 0
_THRESHOLD_SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7)


# --------------------------------------------------------------------------- #
# Embeddings                                                                   #
# --------------------------------------------------------------------------- #


def load_embedding(path: Path) -> Optional[np.ndarray]:
    """Return the cached [D] fp32 embedding for ``path``; encode + store on miss.

    Mirrors ``clip_cache.get_cached_embedding`` but returns the raw vector
    instead of label scores. Returns None if the file is unreadable.
    """
    key = _file_identity(path)
    cpath = _cache_path(key)
    emb = _load_embedding(cpath)
    if emb is not None:
        return np.asarray(emb, dtype=np.float64)
    try:
        emb = get_clip_classifier().encode_image_to_numpy(path)
    except Exception as exc:  # unreadable / decode failure — skip, don't abort
        print(f"  ! encode failed for {path}: {exc}", file=sys.stderr)
        return None
    _save_embedding(cpath, emb)
    return np.asarray(emb, dtype=np.float64)


def load_matrix(rows: Sequence[Tuple[Path, int]]) -> Tuple[np.ndarray, np.ndarray, List[Path]]:
    """Load embeddings for labeled rows. Returns (X, y, kept_paths)."""
    xs, ys, kept = [], [], []
    for path, label in rows:
        emb = load_embedding(path)
        if emb is None:
            continue
        xs.append(emb)
        ys.append(label)
        kept.append(path)
    if not xs:
        return np.empty((0, 0)), np.empty((0,)), []
    return np.vstack(xs), np.asarray(ys, dtype=int), kept


def make_probe(C: float) -> Pipeline:
    """StandardScaler + class-balanced L2 logistic regression.

    class_weight='balanced' matters here: the negative pool (DB images) will
    usually dwarf the hand-labeled interior positives.
    """
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "lr",
                LogisticRegression(C=C, max_iter=2000, class_weight="balanced", random_state=_SEED),
            ),
        ]
    )


# --------------------------------------------------------------------------- #
# Metrics                                                                      #
# --------------------------------------------------------------------------- #


def report_threshold_sweep(y: np.ndarray, scores: np.ndarray) -> None:
    print("  thr   precision  recall     F1    TP FP TN FN")
    for thr in _THRESHOLD_SWEEP:
        pred = (scores >= thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        print(
            f"  {thr:.1f}   {precision:8.3f}  {recall:7.3f}  {f1:6.3f}   "
            f"{tp:2d} {fp:2d} {tn:2d} {fn:2d}"
        )


# --------------------------------------------------------------------------- #
# gather                                                                       #
# --------------------------------------------------------------------------- #


def _iter_images(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
            yield p


def _db_images(db: Path, category_substr: Optional[str]) -> List[Path]:
    """On-disk image files from the graph DB, optionally filtered by category."""
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        if category_substr:
            q = """SELECT DISTINCT f.current_path FROM files f
                   JOIN file_categories fc ON fc.file_id = f.id
                   JOIN categories c ON c.id = fc.category_id
                   WHERE f.mime_type LIKE 'image/%' AND c.full_path LIKE ?"""
            rows = con.execute(q, (f"%{category_substr}%",)).fetchall()
        else:
            rows = con.execute(
                "SELECT DISTINCT current_path FROM files WHERE mime_type LIKE 'image/%'"
            ).fetchall()
    finally:
        con.close()
    return [Path(r[0]) for r in rows if r[0] and os.path.exists(r[0])]


def cmd_gather(args: argparse.Namespace) -> int:
    seen: dict = {}

    def add(path: Path, label: int, source: str) -> None:
        rp = str(Path(path).resolve())
        if rp not in seen:  # first label wins; positives added before negatives
            seen[rp] = (label, source)

    for d in args.interior or []:
        for p in _iter_images(Path(d)):
            add(p, 1, f"dir:{d}")
    for p in args.positive or []:
        add(Path(p), 1, "explicit")
    if args.positive_list:
        for line in Path(args.positive_list).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                add(Path(line), 1, f"list:{args.positive_list}")
    if args.db_positive_cat:
        for p in _db_images(Path(args.db), args.db_positive_cat):
            add(p, 1, f"db:{args.db_positive_cat}")

    for d in args.negative or []:
        for p in _iter_images(Path(d)):
            add(p, 0, f"dir:{d}")
    for p in args.neg or []:
        add(Path(p), 0, "explicit")
    if args.db_negative_cat:
        for p in _db_images(Path(args.db), args.db_negative_cat):
            add(p, 0, f"db:{args.db_negative_cat}")
    if args.db_negatives:
        for p in _db_images(Path(args.db), None):
            add(p, 0, "db:all-images")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["path", "label", "source", "reviewed"])
        for rp, (label, source) in seen.items():
            writer.writerow([rp, label, source, 0])

    pos = sum(1 for v in seen.values() if v[0] == 1)
    neg = sum(1 for v in seen.values() if v[0] == 0)
    print(f"Wrote {out} — {len(seen)} rows ({pos} positive, {neg} negative).")
    if pos < 2 or neg < 2:
        print(
            "  NOTE: too few of one class for a meaningful eval. Interiors are "
            "NOT in the graph DB — hand-supply them with --interior DIR."
        )
    return 0


# --------------------------------------------------------------------------- #
# eval                                                                         #
# --------------------------------------------------------------------------- #


def _read_manifests(paths: Sequence[str]) -> List[Tuple[Path, int]]:
    rows: List[Tuple[Path, int]] = []
    seen = set()
    for mp in paths:
        with open(mp, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                p = Path(r["path"])
                rp = str(p.resolve())
                if rp in seen:
                    continue
                seen.add(rp)
                rows.append((p, int(r["label"])))
    return rows


def _cv_scores(X: np.ndarray, y: np.ndarray, folds: int, C: float) -> np.ndarray:
    """Out-of-fold P(interior) via stratified k-fold."""
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=_SEED)
    return cross_val_predict(make_probe(C), X, y, cv=skf, method="predict_proba")[:, 1]


def _plumbing_self_check(dim: int, folds: int, C: float) -> None:
    """Prove the probe pipeline + metrics work on a synthetic separable set of
    the same dimensionality, so an insufficient-data interior run still verifies
    the harness end-to-end."""
    rng = np.random.default_rng(_SEED)
    n = 120
    y = np.array([0] * (n // 2) + [1] * (n // 2))
    direction = rng.standard_normal(dim)
    direction /= np.linalg.norm(direction)
    # 4-sigma class mean-shift along one direction: cleanly separable, so a
    # working probe must score ROC-AUC ~1.0 — anything lower means broken wiring.
    X = rng.standard_normal((n, dim)) + 4.0 * np.outer(y, direction)
    oof = _cv_scores(X, y, folds, C)
    print(
        f"  self-check (synthetic, D={dim}): ROC-AUC={roc_auc_score(y, oof):.3f} "
        f"AP={average_precision_score(y, oof):.3f}  -> probe pipeline + metrics OK"
    )


def cmd_eval(args: argparse.Namespace) -> int:
    rows = _read_manifests(args.manifest)
    if not rows:
        print("No manifest rows. Run `gather` first.")
        return 1

    print(f"Loading embeddings for {len(rows)} labeled images (cache/encode)...")
    X, y, kept = load_matrix(rows)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    print(f"  usable: {len(kept)} images ({n_pos} positive, {n_neg} negative)")

    ref = _REFERENCE_IMAGE
    min_per_class = min(n_pos, n_neg)

    if min_per_class < 2 or len(kept) < args.folds:
        print(
            f"\nINSUFFICIENT DATA for {args.folds}-fold CV "
            f"(need >= 2 per class and >= {args.folds} total)."
        )
        print(
            "  The graph DB contains no interior positives (the detector this "
            "probe replaces never produced any). Hand-label interiors:\n"
            "    python scripts/prototype_interior_probe.py gather \\\n"
            "        --interior /path/to/interior_photos --db-negatives\n"
            "    python scripts/prototype_interior_probe.py eval"
        )
        print("\nVerifying the harness itself (so it's ready once data exists):")
        if X.size:
            _plumbing_self_check(X.shape[1], min(args.folds, 5), args.C)
        if args.score_reference and ref.exists() and len(np.unique(y)) == 2:
            _score_reference(X, y, kept, ref, args)
        return 0

    folds = min(args.folds, min_per_class)
    if folds < args.folds:
        print(f"  reducing to {folds}-fold CV (limited by minority class).")
    if min_per_class < 5:
        print(
            f"  ** INDICATIVE ONLY: {min_per_class} positive(s) — CV metrics are "
            "high-variance and not a reliable estimate. Aim for >= 5 (ideally "
            "150-300) interiors. **"
        )
    oof = _cv_scores(X, y, folds, args.C)

    print(f"\n=== {folds}-fold CV (out-of-fold) ===")
    print(
        f"  ROC-AUC={roc_auc_score(y, oof):.3f}   "
        f"Average-Precision={average_precision_score(y, oof):.3f}   "
        f"(base rate={n_pos/len(kept):.3f})"
    )
    report_threshold_sweep(y, oof)

    if args.score_reference and ref.exists():
        _score_reference(X, y, kept, ref, args)
    return 0


def _score_reference(
    X: np.ndarray, y: np.ndarray, kept: List[Path], ref: Path, args: argparse.Namespace
) -> None:
    """Refit on all data and score the reference render for the coin-flip contrast."""
    emb = load_embedding(ref)
    if emb is None or X.size == 0 or len(np.unique(y)) < 2:
        return
    n_pos = int((y == 1).sum())
    in_sample = str(ref.resolve()) in {str(p.resolve()) for p in kept}
    probe = make_probe(args.C).fit(X, y)
    prob = float(probe.predict_proba(emb[None, :])[0, 1])
    print(f"\n=== reference render: {ref.name} ===")
    print(f"  probe P(interior) = {prob:.3f}")
    print(f"  zero-shot binary baseline (from analysis) = {_ZERO_SHOT_BASELINE:.3f}")
    if n_pos < 2 and in_sample:
        print(
            "  MEMORIZED: the reference is the only positive and is in the "
            "training set — this is not a generalization estimate. Add more "
            "labeled interiors (and exclude the reference) for a real number."
        )
    elif n_pos < 5:
        print("  (warning: trained on very few positives — indicative only)")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gather", help="build a labeled manifest CSV")
    g.add_argument("--interior", action="append", help="dir of interior images (label=1)")
    g.add_argument("--negative", action="append", help="dir of non-interior images (label=0)")
    g.add_argument("--positive", action="append", help="explicit interior file (label=1)")
    g.add_argument("--positive-list", help="file of newline-separated interior paths (label=1)")
    g.add_argument("--neg", action="append", help="explicit non-interior file (label=0)")
    g.add_argument("--db", default=str(_DEFAULT_DB), help="graph DB path")
    g.add_argument("--db-negatives", action="store_true", help="all on-disk DB images as negatives")
    g.add_argument("--db-positive-cat", help="DB category substring -> positives (proxy tasks)")
    g.add_argument("--db-negative-cat", help="DB category substring -> negatives (proxy tasks)")
    g.add_argument("--out", default=str(_DEFAULT_MANIFEST), help="output manifest CSV")
    g.set_defaults(func=cmd_gather)

    e = sub.add_parser("eval", help="train + CV-eval the probe on a manifest")
    e.add_argument("--manifest", action="append", default=None, help="manifest CSV (repeatable)")
    e.add_argument("--folds", type=int, default=5)
    e.add_argument("--C", type=float, default=1.0, help="inverse L2 strength (sklearn C)")
    e.add_argument(
        "--score-reference",
        action="store_true",
        help="also score the interior reference render (interior task only)",
    )
    e.set_defaults(func=cmd_eval)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "eval" and not args.manifest:
        args.manifest = [str(_DEFAULT_MANIFEST)]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
