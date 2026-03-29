"""Unit tests for src.analyzers.image_metadata.ImageMetadataParser."""

import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to inject stub modules before the module under test is imported
# ---------------------------------------------------------------------------

def _make_pil_stub() -> types.ModuleType:
    """Return a minimal PIL stub that satisfies the import in image_metadata."""
    import importlib.machinery

    pil = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")
    exif_tags_mod = types.ModuleType("PIL.ExifTags")

    # Give stubs a non-None __spec__ so importlib.util.find_spec doesn't crash
    pil.__spec__ = importlib.machinery.ModuleSpec("PIL", None)
    image_mod.__spec__ = importlib.machinery.ModuleSpec("PIL.Image", None)
    exif_tags_mod.__spec__ = importlib.machinery.ModuleSpec("PIL.ExifTags", None)

    image_mod.open = MagicMock()
    exif_tags_mod.TAGS = {}
    exif_tags_mod.GPSTAGS = {}

    pil.Image = image_mod
    pil.ExifTags = exif_tags_mod
    sys.modules.setdefault("PIL", pil)
    sys.modules.setdefault("PIL.Image", image_mod)
    sys.modules.setdefault("PIL.ExifTags", exif_tags_mod)
    return pil


def _inject_stubs() -> None:
    """Inject all optional-dependency stubs needed by image_metadata."""
    _make_pil_stub()

    # piexif
    sys.modules.setdefault("piexif", types.ModuleType("piexif"))

    # geopy
    geopy = types.ModuleType("geopy")
    geocoders_mod = types.ModuleType("geopy.geocoders")
    exc_mod = types.ModuleType("geopy.exc")

    class _Nominatim:  # minimal stub
        def __init__(self, *a, **kw):
            pass
        def reverse(self, *a, **kw):
            return None

    geocoders_mod.Nominatim = _Nominatim
    exc_mod.GeocoderTimedOut = Exception
    exc_mod.GeocoderServiceError = Exception

    geopy.geocoders = geocoders_mod
    geopy.exc = exc_mod
    sys.modules.setdefault("geopy", geopy)
    sys.modules.setdefault("geopy.geocoders", geocoders_mod)
    sys.modules.setdefault("geopy.exc", exc_mod)

    # cost_roi_calculator
    croi = types.ModuleType("cost_roi_calculator")
    croi.CostROICalculator = MagicMock
    croi.CostTracker = MagicMock
    sys.modules.setdefault("cost_roi_calculator", croi)

    # pillow_heif (optional, just needs to not fail)
    heif = types.ModuleType("pillow_heif")
    heif.register_heif_opener = lambda: None
    sys.modules.setdefault("pillow_heif", heif)


_inject_stubs()

# Now safe to import the module under test
import importlib.util

# Import the specific submodule directly to avoid triggering __init__ (which
# would pull in image_analyzer and its CLIP/torch dependencies).
_spec = importlib.util.spec_from_file_location(
    "src.analyzers.image_metadata",
    str(Path(__file__).parent.parent.parent / "src" / "analyzers" / "image_metadata.py"),
)
_meta_module = importlib.util.module_from_spec(_spec)
sys.modules["src.analyzers.image_metadata"] = _meta_module
_spec.loader.exec_module(_meta_module)  # type: ignore[union-attr]

# Force METADATA_AVAILABLE = True so the parser actually executes logic
_meta_module.METADATA_AVAILABLE = True

ImageMetadataParser = _meta_module.ImageMetadataParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def parser() -> ImageMetadataParser:
    """Return a parser with geocoder disabled (no network calls)."""
    p = ImageMetadataParser()
    p.geocoder = None  # prevent any accidental network call
    return p


@pytest.fixture()
def dummy_path(tmp_path: Path) -> Path:
    f = tmp_path / "test.jpg"
    f.write_bytes(b"fake")
    return f


# ---------------------------------------------------------------------------
# extract_exif_data
# ---------------------------------------------------------------------------

