#!/usr/bin/env python3
"""Scene probe — multinomial linear probe on cached CLIP embeddings.

Generalizes the C1 interior probe (scripts/prototype_interior_probe.py) from
binary interior-vs-not to the four scene classes in
docs/plans/MEDIA_EXTERIORS_PLAN.md:

    0  neither   non-scene images (documents, screenshots, sprites, portraits,
                 product shots) — the reject class; other signals decide these.
    1  interior  indoor rooms                       -> media/interiors_other (Room)
    2  exterior  house/building facades + attached  -> media/exteriors_other (House)
                 porches & patios
    3  place      outdoor / landscape / travel and  -> media/place_other      (Place)
                 non-residential or commercial scenes

schema.org hierarchy preserved: Place > Accommodation > {Room, House}.

Three modes, mirroring the interior prototype:

  gather   Build a labeled manifest CSV (path,label,source,reviewed) from
           directory-per-class roots (--interior/--exterior/--place/--neither),
           the convenience label tree results/scene_labels/<class>/ (--label-dirs),
           and/or the graph DB as ``neither`` negatives (--db-neither). As with
           the interior probe the DB holds no clean scene positives — hand-label
           interior/exterior/place.

  eval     Load embeddings via the production cache (scripts/shared/clip_cache),
           fit a class-balanced multinomial logistic regression (StandardScaler +
           LogisticRegression) with stratified k-fold CV, and report macro
           one-vs-rest ROC-AUC, a confusion matrix, and a per-class acceptance
           threshold sweep (the runtime SceneSignal commits the argmax class when
           its probability clears a threshold).

  train    Fit on the full manifest and persist results/scene_probe.joblib
           ({"pipeline", "meta"}) for the runtime SceneSignal. ``meta.classes``
           records the LogisticRegression class order so the signal maps
           predict_proba columns back to scene names.

Run from the project root so ``from shared.x import y`` resolves (the CLI entry
point does this automatically).
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Reuse the exact production cache so embeddings are byte-identical and this
# script also warms the cache for future runs.
from shared.clip_cache import get_or_compute_embedding  # noqa: E402

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".avif", ".bmp", ".gif", ".tiff"}

# Scene class name -> integer label. Persisted in the artifact meta; the runtime
# SceneSignal maps predict_proba columns back through this. ``neither`` (0) is
# the reject class — the probe emits no vote for it.
SCENE_CLASSES: Dict[str, int] = {
    "neither": 0,
    "interior": 1,
    "exterior": 2,
    "place": 3,
}
CLASS_NAMES: Dict[int, str] = {v: k for k, v in SCENE_CLASSES.items()}
_NEITHER = SCENE_CLASSES["neither"]
# Directory-root class names (everything but the DB-fed reject class).
_POSITIVE_NAMES: Tuple[str, ...] = ("interior", "exterior", "place")

_DEFAULT_MANIFEST = Path("results/scene_labels.csv")
_DEFAULT_DB = Path("results/file_organization.db")
# Persisted probe artifact loaded by the runtime SceneSignal.
_DEFAULT_PROBE = Path("results/scene_probe.joblib")
# Convenience hand-labeling tree: results/scene_labels/<class>/.
_LABEL_ROOT = Path("results/scene_labels")

_SEED = 0
_THRESHOLD_SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7)


# --------------------------------------------------------------------------- #
# Embeddings                                                                   #
# --------------------------------------------------------------------------- #


def load_embedding(path: Path) -> Optional[np.ndarray]:
    """Cached [D] fp32 embedding for ``path`` (encode + store on miss).

    Delegates to the single-homed ``clip_cache.get_or_compute_embedding`` — the
    same accessor the runtime SceneSignal uses — so prototype and production
    score byte-identical vectors. None if unavailable/unreadable.
    """
    emb = get_or_compute_embedding(path)
    return None if emb is None else np.asarray(emb, dtype=np.float64)


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
    """StandardScaler + class-balanced logistic regression.

    ``class_weight='balanced'`` matters here: the ``neither`` pool (DB images)
    usually dwarfs the hand-labeled scene positives. LogisticRegression is
    multinomial by default (lbfgs) when more than two classes are present, so
    the same factory serves the binary and 4-class cases.
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
        seen.setdefault(rp, (label, source))  # first label wins; positives first

    # Positives (interior/exterior/place) before the neither pool, so an image
    # that appears in both a scene dir and the DB keeps its scene label.
    for name in _POSITIVE_NAMES:
        for d in getattr(args, name) or []:
            for p in _iter_images(Path(d)):
                add(p, SCENE_CLASSES[name], f"dir:{name}:{d}")
    if args.label_dirs:
        for name, label in SCENE_CLASSES.items():
            d = _LABEL_ROOT / name
            if d.is_dir():
                for p in _iter_images(d):
                    add(p, label, f"labeldir:{name}")
    for d in args.neither or []:
        for p in _iter_images(Path(d)):
            add(p, _NEITHER, f"dir:neither:{d}")
    if args.db_neither:
        for p in _db_images(Path(args.db), None):
            add(p, _NEITHER, "db:all-images")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["path", "label", "source", "reviewed"])
        for rp, (label, source) in seen.items():
            writer.writerow([rp, label, source, 0])

    counts = {
        name: sum(1 for v in seen.values() if v[0] == label)
        for name, label in SCENE_CLASSES.items()
    }
    print(f"Wrote {out} — {len(seen)} rows.")
    for name, label in SCENE_CLASSES.items():
        print(f"  {label} {name:<9} {counts[name]}")
    thin = [n for n in _POSITIVE_NAMES if counts[n] < 2]
    if thin:
        print(
            f"  NOTE: too few positives for {', '.join(thin)} — hand-label under "
            f"{_LABEL_ROOT}/<class>/ then re-run with --label-dirs."
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


def _class_counts(y: np.ndarray) -> Dict[int, int]:
    return {int(c): int((y == c).sum()) for c in np.unique(y)}


def _cv_proba(X: np.ndarray, y: np.ndarray, folds: int, C: float) -> Tuple[np.ndarray, np.ndarray]:
    """Out-of-fold predict_proba via stratified k-fold. Returns (proba, classes),
    with ``classes`` giving the column order of ``proba``."""
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=_SEED)
    proba = cross_val_predict(make_probe(C), X, y, cv=skf, method="predict_proba")
    return proba, np.unique(y)


