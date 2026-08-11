"""Run the faiss stage in a clean interpreter.

faiss and torch each bundle their own ``libomp.dylib``. On macOS, whichever
initialises second aborts the process:

    OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib
    already initialized.

Verified 2026-08-10 (torch 2.13.0, faiss-cpu 1.15.0, macOS arm64): the abort
fires on faiss's first parallel region — ``IndexFlat.search`` — not at import,
so it survives a smoke test and dies on real work. Import order does not help
(both orders abort), ``OMP_NUM_THREADS=1`` does not help, and
``faiss.omp_set_num_threads(1)`` does not help. The documented
``KMP_DUPLICATE_LIB_OK=TRUE`` workaround is worse than the error: it
**segfaults** (exit 139).

The near-duplicate pipeline needs both libraries — torch to describe images,
faiss to index them — so they are separated by process, not by import order.
The parent describes (torch); this module indexes (faiss) and must never
import torch, directly or transitively.

Run as ``python -m src.similarity.worker <job.json>``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Sequence

from .constants import DEFAULT_MAX_NEIGHBORS, DEFAULT_SIMILARITY_THRESHOLD
from .types import DuplicateGroup, SimilarPair

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKER_MODULE = "src.similarity.worker"
_DESCRIPTORS_FILE = "descriptors.npy"
_JOB_FILE = "job.json"
_RESULT_FILE = "result.json"

# The child does numpy + faiss work on an in-memory matrix; a corpus that
# cannot be indexed inside this window has other problems.
_WORKER_TIMEOUT_SECONDS = 1800


class IndexWorkerError(RuntimeError):
    """The faiss subprocess failed. Carries its stderr for diagnosis."""


# --------------------------------------------------------------------------- #
# Parent side                                                                  #
# --------------------------------------------------------------------------- #


def group_near_duplicates_isolated(
    paths: Sequence[Path],
    descriptors: "np.ndarray",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_neighbors: int = DEFAULT_MAX_NEIGHBORS,
) -> List[DuplicateGroup]:
    """Group near-duplicates, running faiss in a separate interpreter.

    Safe to call from a process that has already loaded torch — which is the
    normal case, since descriptors are produced by torch immediately before.
    """
    import numpy as np

    if len(paths) < 2:
        return []

    with tempfile.TemporaryDirectory(prefix="near-dupe-") as workdir:
        directory = Path(workdir)
        np.save(directory / _DESCRIPTORS_FILE, np.ascontiguousarray(descriptors))
        (directory / _JOB_FILE).write_text(
            json.dumps(
                {
                    "paths": [str(path) for path in paths],
                    "threshold": threshold,
                    "max_neighbors": max_neighbors,
                    "descriptors": _DESCRIPTORS_FILE,
                    "result": _RESULT_FILE,
                }
            )
        )

        completed = subprocess.run(
            [sys.executable, "-m", _WORKER_MODULE, str(directory / _JOB_FILE)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=_WORKER_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise IndexWorkerError(
                f"faiss index worker exited {completed.returncode}: "
                f"{completed.stderr.strip() or '<no stderr>'}"
            )

        payload = json.loads((directory / _RESULT_FILE).read_text())

    return [_group_from_dict(group) for group in payload["groups"]]


def _group_from_dict(payload: Dict[str, Any]) -> DuplicateGroup:
    return DuplicateGroup(
        paths=tuple(Path(path) for path in payload["paths"]),
        pairs=tuple(
            SimilarPair(Path(pair["left"]), Path(pair["right"]), pair["similarity"])
            for pair in payload["pairs"]
        ),
    )


# --------------------------------------------------------------------------- #
# Child side — imports faiss, must never import torch                          #
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str]) -> int:
    import numpy as np

    from .index import group_near_duplicates

    if len(argv) != 1:
        print(f"usage: python -m {_WORKER_MODULE} <job.json>", file=sys.stderr)
        return 2

    job_path = Path(argv[0])
    job = json.loads(job_path.read_text())
    directory = job_path.parent

    descriptors = np.load(directory / job["descriptors"])
    paths = [Path(path) for path in job["paths"]]

    groups = group_near_duplicates(paths, descriptors, job["threshold"], job["max_neighbors"])

    (directory / job["result"]).write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "paths": [str(path) for path in group.paths],
                        "pairs": [
                            {
                                "left": str(pair.left),
                                "right": str(pair.right),
                                "similarity": pair.similarity,
                            }
                            for pair in group.pairs
                        ],
                    }
                    for group in groups
                ]
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main(sys.argv[1:]))
