"""Unit tests for src.analyzers.image_metadata.ImageMetadataParser."""

import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Optional
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
# piexif fallback
# ---------------------------------------------------------------------------

_PIEXIF_TAGS = {0x0132: "DateTime", 0x9003: "DateTimeOriginal"}
_PIEXIF_GPSTAGS = {
    1: "GPSLatitudeRef",
    2: "GPSLatitude",
    3: "GPSLongitudeRef",
    4: "GPSLongitude",
}


def _piexif_stub(exif_dict: dict) -> MagicMock:
    stub = MagicMock()
    stub.load.return_value = exif_dict
    return stub


def _pil_no_exif() -> MagicMock:
    mock_img = MagicMock()
    mock_img._getexif.return_value = None
    return mock_img


class TestPiexifFallback:
    def test_normalizes_tags_and_decodes_bytes(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        piexif_data = {
            "0th": {0x0132: b"2023:11:26 14:30:00\x00"},
            "Exif": {0x9003: b"2023:11:26 14:30:00"},
            "GPS": {},
        }
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.piexif", _piexif_stub(piexif_data)), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", _PIEXIF_TAGS):
            result = parser.extract_exif_data(dummy_path)

        assert result["DateTime"] == "2023:11:26 14:30:00"
        assert result["DateTimeOriginal"] == "2023:11:26 14:30:00"

    def test_pil_exif_wins_when_present(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        mock_img = MagicMock()
        mock_img._getexif.return_value = {0x0132: "2023:01:01 00:00:00"}
        piexif_mock = _piexif_stub({"0th": {0x0132: b"1999:01:01 00:00:00"}})
        with patch("src.analyzers.image_metadata.Image.open", return_value=mock_img), \
             patch("src.analyzers.image_metadata.piexif", piexif_mock), \
             patch("src.analyzers.image_metadata.TAGS", _PIEXIF_TAGS):
            result = parser.extract_exif_data(dummy_path)

        assert result == {"DateTime": "2023:01:01 00:00:00"}
        piexif_mock.load.assert_not_called()

    def test_datetime_end_to_end_via_fallback(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        piexif_data = {"Exif": {0x9003: b"2023:11:26 14:30:00"}}
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.piexif", _piexif_stub(piexif_data)), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", _PIEXIF_TAGS):
            dt = parser.extract_datetime(dummy_path)

        assert dt == datetime(2023, 11, 26, 14, 30, 0)

    def test_gps_end_to_end_via_fallback(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        piexif_data = {
            "GPS": {
                1: b"N",
                2: ((37, 1), (46, 1), (294, 10)),
                3: b"W",
                4: ((122, 1), (25, 1), (0, 1)),
            }
        }
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.piexif", _piexif_stub(piexif_data)), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.GPSTAGS", _PIEXIF_GPSTAGS):
            coords = parser.extract_gps_coordinates(dummy_path)

        assert coords is not None
        lat, lon = coords
        assert abs(lat - (37 + 46 / 60 + 29.4 / 3600)) < 1e-6
        assert abs(lon - -(122 + 25 / 60)) < 1e-6

    def test_gps_retry_when_pil_gpsinfo_is_bare_offset(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        """PIL EXIF present (so no whole-dict fallback) but GPSInfo is an IFD
        offset int — GPS should still resolve via the piexif retry."""
        mock_img = MagicMock()
        mock_img._getexif.return_value = {0x0132: "2024:05:01 10:20:30", 0x8825: 746}
        piexif_data = {
            "GPS": {
                1: b"N",
                2: ((37, 1), (46, 1), (294, 10)),
                3: b"W",
                4: ((122, 1), (25, 1), (0, 1)),
            }
        }
        with patch("src.analyzers.image_metadata.Image.open", return_value=mock_img), \
             patch("src.analyzers.image_metadata.piexif", _piexif_stub(piexif_data)), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", {**_PIEXIF_TAGS, 0x8825: "GPSInfo"}), \
             patch("src.analyzers.image_metadata.GPSTAGS", _PIEXIF_GPSTAGS):
            coords = parser.extract_gps_coordinates(dummy_path)

        assert coords is not None
        assert abs(coords[0] - (37 + 46 / 60 + 29.4 / 3600)) < 1e-6

    def test_load_failure_returns_empty(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        piexif_mock = MagicMock()
        piexif_mock.load.side_effect = ValueError("not a jpeg")
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.piexif", piexif_mock), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True):
            assert parser.extract_exif_data(dummy_path) == {}

    def test_unavailable_returns_empty(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", False):
            assert parser.extract_exif_data(dummy_path) == {}

    def test_piexif_loaded_at_most_once_when_no_gps(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        """PIL empty + piexif has no GPS: piexif.load() must run once (extract),
        not twice (the old GPS retry re-loaded the same file)."""
        piexif_mock = _piexif_stub({"Exif": {0x9003: b"2023:11:26 14:30:00"}})
        with patch("src.analyzers.image_metadata.Image.open", return_value=_pil_no_exif()), \
             patch("src.analyzers.image_metadata.piexif", piexif_mock), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", _PIEXIF_TAGS):
            coords = parser.extract_gps_coordinates(dummy_path)
        assert coords is None
        piexif_mock.load.assert_called_once()

    def test_non_gps_pil_exif_never_loads_piexif(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        """A non-GPS image PIL can read (no GPSInfo key) must not touch piexif."""
        mock_img = MagicMock()
        mock_img._getexif.return_value = {0x0132: "2023:01:01 00:00:00"}
        piexif_mock = _piexif_stub({})
        with patch("src.analyzers.image_metadata.Image.open", return_value=mock_img), \
             patch("src.analyzers.image_metadata.piexif", piexif_mock), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", _PIEXIF_TAGS):
            coords = parser.extract_gps_coordinates(dummy_path)
        assert coords is None
        piexif_mock.load.assert_not_called()

    def test_bare_offset_gpsinfo_normalized_to_dict_in_exif(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        """extract_exif_data itself resolves a bare-offset GPSInfo into a dict,
        so callers reusing the returned exif_data get GPS without a re-read."""
        mock_img = MagicMock()
        mock_img._getexif.return_value = {0x8825: 746}  # GPSInfo as bare IFD offset
        piexif_data = {"GPS": {1: b"N", 2: ((37, 1), (46, 1), (294, 10)),
                               3: b"W", 4: ((122, 1), (25, 1), (0, 1))}}
        with patch("src.analyzers.image_metadata.Image.open", return_value=mock_img), \
             patch("src.analyzers.image_metadata.piexif", _piexif_stub(piexif_data)), \
             patch("src.analyzers.image_metadata.PIEXIF_AVAILABLE", True), \
             patch("src.analyzers.image_metadata.TAGS", {0x8825: "GPSInfo"}):
            exif_data = parser.extract_exif_data(dummy_path)
        assert isinstance(exif_data["GPSInfo"], dict)
        assert exif_data["GPSInfo"][1] == "N"


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

    def test_includes_text_metadata(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={}), \
             patch.object(parser, "extract_text_metadata", return_value={"Software": "GIMP"}):
            result = parser.get_metadata_summary(dummy_path)
        assert result["text_metadata"] == {"Software": "GIMP"}

    def test_creation_time_used_as_datetime_fallback(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={}), \
             patch.object(parser, "extract_text_metadata",
                          return_value={"Creation Time": "2021-08-15T09:30:00"}):
            result = parser.get_metadata_summary(dummy_path)
        assert result["datetime"] == datetime(2021, 8, 15, 9, 30, 0)
        assert result["year"] == 2021
        assert result["date_str"] == "2021-08"

    def test_exif_datetime_wins_over_creation_time(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch.object(parser, "extract_exif_data", return_value={"DateTimeOriginal": "2023:11:26 14:30:00"}), \
             patch.object(parser, "extract_text_metadata",
                          return_value={"Creation Time": "2021-08-15T09:30:00"}):
            result = parser.get_metadata_summary(dummy_path)
        assert result["datetime"] == datetime(2023, 11, 26, 14, 30, 0)


# ---------------------------------------------------------------------------
# extract_text_metadata (GIF / PNG textual metadata)
# ---------------------------------------------------------------------------

def _mock_text_image(text: Optional[dict] = None, info: Optional[dict] = None) -> MagicMock:
    """Mock image usable as a context manager, exposing .text and .info dicts."""
    img = MagicMock()
    img.__enter__.return_value = img
    img.__exit__.return_value = False
    img.text = text if text is not None else {}
    img.info = info if info is not None else {}
    return img


class TestExtractTextMetadata:
    def test_returns_empty_when_metadata_unavailable(self, dummy_path: Path) -> None:
        p = ImageMetadataParser()
        p.metadata_available = False
        assert p.extract_text_metadata(dummy_path) == {}

    def test_returns_empty_on_open_failure(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        with patch("src.analyzers.image_metadata.Image.open", side_effect=OSError("bad file")):
            assert parser.extract_text_metadata(dummy_path) == {}

    def test_reads_png_text_chunks_and_strips(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        img = _mock_text_image(text={"Software": "GIMP", "Description": "  a render  "})
        with patch("src.analyzers.image_metadata.Image.open", return_value=img):
            result = parser.extract_text_metadata(dummy_path)
        assert result == {"Software": "GIMP", "Description": "a render"}

    def test_reads_gif_comment_from_info_and_decodes_bytes(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        img = _mock_text_image(info={"comment": b"Made with X", "duration": 100})
        with patch("src.analyzers.image_metadata.Image.open", return_value=img):
            result = parser.extract_text_metadata(dummy_path)
        assert result == {"comment": "Made with X"}

    def test_ignores_unlisted_keys_and_empty_values(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        img = _mock_text_image(text={"Title": "   ", "icc_profile": "x"}, info={"dpi": (72, 72)})
        with patch("src.analyzers.image_metadata.Image.open", return_value=img):
            assert parser.extract_text_metadata(dummy_path) == {}

    def test_text_chunk_wins_over_info_duplicate(self, dummy_path: Path, parser: ImageMetadataParser) -> None:
        img = _mock_text_image(text={"Comment": "from-text"}, info={"Comment": "from-info"})
        with patch("src.analyzers.image_metadata.Image.open", return_value=img):
            assert parser.extract_text_metadata(dummy_path) == {"Comment": "from-text"}


class TestNormalizeTextValue:
    def test_strips_str(self) -> None:
        assert ImageMetadataParser._normalize_text_value("  hi  ") == "hi"

    def test_decodes_utf8_bytes(self) -> None:
        assert ImageMetadataParser._normalize_text_value(b"hi") == "hi"

    def test_empty_after_strip_returns_none(self) -> None:
        assert ImageMetadataParser._normalize_text_value("   ") is None

    def test_non_text_returns_none(self) -> None:
        assert ImageMetadataParser._normalize_text_value(123) is None

    def test_undecodable_bytes_returns_none(self) -> None:
        assert ImageMetadataParser._normalize_text_value(b"\xff\xfe") is None


class TestParseCreationTime:
    def test_iso_8601(self, parser: ImageMetadataParser) -> None:
        assert parser._parse_creation_time({"Creation Time": "2021-08-15T09:30:00"}) == datetime(2021, 8, 15, 9, 30, 0)

    def test_date_only(self, parser: ImageMetadataParser) -> None:
        assert parser._parse_creation_time({"Creation Time": "2021-08-15"}) == datetime(2021, 8, 15)

    def test_missing_key_returns_none(self, parser: ImageMetadataParser) -> None:
        assert parser._parse_creation_time({}) is None

    def test_unparseable_returns_none(self, parser: ImageMetadataParser) -> None:
        assert parser._parse_creation_time({"Creation Time": "last tuesday"}) is None


# ---------------------------------------------------------------------------
# get_location_name
# ---------------------------------------------------------------------------

def _fake_geocoder(address: dict) -> MagicMock:
    """Geocoder stub whose reverse() returns a location with the given address."""
    location = MagicMock()
    location.raw = {"address": address}
    geocoder = MagicMock()
    geocoder.reverse.return_value = location
    return geocoder


class TestGetLocationName:
    def test_none_when_geocoder_unavailable(self, parser: ImageMetadataParser) -> None:
        assert parser.get_location_name((37.77, -122.42)) is None

    def test_city_state_country(self, parser: ImageMetadataParser) -> None:
        parser.geocoder = _fake_geocoder(
            {"city": "San Francisco", "state": "California", "country": "USA"}
        )
        assert parser.get_location_name((37.77, -122.42)) == "San Francisco, California, USA"

    def test_town_preferred_over_county(self, parser: ImageMetadataParser) -> None:
        parser.geocoder = _fake_geocoder({"town": "Marfa", "county": "Presidio County"})
        assert parser.get_location_name((30.31, -104.02)) == "Marfa"

    def test_county_fallback_when_no_locality(self, parser: ImageMetadataParser) -> None:
        parser.geocoder = _fake_geocoder(
            {"county": "Presidio County", "state": "Texas", "country": "USA"}
        )
        assert parser.get_location_name((30.31, -104.02)) == "Presidio County, Texas, USA"

    def test_none_when_address_empty(self, parser: ImageMetadataParser) -> None:
        parser.geocoder = _fake_geocoder({})
        assert parser.get_location_name((0.0, 0.0)) is None


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

    def test_plain_float_components(self, parser: ImageMetadataParser) -> None:
        # Modern Pillow returns floats/IFDRationals, not (num, den) pairs
        result = parser._convert_to_degrees((37.0, 46.0, 29.4))
        assert result is not None
        assert abs(result - (37 + 46 / 60 + 29.4 / 3600)) < 1e-6

    def test_mixed_components(self, parser: ImageMetadataParser) -> None:
        result = parser._convert_to_degrees((37.0, (46, 1), 29.4))
        assert result is not None
        assert abs(result - (37 + 46 / 60 + 29.4 / 3600)) < 1e-6

    def test_zero_denominator_returns_none(self, parser: ImageMetadataParser) -> None:
        assert parser._convert_to_degrees(((37, 0), (46, 1), (294, 10))) is None
