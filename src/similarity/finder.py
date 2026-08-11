"""Near-duplicate report — walk a tree, describe it, group it, print it.

Read-only by construction: no file moves, no graph writes. It answers "which of
these are the same document twice", which the exact-``content_hash`` grouping in
``GraphStore.find_duplicates`` cannot — different bytes (re-encoded, resized,
PDF-vs-PNG) are different hashes.

Deciding what to *do* about a group is left to a human. See the BACKLOG entry.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    DEFAULT_MAX_NEIGHBORS,
    DEFAULT_SIMILARITY_THRESHOLD,
    IMAGE_EXTENSIONS,
    PDF_EXTENSION,
)
from .descriptors import DESCRIPTORS_AVAILABLE, get_descriptors
from .types import DuplicateGroup

logger = logging.getLogger(__name__)


def _faiss_installed() -> bool:
    """Check for faiss *without importing it*.

    This module runs in the torch-side process; importing faiss here is exactly
    the co-load that aborts the interpreter (see ``worker.py``).
    """
    return importlib.util.find_spec("faiss") is not None


@dataclass(frozen=True)
class DuplicateReport:
    """Outcome of one near-duplicate scan."""

    groups: List[DuplicateGroup]
    scanned: int
    described: int
    threshold: float

    @property
    def duplicate_file_count(self) -> int:
        return sum(group.size for group in self.groups)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold": self.threshold,
            "files_scanned": self.scanned,
            "files_described": self.described,
            "group_count": len(self.groups),
            "duplicate_file_count": self.duplicate_file_count,
            "groups": [
                {
                    "size": group.size,
                    "min_similarity": round(group.min_similarity, 4),
                    "max_similarity": round(group.max_similarity, 4),
                    "paths": [str(path) for path in group.paths],
                    "pairs": [
                        {
                            "left": str(pair.left),
                            "right": str(pair.right),
                            "similarity": round(pair.similarity, 4),
                        }
                        for pair in group.pairs
                    ],
                }
                for group in self.groups
            ],
        }


def supported_extensions(include_pdfs: bool = True) -> frozenset:
    """Extensions the descriptor model can consume."""
    if include_pdfs:
        return IMAGE_EXTENSIONS | {PDF_EXTENSION}
    return IMAGE_EXTENSIONS


def collect_files(
    sources: Sequence[Path],
    include_pdfs: bool = True,
    limit: Optional[int] = None,
) -> List[Path]:
    """Recursively collect describable files under ``sources``.

    Sorted for run-to-run stability, so ``--limit`` selects the same subset on a
    repeat run instead of an arbitrary one.
    """
    extensions = supported_extensions(include_pdfs)
    found: List[Path] = []
    for source in sources:
        source = Path(source).expanduser()
        if source.is_file():
            if source.suffix.lower() in extensions:
                found.append(source)
            continue
        if not source.is_dir():
            logger.warning("Source does not exist, skipped: %s", source)
            continue
        found.extend(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.lower() in extensions
        )
    found.sort()
    return found[:limit] if limit else found


def find_duplicates(
    sources: Sequence[Path],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_neighbors: int = DEFAULT_MAX_NEIGHBORS,
    include_pdfs: bool = True,
    limit: Optional[int] = None,
) -> DuplicateReport:
    """Scan ``sources`` and group near-duplicates."""
    import numpy as np

    from .worker import group_near_duplicates_isolated

    files = collect_files(sources, include_pdfs=include_pdfs, limit=limit)
    if not files:
        return DuplicateReport(groups=[], scanned=0, described=0, threshold=threshold)

    described = get_descriptors(files)
    if not described:
        return DuplicateReport(groups=[], scanned=len(files), described=0, threshold=threshold)

    paths = [path for path, _ in described]
    matrix = np.vstack([descriptor for _, descriptor in described])
    groups = group_near_duplicates_isolated(paths, matrix, threshold, max_neighbors)
    return DuplicateReport(
        groups=groups,
        scanned=len(files),
        described=len(paths),
        threshold=threshold,
    )


def unavailable_reason() -> Optional[str]:
    """Explain why a scan cannot run, or ``None`` when it can."""
    if not DESCRIPTORS_AVAILABLE:
        return "SSCD descriptors need torch, torchvision and Pillow: pip install -e '.[ai]'"
    if not _faiss_installed():
        return "faiss is not installed: pip install -e '.[similarity]'"
    return None


def print_report(report: DuplicateReport) -> None:
    """Human-readable summary."""
    print(f"\nScanned {report.scanned} file(s); described {report.described}.")
    if report.described < report.scanned:
        print(f"  {report.scanned - report.described} could not be read or encoded.")
    if not report.groups:
        print(f"No near-duplicates at similarity >= {report.threshold}.\n")
        return

    print(
        f"\n{len(report.groups)} near-duplicate group(s) covering "
        f"{report.duplicate_file_count} file(s), similarity >= {report.threshold}:\n"
    )
    for number, group in enumerate(report.groups, start=1):
        print(f"  [{number}] {group.size} files, similarity {group.min_similarity:.3f}")
        for path in group.paths:
            print(f"      {path}")
        print()
    print("Nothing was moved or deleted — this is a report.\n")


def write_report(report: DuplicateReport, output: Path) -> None:
    """Persist the report as JSON."""
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_dict(), indent=2))
    print(f"Wrote {output}")