def _plumbing_self_check(dim: int, folds: int, C: float) -> None:
    """Prove the probe pipeline + metrics work on a synthetic separable set of
    the same dimensionality, so an insufficient-data run still verifies the
    harness end-to-end."""
    rng = np.random.default_rng(_SEED)
    n = 120
    y = np.array([0] * (n // 2) + [1] * (n // 2))
    direction = rng.standard_normal(dim)
    direction /= np.linalg.norm(direction)
    X = rng.standard_normal((n, dim)) + 4.0 * np.outer(y, direction)
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=_SEED)
    oof = cross_val_predict(make_probe(C), X, y, cv=skf, method="predict_proba")[:, 1]
    print(
        f"  self-check (synthetic, D={dim}): ROC-AUC={roc_auc_score(y, oof):.3f} "
        f"AP={average_precision_score(y, oof):.3f}  -> probe pipeline + metrics OK"
    )


def _report_threshold_sweep(y: np.ndarray, proba: np.ndarray, classes: np.ndarray) -> None:
    """One-vs-rest acceptance sweep per positive class: accept class c iff
    P(c) >= thr — the rule the runtime SceneSignal applies to the argmax."""
    col = {int(c): i for i, c in enumerate(classes)}
    print("  class     thr  precision recall     F1   (accept iff P(class) >= thr)")
    for c in classes:
        c = int(c)
        if c == _NEITHER:
            continue
        yc = (y == c).astype(int)
        pc = proba[:, col[c]]
        for thr in _THRESHOLD_SWEEP:
            pred = (pc >= thr).astype(int)
            tn, fp, fn, tp = confusion_matrix(yc, pred, labels=[0, 1]).ravel()
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            print(
                f"  {CLASS_NAMES.get(c, str(c)):<8} {thr:.1f}  "
                f"{precision:8.3f} {recall:6.3f} {f1:6.3f}"
            )


def _print_multiclass_metrics(y: np.ndarray, proba: np.ndarray, classes: np.ndarray) -> None:
    pred = classes[proba.argmax(axis=1)]
    try:
        if len(classes) == 2:
            auc = roc_auc_score(y, proba[:, 1])
            ap = average_precision_score(y, proba[:, 1])
            print(f"  ROC-AUC={auc:.3f}   Average-Precision={ap:.3f}")
        else:
            auc = roc_auc_score(y, proba, multi_class="ovr", average="macro", labels=classes)
            print(f"  macro one-vs-rest ROC-AUC={auc:.3f}")
    except ValueError as exc:
        print(f"  (ROC-AUC unavailable: {exc})")
    print(f"  argmax accuracy={float((pred == y).mean()):.3f}")

    order = [CLASS_NAMES.get(int(c), str(c)) for c in classes]
    print(f"\n  confusion matrix (rows=true, cols=pred), order {order}:")
    for name, row in zip(order, confusion_matrix(y, pred, labels=classes)):
        print(f"    {name:<9} {row}")
    print()
    print(classification_report(y, pred, labels=classes, target_names=order, zero_division=0))
    _report_threshold_sweep(y, proba, classes)


def cmd_eval(args: argparse.Namespace) -> int:
    rows = _read_manifests(args.manifest)
    if not rows:
        print("No manifest rows. Run `gather` first.")
        return 1

    print(f"Loading embeddings for {len(rows)} labeled images (cache/encode)...")
    X, y, kept = load_matrix(rows)
    counts = _class_counts(y)
    summary = "  ".join(f"{CLASS_NAMES.get(c, c)}={n}" for c, n in sorted(counts.items()))
    print(f"  usable: {len(kept)} images  {summary}")

    min_per_class = min(counts.values()) if counts else 0
    if len(counts) < 2 or min_per_class < 2 or len(kept) < args.folds:
        print(
            f"\nINSUFFICIENT DATA for {args.folds}-fold CV "
            f"(need >= 2 classes, >= 2 per class, >= {args.folds} total)."
        )
        print(
            "  Hand-label interior/exterior/place under results/scene_labels/, then:\n"
            "    python scripts/prototype_scene_probe.py gather --label-dirs\n"
            "    python scripts/prototype_scene_probe.py eval"
        )
        if X.size:
            print("\nVerifying the harness itself (so it's ready once data exists):")
            _plumbing_self_check(X.shape[1], min(args.folds, 5), args.C)
        return 0

    folds = min(args.folds, min_per_class)
    if folds < args.folds:
        print(f"  reducing to {folds}-fold CV (limited by minority class).")
    if min_per_class < 5:
        print(
            f"  ** INDICATIVE ONLY: minority class has {min_per_class} — CV metrics are "
            "high-variance. Aim for >= 5 (ideally 150-300) per positive class. **"
        )

    proba, classes = _cv_proba(X, y, folds, args.C)
    print(f"\n=== {folds}-fold CV (out-of-fold) ===")
    _print_multiclass_metrics(y, proba, classes)
    return 0


# --------------------------------------------------------------------------- #
# train — persist the fitted probe for the runtime SceneSignal                 #
# --------------------------------------------------------------------------- #


def cmd_train(args: argparse.Namespace) -> int:
    import joblib

    rows = _read_manifests(args.manifest)
    if not rows:
        print("No manifest rows. Run `gather` first.")
        return 1
    X, y, kept = load_matrix(rows)
    counts = _class_counts(y)
    if len(counts) < 2 or min(counts.values()) < 2:
        print(f"Refusing to train: need >= 2 classes and >= 2 per class (have {counts}).")
        return 1

    probe = make_probe(args.C).fit(X, y)
    trained_classes = [int(c) for c in probe.named_steps["lr"].classes_]
    artifact = {
        "pipeline": probe,
        "meta": {
            "classes": trained_classes,  # predict_proba column order
            "class_names": {c: CLASS_NAMES.get(c, str(c)) for c in trained_classes},
            "counts": {CLASS_NAMES.get(c, str(c)): n for c, n in counts.items()},
            "C": args.C,
            "seed": _SEED,
            "feature_dim": int(X.shape[1]),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, out)
    labels = [CLASS_NAMES.get(c, str(c)) for c in trained_classes]
    print(f"Trained on {counts} (dim={X.shape[1]}) -> {out}")
    print(f"  class order (predict_proba columns): {labels}")
    return 0


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
    g.add_argument("--exterior", action="append", help="dir of house/building exteriors (label=2)")
    g.add_argument("--place", action="append", help="dir of outdoor/place images (label=3)")
    g.add_argument("--neither", action="append", help="dir of non-scene images (label=0)")
    g.add_argument(
        "--label-dirs",
        action="store_true",
        help=f"also ingest {_LABEL_ROOT}/<class>/ for each scene class",
    )
    g.add_argument("--db", default=str(_DEFAULT_DB), help="graph DB path")
    g.add_argument(
        "--db-neither", action="store_true", help="all on-disk DB images as `neither` (label=0)"
    )
    g.add_argument("--out", default=str(_DEFAULT_MANIFEST), help="output manifest CSV")
    g.set_defaults(func=cmd_gather)

    e = sub.add_parser("eval", help="CV-eval the multinomial probe on a manifest")
    e.add_argument("--manifest", action="append", default=None, help="manifest CSV (repeatable)")
    e.add_argument("--folds", type=int, default=5)
    e.add_argument("--C", type=float, default=1.0, help="inverse L2 strength (sklearn C)")
    e.set_defaults(func=cmd_eval)

    t = sub.add_parser("train", help="fit the probe on a manifest and persist a joblib artifact")
    t.add_argument("--manifest", action="append", default=None, help="manifest CSV (repeatable)")
    t.add_argument("--C", type=float, default=1.0, help="inverse L2 strength (sklearn C)")
    t.add_argument("--out", default=str(_DEFAULT_PROBE), help="output joblib artifact path")
    t.set_defaults(func=cmd_train)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in ("eval", "train") and not args.manifest:
        args.manifest = [str(_DEFAULT_MANIFEST)]
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
