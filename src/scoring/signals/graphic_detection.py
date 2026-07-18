"""GraphicDetectionSignal — cheap non-CLIP gate for logos/icons/graphics.

CLIP zero-shot cannot distinguish logos and app icons from photographs: real
brand graphics score at the softmax floor (~0.077 in a 13-label vocab) and sit
on CLIP's decision boundary for a binary 'graphic vs. photograph' contrast.
This signal replaces the CLIP attempt with cheap, non-semantic pixel cues
evaluated before CLIP runs (cheap tier → runs in the first wave).

Detection strategy (pre-CLIP gate):

- **SVG extension** — always a graphic; route to ``media/graphics_vector``.
- **Raster images** — scored by up to four independent heuristics; confidence
  is the clamped sum of individual scores.  An image must reach
  ``_MIN_RASTER_CONFIDENCE`` (0.35) to emit a vote.  Routes to
  ``media/graphics_icons`` when it has a transparency channel *and* square
  icon-standard dimensions; ``media/graphics_other`` otherwise.

Heuristic scores (additive, each independent):

1. ``has_alpha`` (+0.40): image has a transparency channel (RGBA, LA, PA
   mode, or P mode with ``transparency`` info).  Brand graphics almost always
   have transparent backgrounds; photographs essentially never do.
2. ``is_square_icon`` (+0.30): width == height and max dimension ≤ 512 px.
   App icons and logos are typically square at standard sizes (16–512 px);
   photographs rarely are.
3. ``small_palette`` (+0.25): after a 64×64 thumbnail, the image has ≤ 64
   distinct sRGB colours.  Flat-colour / limited-palette graphics are far
   below the hundreds-to-thousands of colours a photograph produces.
4. ``asset_path`` (+0.15): the filename's immediate parent directory name is
   one of the known asset-folder names (``assets``, ``icons``, ``img``, etc.).

Pixel analysis is skipped for images larger than ``_PIXEL_ANALYSIS_LIMIT``
(4 MP); only the path-based cues apply in that case (real photos).

Pillow is optional — the signal no-ops (``applies_to`` → False) when
unavailable, matching the graceful-degrade pattern of other heavy-import
signals.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ..context import FileContext

from ..types import CategoryScore
from ..weights import W_GRAPHIC

# ---------------------------------------------------------------------------
# Extension gates
# ---------------------------------------------------------------------------

# SVG is always a graphic — route to vector without opening the file.
SVG_EXTENSION = ".svg"

# Raster formats that can carry transparency or be icon-sized graphics.
RASTER_EXTENSIONS = frozenset(
    {".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico"}
)

# ---------------------------------------------------------------------------
# Category / subcategory targets
# ---------------------------------------------------------------------------

GRAPHICS_CATEGORY = "media"
VECTOR_SUBCATEGORY = "graphics_vector"
ICONS_SUBCATEGORY = "graphics_icons"
OTHER_SUBCATEGORY = "graphics_other"

# ---------------------------------------------------------------------------
# Heuristic score constants
# ---------------------------------------------------------------------------

# SVG files are definitively graphic; high but not absolute (corrupted SVGs).
_SVG_CONFIDENCE = 0.90

# Additive raster scores (each independent).
_SCORE_HAS_ALPHA = 0.40
_SCORE_IS_SQUARE_ICON = 0.30
_SCORE_SMALL_PALETTE = 0.25
_SCORE_ASSET_PATH = 0.15

# Minimum raster confidence to emit a vote (avoids false-positive noise from
# a single weak signal on a real photograph).
_MIN_RASTER_CONFIDENCE = 0.35

# Skip pixel analysis on images larger than this (4 MP) — real photos.
_PIXEL_ANALYSIS_LIMIT = 4_000_000

# Icon size threshold: both dimensions at most this many pixels for square-icon
# detection.  Covers the standard icon set (16 → 512 px).
_ICON_MAX_DIMENSION = 512

# Palette analysis: resample to this grid before counting distinct colours.
_PALETTE_SAMPLE_SIZE = (64, 64)

# Distinct-colour threshold for "small palette" (flat-colour / limited-palette).
_PALETTE_DISTINCT_THRESHOLD = 64

# Asset-folder directory names that hint at graphic content.
_ASSET_FOLDER_NAMES = frozenset(
    {
        "assets",
        "icons",
        "icon",
        "img",
        "images",
        "static",
        "logos",
        "logo",
        "graphics",
        "brand",
        "branding",
        "cdn",
    }
)

# ---------------------------------------------------------------------------
# Evidence keys
# ---------------------------------------------------------------------------

EVIDENCE_SVG = "svg"
EVIDENCE_HAS_ALPHA = "has_alpha"
EVIDENCE_IS_SQUARE_ICON = "is_square_icon"
EVIDENCE_SMALL_PALETTE = "small_palette"
EVIDENCE_ASSET_PATH = "asset_path"
EVIDENCE_GRAPHIC_SCORE = "graphic_score"


# ---------------------------------------------------------------------------
# Pure helper functions (importable by tests without an organizer)
# ---------------------------------------------------------------------------


def _has_alpha_channel(img: object) -> bool:
    """True when the Pillow image has a usable transparency channel."""
    mode = getattr(img, "mode", "")
    if mode in {"RGBA", "LA", "PA"}:
        return True
    if mode == "P":
        info = getattr(img, "info", {})
        return "transparency" in info
    return False


def _is_square_icon_size(width: int, height: int) -> bool:
    """True when the image is square and within the icon size range."""
    return width == height and max(width, height) <= _ICON_MAX_DIMENSION


def _count_distinct_colors(img: object) -> Optional[int]:
    """Return the number of distinct sRGB colours in a small thumbnail.

    Resizes to ``_PALETTE_SAMPLE_SIZE`` first so the cost is bounded.
    Returns None when Pillow operations fail.
    """
    try:
        thumbnail = img.resize(_PALETTE_SAMPLE_SIZE)  # type: ignore[attr-defined]
        rgb = thumbnail.convert("RGB")
        # get_flattened_data added in Pillow 10; fall back to getdata for older.
        getter = getattr(rgb, "get_flattened_data", None) or rgb.getdata
        return len(set(getter()))
    except Exception:
        return None


def _asset_path_hint(path: Path) -> bool:
    """True when the immediate parent directory name is an asset folder."""
    parent_name = path.parent.name.lower()
    return parent_name in _ASSET_FOLDER_NAMES


def score_raster_graphic(path: Path, img: object) -> tuple[float, dict]:
    """Compute the additive raster-graphic confidence and evidence dict.

    Returns ``(confidence, evidence)``.  The caller is responsible for
    opening and closing the Pillow image object.
    """
    score = 0.0
    evidence: dict = {}

    try:
        width: int = img.width  # type: ignore[attr-defined]
        height: int = img.height  # type: ignore[attr-defined]
        pixel_count = width * height
    except Exception:
        return 0.0, {}

    # --- 1. Transparency channel (most discriminative for logos) ----------
    if _has_alpha_channel(img):
        score += _SCORE_HAS_ALPHA
        evidence[EVIDENCE_HAS_ALPHA] = True

    # --- 2. Square icon dimensions ----------------------------------------
    if _is_square_icon_size(width, height):
        score += _SCORE_IS_SQUARE_ICON
        evidence[EVIDENCE_IS_SQUARE_ICON] = True

    # --- 3. Small palette (skip for large images — they are real photos) --
    if pixel_count <= _PIXEL_ANALYSIS_LIMIT:
        distinct = _count_distinct_colors(img)
        if distinct is not None and distinct <= _PALETTE_DISTINCT_THRESHOLD:
            score += _SCORE_SMALL_PALETTE
            evidence[EVIDENCE_SMALL_PALETTE] = distinct

    # --- 4. Asset-folder path hint ----------------------------------------
    if _asset_path_hint(path):
        score += _SCORE_ASSET_PATH
        evidence[EVIDENCE_ASSET_PATH] = True

    evidence[EVIDENCE_GRAPHIC_SCORE] = round(score, 3)
    return min(score, 1.0), evidence


# ---------------------------------------------------------------------------
# Signal class
# ---------------------------------------------------------------------------


class GraphicDetectionSignal:
    """Cheap non-CLIP gate that routes logos/icons/graphics to Media/Graphics.

    Cost tier is 'cheap' so it runs in the first wave, before CLIP and OCR,
    acting as a pre-CLIP gate for files the CLIP vocab cannot distinguish.

    Gracefully no-ops when Pillow is absent (SVG routing still works; raster
    analysis is skipped via ``applies_to`` → True but pixel analysis returns
    0.0 if the import fails inside ``score_raster_graphic``).
    """

    name = "graphic_detection"
    weight = W_GRAPHIC
    cost_tier = "cheap"

    def applies_to(self, ctx: "FileContext") -> bool:
        ext = ctx.path.suffix.lower()
        return ext == SVG_EXTENSION or ext in RASTER_EXTENSIONS

    def run(self, ctx: "FileContext") -> List[CategoryScore]:
        ext = ctx.path.suffix.lower()

        # SVG: always a vector graphic.
        if ext == SVG_EXTENSION:
            return [
                CategoryScore(
                    category=GRAPHICS_CATEGORY,
                    subcategory=VECTOR_SUBCATEGORY,
                    confidence=_SVG_CONFIDENCE,
                    signal_name=self.name,
                    evidence={EVIDENCE_SVG: True},
                )
            ]

        # Raster images: score from cheap pixel/path heuristics.
        if ext not in RASTER_EXTENSIONS:
            return []

        try:
            from PIL import Image  # noqa: PLC0415 — optional dep
        except ImportError:
            return []

        try:
            with Image.open(ctx.path) as img:
                confidence, evidence = score_raster_graphic(ctx.path, img)
        except Exception:
            return []

        if confidence < _MIN_RASTER_CONFIDENCE:
            return []

        # Route: transparency + square icon → icons; otherwise other.
        is_icon = bool(
            evidence.get(EVIDENCE_HAS_ALPHA) and evidence.get(EVIDENCE_IS_SQUARE_ICON)
        )
        subcategory = ICONS_SUBCATEGORY if is_icon else OTHER_SUBCATEGORY

        return [
            CategoryScore(
                category=GRAPHICS_CATEGORY,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence=evidence,
            )
        ]
