"""GraphicDetectionSignal tests — cheap non-CLIP gate for logos/icons/graphics.

Uses in-memory Pillow images and synthetic path objects so no real files or
CLIP model are needed.  Covers:

- SVG routing (always vector, no Pillow open required)
- Raster: transparency + square dims → icons subcategory
- Raster: transparency only → graphics_other
- Raster: small palette only → graphics_other (above threshold)
- Raster: asset-path hint alone → below threshold, no vote
- Raster: asset-path + small palette → just above threshold
- Raster: plain photograph (large, no alpha, high palette) → no vote
- applies_to gates (extension filter)
- score_raster_graphic pure helper (unit-testable without signal)
"""

import io
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.graphic_detection import (
    EVIDENCE_ASSET_PATH,
    EVIDENCE_HAS_ALPHA,
    EVIDENCE_IS_SQUARE_ICON,
    EVIDENCE_SMALL_PALETTE,
    EVIDENCE_SVG,
    GRAPHICS_CATEGORY,
    ICONS_SUBCATEGORY,
    OTHER_SUBCATEGORY,
    VECTOR_SUBCATEGORY,
    GraphicDetectionSignal,
    _asset_path_hint,
    _has_alpha_channel,
    _is_square_icon_size,
    score_raster_graphic,
)
from src.scoring.weights import W_GRAPHIC

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

requires_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(path: str, schema_type: str = "ImageObject") -> FileContext:
    return FileContext(path=Path(path), schema_type=schema_type)


def _pil_rgba_square(size: int = 64) -> "Image.Image":
    """Create a small RGBA image with a transparent background."""
    img = Image.new("RGBA", (size, size), (255, 0, 0, 0))
    return img


def _pil_rgb_photo(width: int = 1920, height: int = 1080) -> "Image.Image":
    """Create a large RGB image simulating a photograph (no alpha)."""
    import random

    img = Image.new("RGB", (width, height))
    pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
              for _ in range(width * height)]
    img.putdata(pixels)
    return img


def _pil_rgb_small_palette(size: int = 64, num_colors: int = 4) -> "Image.Image":
    """Create a flat-colour image with very few distinct colours."""
    colors = [(i * 40, 0, 0) for i in range(num_colors)]
    img = Image.new("RGB", (size, size))
    block = size // num_colors
    for i, color in enumerate(colors):
        for x in range(i * block, (i + 1) * block):
            for y in range(size):
                img.putpixel((x, y), color)
    return img


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHasAlphaChannel:
    @requires_pil
    def test_rgba_mode(self):
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        assert _has_alpha_channel(img) is True

    @requires_pil
    def test_la_mode(self):
        img = Image.new("LA", (10, 10), (0, 0))
        assert _has_alpha_channel(img) is True

    @requires_pil
    def test_rgb_mode_no_alpha(self):
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        assert _has_alpha_channel(img) is False

    @requires_pil
    def test_p_mode_with_transparency(self):
        img = Image.new("P", (10, 10))
        img.info["transparency"] = 0
        assert _has_alpha_channel(img) is True

    @requires_pil
    def test_p_mode_no_transparency(self):
        img = Image.new("P", (10, 10))
        assert _has_alpha_channel(img) is False


class TestIsSquareIconSize:
    def test_64x64_square(self):
        assert _is_square_icon_size(64, 64) is True

    def test_512x512_max_boundary(self):
        assert _is_square_icon_size(512, 512) is True

    def test_513x513_above_boundary(self):
        assert _is_square_icon_size(513, 513) is False

    def test_non_square(self):
        assert _is_square_icon_size(100, 200) is False

    def test_1x1_square(self):
        assert _is_square_icon_size(1, 1) is True


