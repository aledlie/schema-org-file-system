"""Result types for near-duplicate detection.

Deliberately dependency-free (stdlib only): these cross a process boundary —
see ``worker.py`` — so both the torch-side parent and the faiss-side child must
be able to import them without pulling the other side's native libraries in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class SimilarPair:
    """Two files whose descriptors exceed the similarity threshold."""

    left: Path
    right: Path
    similarity: float


@dataclass(frozen=True)
class DuplicateGroup:
    """A connected component of near-duplicate files.

    Transitivity is a reporting convenience, not a claim: A~B and B~C puts A, B
    and C in one group even when A~C falls below the threshold. That is the
    right shape for human review of a document family, and the wrong shape for
    an automated delete — which is why this feature only ever reports.
    """

    paths: Tuple[Path, ...]
    pairs: Tuple[SimilarPair, ...]

    @property
    def size(self) -> int:
        return len(self.paths)

    @property
    def min_similarity(self) -> float:
        return min(pair.similarity for pair in self.pairs)

    @property
    def max_similarity(self) -> float:
        return max(pair.similarity for pair in self.pairs)
