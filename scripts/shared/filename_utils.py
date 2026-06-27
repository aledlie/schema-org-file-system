"""
Shared filename utility functions.

Provides a single source of truth for generic-filename detection patterns
used across ImageAnalyzer and ImageRenamer.
"""

from __future__ import annotations

import re
from pathlib import Path

# Compiled at module load; matched against the lowercased file stem.
_GENERIC_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        # Camera vendor prefixes
        r"^img_\d+",  # IMG_1234.jpg
        r"^pxl_\d+",  # PXL_20250425.jpg
        r"^dsc_?\d+",  # DSC_1234.jpg / DSC1234.jpg
        r"^dcim_\d+",  # DCIM_1234.jpg
        # Screenshots — [\s_-] superset covers "screenshot 2025..." too
        r"^screenshot[\s_-]",
        # Timestamps
        r"^\d{8}_\d{6}",  # 20250425_123456.jpg
        r"^\d{4}-\d{2}-\d{2}",  # 2025-04-25.jpg
        r"^\d{13}",  # Unix ms timestamps
        # Pure numeric
        r"^\d+$",  # 12345.jpg
        # Hashes and UUIDs
        r"^[a-f0-9]{32}",  # MD5-style hashes
        r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",  # UUIDs
        # Generic placeholders with optional counters
        r"^image\d*$",  # image, image1
        r"^image\(\d+\)",  # image(1).jpg
        r"^photo\d*$",  # photo, photo1
        r"^photo\(\d+\)",  # photo(1).jpg
        r"^unnamed",  # unnamed, unnamed(1)
        r"^file\(\d+\)",  # file(1).jpg
    )
)

# Public alias for callers that need the raw strings (e.g. tests)
GENERIC_FILENAME_PATTERNS: tuple[str, ...] = tuple(p.pattern for p in _GENERIC_FILENAME_PATTERNS)


def is_generic_filename(filename: str) -> bool:
    """Return True if *filename* is a generic/non-human-readable name."""
    stem = Path(filename).stem.lower()
    return any(p.match(stem) for p in _GENERIC_FILENAME_PATTERNS)
