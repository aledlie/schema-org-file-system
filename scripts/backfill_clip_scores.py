#!/usr/bin/env python3
"""Backfill CLIP label scores (files.image_classification) + embedding cache.

The backtest replay (``scripts/backtest_scoring.py``) reconstructs
``ClipVisionSignal`` input from the ``files.image_classification`` column —
but nothing in the production pipeline ever wrote it, so every replayed image
classifies without CLIP and the media slice of the stored-decision oracle is
noise (see ``docs/architecture/scoring-calibration-20260726.md`` §4).

For every image row whose ``current_path`` exists on disk, this computes the
same label→score mapping the live unified path builds
(``ContentOrganizer._clip_scores_for_context``: ``CLIP_CATEGORY_PROMPTS``
scored with an empty prompt prefix, prompts mapped to their
``CLIP_CONTENT_LABELS`` short keys) and stores it as JSON. As a side effect
each image's fp32 embedding lands in ``.cache/clip_embeddings_v2/`` keyed by
current-path identity, which also feeds ``SceneSignal`` on future live runs.

Idempotent: rows with a non-empty ``image_classification`` are skipped unless
``--force``. Dry-run by default; pass ``--apply`` to write.

Usage:
    PYTHONPATH=src:scripts:. python scripts/backfill_clip_scores.py            # report only
    PYTHONPATH=src:scripts:. python scripts/backfill_clip_scores.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.models import ClipScores

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from constants import DEFAULT_DB_PATH  # noqa: E402  (src on path)

EXIT_OK = 0
EXIT_NO_DATA = 1

# Progress print cadence (rows).
PROGRESS_EVERY = 25


def backfill(db_path: Path, apply: bool, force: bool, limit: Optional[int]) -> int:
    from shared.clip_cache import get_cached_embedding
    from shared.constants import CLIP_CATEGORY_PROMPTS, CLIP_CONTENT_LABELS

    prompt_to_label = dict(zip(CLIP_CATEGORY_PROMPTS, CLIP_CONTENT_LABELS))

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    where = "mime_type LIKE 'image/%'"
    if not force:
        where += (
            " AND (image_classification IS NULL"
            " OR image_classification = 'null' OR image_classification = '{}')"
        )
    query = f"SELECT id, current_path FROM files WHERE {where} ORDER BY id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    rows = db.execute(query).fetchall()

    done = missing = failed = 0
    updates: List[tuple] = []
    for i, row in enumerate(rows, 1):
        path = Path(row["current_path"] or "")
        if not path.exists():
            missing += 1
            continue
        try:
            results = get_cached_embedding(path, list(CLIP_CATEGORY_PROMPTS), prompt_prefix="")
        except Exception as exc:  # noqa: BLE001 — per-file resilience
            print(f"  ERR {path.name}: {exc}")
            failed += 1
            continue
        # Checked against the column's declared shape (models.ClipScores).
        scores: ClipScores = {
            prompt_to_label.get(prompt, prompt): score for prompt, score in results
        }
        updates.append((json.dumps(scores), row["id"]))
        done += 1
        if i % PROGRESS_EVERY == 0:
            print(f"  {i}/{len(rows)} processed ({done} scored)")

    label = "APPLY" if apply else "DRY RUN"
    print(
        f"[{label}] candidate rows: {len(rows)}  scored: {done}  "
        f"missing on disk: {missing}  failed: {failed}"
    )
    if apply and updates:
        db.executemany("UPDATE files SET image_classification=? WHERE id=?", updates)
        db.commit()
        print(f"[{label}] wrote {len(updates)} image_classification rows")
    db.close()
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-path", type=Path, default=Path(DEFAULT_DB_PATH))
    parser.add_argument("--apply", action="store_true", help="Write results (default: dry run)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute rows that already have image_classification",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process")
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"Error: database not found at {args.db_path}")
        return EXIT_NO_DATA
    return backfill(args.db_path, apply=args.apply, force=args.force, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