class TestAssetPathHint:
    def test_icons_dir(self):
        assert _asset_path_hint(Path("/project/icons/logo.png")) is True

    def test_assets_dir(self):
        assert _asset_path_hint(Path("/site/assets/banner.png")) is True

    def test_img_dir(self):
        assert _asset_path_hint(Path("/web/img/hero.webp")) is True

    def test_logos_dir(self):
        assert _asset_path_hint(Path("/brand/logos/mark.svg")) is True

    def test_cdn_dir(self):
        assert _asset_path_hint(Path("/cdn/graphic.png")) is True

    def test_random_dir(self):
        assert _asset_path_hint(Path("/Users/alyshia/Downloads/photo.jpg")) is False

    def test_documents_dir(self):
        assert _asset_path_hint(Path("/Users/alyshia/Documents/report.pdf")) is False


# ---------------------------------------------------------------------------
# score_raster_graphic unit tests
# ---------------------------------------------------------------------------


class TestScoreRasterGraphic:
    @requires_pil
    def test_transparent_square_icon_high_score(self):
        img = _pil_rgba_square(64)
        score, evidence = score_raster_graphic(Path("/icons/logo.png"), img)
        # has_alpha (0.40) + is_square_icon (0.30) = 0.70 minimum
        assert score >= 0.70
        assert evidence[EVIDENCE_HAS_ALPHA] is True
        assert evidence[EVIDENCE_IS_SQUARE_ICON] is True

    @requires_pil
    def test_asset_path_adds_to_score(self):
        img = _pil_rgba_square(64)
        score_no_asset, _ = score_raster_graphic(Path("/downloads/logo.png"), img)
        score_with_asset, evidence = score_raster_graphic(Path("/icons/logo.png"), img)
        assert score_with_asset > score_no_asset
        assert evidence.get(EVIDENCE_ASSET_PATH) is True

    @requires_pil
    def test_small_palette_detected(self):
        img = _pil_rgb_small_palette(64, num_colors=4)
        score, evidence = score_raster_graphic(Path("/tmp/flat.png"), img)
        assert EVIDENCE_SMALL_PALETTE in evidence
        assert evidence[EVIDENCE_SMALL_PALETTE] <= 64

    @requires_pil
    def test_non_square_rgba_routes_other(self):
        img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        score, evidence = score_raster_graphic(Path("/tmp/banner.png"), img)
        # has_alpha fires; square-icon does not (non-square).
        assert evidence.get(EVIDENCE_HAS_ALPHA) is True
        assert EVIDENCE_IS_SQUARE_ICON not in evidence
        # Score must be at least has_alpha (0.40) and may include small_palette
        # for the uniform fill — just confirm it exceeds the emission threshold.
        assert score >= 0.40


# ---------------------------------------------------------------------------
# GraphicDetectionSignal.applies_to
# ---------------------------------------------------------------------------


class TestAppliesTo:
    def setup_method(self):
        self.signal = GraphicDetectionSignal()

    def test_svg_applies(self):
        ctx = make_ctx("/assets/logo.svg")
        assert self.signal.applies_to(ctx) is True

    def test_png_applies(self):
        ctx = make_ctx("/icons/icon.png")
        assert self.signal.applies_to(ctx) is True

    def test_webp_applies(self):
        ctx = make_ctx("/brand/logo.webp")
        assert self.signal.applies_to(ctx) is True

    def test_gif_applies(self):
        ctx = make_ctx("/assets/animated.gif")
        assert self.signal.applies_to(ctx) is True

    def test_ico_applies(self):
        ctx = make_ctx("/assets/favicon.ico")
        assert self.signal.applies_to(ctx) is True

    def test_jpg_skipped(self):
        ctx = make_ctx("/photos/portrait.jpg")
        assert self.signal.applies_to(ctx) is False

    def test_pdf_skipped(self):
        ctx = make_ctx("/documents/contract.pdf")
        assert self.signal.applies_to(ctx) is False

    def test_mp4_skipped(self):
        ctx = make_ctx("/media/video.mp4")
        assert self.signal.applies_to(ctx) is False


# ---------------------------------------------------------------------------
# GraphicDetectionSignal.run — SVG routing
# ---------------------------------------------------------------------------


