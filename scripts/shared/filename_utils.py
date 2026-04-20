"""
Shared filename utility functions.

Provides a single source of truth for generic-filename detection patterns
used across ImageContentRenamer and ImageRenamer.
"""
from __future__ import annotations

import re
from pathlib import Path

# Ordered from most-specific to least-specific so the first match wins.
# All patterns are matched against the lowercased stem.
GENERIC_FILENAME_PATTERNS: tuple[str, ...] = (
    # Camera vendor prefixes
    r'^img_\d+',                                                    # IMG_1234.jpg
    r'^pxl_\d+',                                                    # PXL_20250425.jpg
    r'^dsc_?\d+',                                                   # DSC_1234.jpg / DSC1234.jpg
    r'^dcim_\d+',                                                   # DCIM_1234.jpg
    # Screenshots
    r'^screenshot[\s_-]',                                           # screenshot 2025-11-23...
    r'^screenshot\s+\d{4}',                                         # Screenshot 2025...
    # Timestamps
    r'^\d{8}_\d{6}',                                               # 20250425_123456.jpg
    r'^\d{4}-\d{2}-\d{2}',                                        # 2025-04-25.jpg
    r'^\d{13}',                                                     # Unix ms timestamps
    # Pure numeric
    r'^\d+$',                                                       # 12345.jpg
    # Hashes and UUIDs
    r'^[a-f0-9]{32}',                                              # MD5-style hashes
    r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',  # UUIDs
    # Generic placeholders with counters
    r'^image\d*$',                                                  # image, image1
    r'^image\(\d+\)',                                               # image(1).jpg
    r'^photo\d*$',                                                  # photo, photo1
    r'^photo\(\d+\)',                                               # photo(1).jpg
    r'^unnamed',                                                    # unnamed, unnamed(1)
    r'^file\(\d+\)',                                                # file(1).jpg
)


def is_generic_filename(filename: str) -> bool:
    """Return True if *filename* is a generic/non-human-readable name."""
    stem = Path(filename).stem.lower()
    return any(re.match(pattern, stem) for pattern in GENERIC_FILENAME_PATTERNS)
