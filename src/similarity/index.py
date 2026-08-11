"""faiss similarity index and near-duplicate grouping.

Exact (``IndexFlatIP``) search, deliberately — measured on this project's target
corpus (265k x 512) a flat index is 543 MB resident and answers a full self-kNN
in about a minute. An approximate index (IVF/PQ) would add recall tuning and a
training step for no gain at this size. Revisit only if the corpus grows an
order of magnitude.

Descriptors are L2-normalised, so inner product *is* cosine similarity.

**Never import this module in a process that has loaded torch.** faiss and
torch each bundle their own ``libomp.dylib``; on macOS the second one to
initialise aborts the process with "OMP: Error #15", and the documented
``KMP_DUPLICATE_LIB_OK=TRUE`` escape hatch segfaults here rather than degrading
(verified 2026-08-10 on torch 2.13.0 / faiss-cpu 1.15.0). Everything in this
module is therefore reached through ``worker.py``, which runs it in a clean
interpreter. ``finder.py`` is the supported entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Sequence, Tuple

from .constants import DEFAULT_MAX_NEIGHBORS, DEFAULT_SIMILARITY_THRESHOLD, MIN_GROUP_SIZE
from .types import DuplicateGroup, SimilarPair

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

try:
    import numpy as np  # noqa: F811

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    import faiss

    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False

logger = logging.getLogger(__name__)

INDEX_AVAILABLE = _HAS_NUMPY and _HAS_FAISS


class _UnionFind:
    """Minimal union-find over descriptor row indices."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def build_index(descriptors: "np.ndarray"):
    """Build a flat inner-product index over ``[N, D]`` float32 descriptors.

    Normalises in place — callers pass a copy if they need the originals.
    Returns ``None`` when faiss/numpy is unavailable so callers degrade.
    """
    if not INDEX_AVAILABLE or descriptors.size == 0:
        return None
    matrix = np.ascontiguousarray(descriptors.astype("float32"))
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    return index


def find_similar_pairs(
    paths: Sequence[Path],
    descriptors: "np.ndarray",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_neighbors: int = DEFAULT_MAX_NEIGHBORS,
) -> List[SimilarPair]:
    """Return every distinct pair scoring at or above ``threshold``.

    Self-matches are dropped, and each unordered pair is emitted once.
    """
    if not INDEX_AVAILABLE or len(paths) < MIN_GROUP_SIZE:
        return []

    matrix = np.ascontiguousarray(descriptors.astype("float32"))
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    # +1 because the nearest neighbour of every row is itself.
    neighbors = min(max_neighbors + 1, len(paths))
    scores, indices = index.search(matrix, neighbors)

    seen: set[Tuple[int, int]] = set()
    pairs: List[SimilarPair] = []
    for row in range(len(paths)):
        for column in range(neighbors):
            other = int(indices[row][column])
            if other < 0 or other == row:
                continue
            similarity = float(scores[row][column])
            if similarity < threshold:
                continue
            key = (row, other) if row < other else (other, row)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(SimilarPair(paths[key[0]], paths[key[1]], similarity))
    return pairs


def group_near_duplicates(
    paths: Sequence[Path],
    descriptors: "np.ndarray",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_neighbors: int = DEFAULT_MAX_NEIGHBORS,
) -> List[DuplicateGroup]:
    """Group files into near-duplicate components, largest (then tightest) first."""
    pairs = find_similar_pairs(paths, descriptors, threshold, max_neighbors)
    if not pairs:
        return []

    position = {path: index for index, path in enumerate(paths)}
    union_find = _UnionFind(len(paths))
    for pair in pairs:
        union_find.union(position[pair.left], position[pair.right])

    members: Dict[int, List[int]] = {}
    for index in range(len(paths)):
        members.setdefault(union_find.find(index), []).append(index)

    pairs_by_root: Dict[int, List[SimilarPair]] = {}
    for pair in pairs:
        pairs_by_root.setdefault(union_find.find(position[pair.left]), []).append(pair)

    groups = [
        DuplicateGroup(
            paths=tuple(paths[i] for i in sorted(indices)),
            pairs=tuple(sorted(pairs_by_root[root], key=lambda p: -p.similarity)),
        )
        for root, indices in members.items()
        if len(indices) >= MIN_GROUP_SIZE
    ]
    groups.sort(key=lambda group: (-group.size, -group.max_similarity))
    return groups
