"""
Shared filename utility functions.

Provides a single source of truth for generic-filename detection patterns
used across ImageAnalyzer and ImageRenamer.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared.constants import CAMERA_VENDOR_PREFIX_PATTERNS  # noqa: E402

# Compiled at module load; matched against the lowercased file stem.
_GENERIC_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        # Camera vendor prefixes — single-homed in shared.constants so
        # name_organizer.py's camera_photos group stays in sync.
        *CAMERA_VENDOR_PREFIX_PATTERNS,
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


# Title-snippet selection (ported from the retired image_renamer_metadata.py):
# scan the first few OCR lines for one sized like a window/page title.
_TITLE_SNIPPET_WINDOW = 3     # only the first N lines can hold a title
_TITLE_SNIPPET_MIN_CHARS = 10  # exclusive — shorter lines are UI fragments
_TITLE_SNIPPET_MAX_CHARS = 50  # exclusive — longer lines are body text
_TITLE_SNIPPET_CAP = 40        # hard cap after sanitization


def title_snippet_from_lines(lines: list[str] | None) -> str | None:
    """Pick a filename-safe title snippet from reading-order OCR lines.

    Returns the first of the top ``_TITLE_SNIPPET_WINDOW`` lines whose length
    is strictly between the min/max bounds, stripped to word characters,
    spaces, and hyphens, whitespace collapsed to underscores, capped at
    ``_TITLE_SNIPPET_CAP`` chars. Returns None when no line qualifies.
    """
    if not lines:
        return None
    for line in lines[:_TITLE_SNIPPET_WINDOW]:
        if _TITLE_SNIPPET_MIN_CHARS < len(line) < _TITLE_SNIPPET_MAX_CHARS:
            clean = re.sub(r"[^\w\s-]", "", line)
            clean = re.sub(r"\s+", "_", clean.strip())
            if re.search(r"\w", clean):
                return clean[:_TITLE_SNIPPET_CAP]
    return None