class TestExtractExifData:
    def test_returns_empty_when_metadata_unavailable(self, dummy_path: Path) -> None:
        parser = ImageMetadataParser()
        parser.metadata_available = False
        assert parser.extract_exif_data(dummy_path) == {}

    def test_returns_empty_on_open_failure(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch("src.analyzers.image_metadata.Image.open", side_effect=OSError("bad file")):
            result = parser.extract_exif_data(dummy_path)
        assert result == {}

    def test_returns_empty_when_no_exif(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        mock_img = MagicMock()
        mock_img._getexif.return_value = None
        with patch("src.analyzers.image_metadata.Image.open", return_value=mock_img):
            result = parser.extract_exif_data(dummy_path)
        assert result == {}

    def test_maps_tag_ids_using_TAGS(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        mock_img = MagicMock()
        mock_img._getexif.return_value = {0x0132: "2023:11:26 14:30:00"}  # tag 306 = DateTime

        with patch("src.analyzers.image_metadata.TAGS", {0x0132: "DateTime"}), \
             patch("src.analyzers.image_metadata.Image.open", return_value=mock_img):
            result = parser.extract_exif_data(dummy_path)

        assert result == {"DateTime": "2023:11:26 14:30:00"}


# ---------------------------------------------------------------------------
# extract_datetime
# ---------------------------------------------------------------------------

class TestExtractDatetime:
    def test_returns_none_when_no_exif(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={}):
            assert parser.extract_datetime(dummy_path) is None

    def test_parses_DateTimeOriginal(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={"DateTimeOriginal": "2023:11:26 14:30:00"}):
            result = parser.extract_datetime(dummy_path)
        assert result == datetime(2023, 11, 26, 14, 30, 0)

    def test_falls_back_to_DateTime(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={"DateTime": "2021:01:01 00:00:00"}):
            result = parser.extract_datetime(dummy_path)
        assert result == datetime(2021, 1, 1, 0, 0, 0)

    def test_skips_malformed_tag(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        exif = {"DateTimeOriginal": "NOT-A-DATE", "DateTime": "2022:06:15 08:00:00"}
        with patch.object(parser, "extract_exif_data", return_value=exif):
            result = parser.extract_datetime(dummy_path)
        assert result == datetime(2022, 6, 15, 8, 0, 0)

    def test_returns_none_when_all_tags_missing(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={"Make": "Canon"}):
            assert parser.extract_datetime(dummy_path) is None


# ---------------------------------------------------------------------------
# get_metadata_summary
# ---------------------------------------------------------------------------

class TestGetMetadataSummary:
    def test_all_none_when_no_exif(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={}):
            result = parser.get_metadata_summary(dummy_path)

        assert result["datetime"] is None
        assert result["year"] is None
        assert result["month"] is None
        assert result["date_str"] is None
        assert result["gps_coordinates"] is None
        assert result["location_name"] is None

    def test_populates_datetime_fields(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        dt = datetime(2023, 11, 26, 14, 30, 0)
        exif = {"DateTimeOriginal": "2023:11:26 14:30:00"}
        with patch.object(parser, "extract_exif_data", return_value=exif):
            result = parser.get_metadata_summary(dummy_path)

        assert result["datetime"] == dt
        assert result["year"] == 2023
        assert result["month"] == 11
        assert result["date_str"] == "2023-11"

    def test_populates_location_when_gps_present(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        coords = (37.7749, -122.4194)
        with patch.object(parser, "extract_exif_data", return_value={}), \
             patch.object(parser, "_extract_gps_from_exif", return_value=coords), \
             patch.object(parser, "get_location_name", return_value="San Francisco, CA, USA"):
            result = parser.get_metadata_summary(dummy_path)

        assert result["gps_coordinates"] == coords
        assert result["location_name"] == "San Francisco, CA, USA"


# ---------------------------------------------------------------------------
# _convert_to_degrees
# ---------------------------------------------------------------------------

class TestConvertToDegrees:
    def test_none_input_returns_none(self, parser: ImageMetadataParser) -> None:
        assert parser._convert_to_degrees(None) is None

    def test_empty_input_returns_none(self, parser: ImageMetadataParser) -> None:
        assert parser._convert_to_degrees([]) is None

    def test_correct_conversion(self, parser: ImageMetadataParser) -> None:
        # 37 degrees, 46 minutes, 29.4 seconds
        value = ((37, 1), (46, 1), (294, 10))
        result = parser._convert_to_degrees(value)
        assert result is not None
        assert abs(result - (37 + 46 / 60 + 29.4 / 3600)) < 1e-6