class TestRunSVG:
    def setup_method(self):
        self.signal = GraphicDetectionSignal()

    def test_svg_routes_to_vector(self):
        ctx = make_ctx("/assets/logo.svg")
        scores = self.signal.run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert score.category == GRAPHICS_CATEGORY
        assert score.subcategory == VECTOR_SUBCATEGORY
        assert score.confidence >= 0.85
        assert score.signal_name == "graphic_detection"
        assert score.evidence.get(EVIDENCE_SVG) is True

    def test_svg_does_not_open_file(self):
        """SVG detection must not attempt to open the file via Pillow."""
        ctx = make_ctx("/nonexistent/logo.svg")
        # Should succeed even though the file doesn't exist.
        scores = self.signal.run(ctx)
        assert len(scores) == 1
        assert scores[0].subcategory == VECTOR_SUBCATEGORY

    def test_signal_weight(self):
        assert self.signal.weight == W_GRAPHIC

    def test_cost_tier(self):
        assert self.signal.cost_tier == "cheap"


# ---------------------------------------------------------------------------
# GraphicDetectionSignal.run — raster routing (requires PIL)
# ---------------------------------------------------------------------------


class TestRunRaster:
    def setup_method(self):
        self.signal = GraphicDetectionSignal()

    @requires_pil
    def test_transparent_square_routes_to_icons(self, tmp_path):
        img = _pil_rgba_square(64)
        path = tmp_path / "logo.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        assert len(scores) == 1
        assert scores[0].subcategory == ICONS_SUBCATEGORY

    @requires_pil
    def test_transparent_non_square_routes_to_other(self, tmp_path):
        img = Image.new("RGBA", (200, 100), (255, 0, 0, 0))
        path = tmp_path / "banner.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        # has_alpha = 0.40 → above threshold; non-square → other
        assert len(scores) == 1
        assert scores[0].subcategory == OTHER_SUBCATEGORY

    @requires_pil
    def test_small_palette_asset_path_routes_to_other(self, tmp_path):
        # asset-path (0.15) + small-palette (0.25) = 0.40 → above threshold
        img = _pil_rgb_small_palette(64, num_colors=2)
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        path = icons_dir / "flat.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        assert len(scores) == 1
        assert scores[0].category == GRAPHICS_CATEGORY
        assert scores[0].subcategory == OTHER_SUBCATEGORY

    @requires_pil
    def test_real_photo_no_vote(self, tmp_path):
        """Large RGB photograph with no alpha/palette signals → no vote."""
        # Use a 100x67 RGB image with many distinct colours to simulate a photo.
        img = Image.new("RGB", (100, 67))
        import random
        random.seed(42)
        pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                  for _ in range(100 * 67)]
        img.putdata(pixels)
        path = tmp_path / "photo.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        # photo.png is not in an asset dir, has no alpha, and has a large palette
        assert scores == []

    @requires_pil
    def test_asset_path_alone_below_threshold(self, tmp_path):
        """Asset path (+0.15) alone is below _MIN_RASTER_CONFIDENCE (0.35)."""
        import random
        random.seed(42)
        img = Image.new("RGB", (100, 67))
        pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                  for _ in range(100 * 67)]
        img.putdata(pixels)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        path = assets_dir / "photo.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        assert scores == []

    @requires_pil
    def test_missing_file_no_vote(self):
        """A missing file must not raise — just return empty."""
        ctx = make_ctx("/nonexistent/graphic.png")
        scores = self.signal.run(ctx)
        assert scores == []

    @requires_pil
    def test_evidence_contains_graphic_score(self, tmp_path):
        img = _pil_rgba_square(32)
        path = tmp_path / "icon.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        assert len(scores) == 1
        assert "graphic_score" in scores[0].evidence

    @requires_pil
    def test_signal_name_tagged_correctly(self, tmp_path):
        img = _pil_rgba_square(32)
        path = tmp_path / "icon.png"
        img.save(path)
        ctx = make_ctx(str(path))
        scores = self.signal.run(ctx)
        assert all(s.signal_name == "graphic_detection" for s in scores)
