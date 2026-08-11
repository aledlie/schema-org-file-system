"""
Image metadata parsing: EXIF, GPS coordinates, timestamps, and reverse geocoding.
"""

import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    Dict,
    Literal,
    Mapping,
    Optional,
    Sequence,
    TYPE_CHECKING,
    Tuple,
    TypedDict,
    cast,
)

if TYPE_CHECKING:
    # The bare cost_roi_calculator import below is Any to mypy; the
    # src.-prefixed form is the one that resolves.
    from src.cost_roi_calculator import CostROICalculator

# PIL / geopy are optional
try:
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, IFD, TAGS
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderServiceError, GeocoderTimedOut
    from geopy.extra.rate_limiter import RateLimiter

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass

    METADATA_AVAILABLE = True
except ImportError:
    METADATA_AVAILABLE = False

# EXIF tag name under which the GPS sub-IFD is nested, in every shape this
# module produces (PIL legacy, PIL public accessor, piexif fallback).
GPS_INFO_TAG = "GPSInfo"

# Forward-geocoding rate limit / retries (OSM Nominatim policy: <=1 req/s) and
# the on-disk result cache shared across runs (keyed by normalized address).
GEOCODE_MIN_DELAY_SEC = 1.0
GEOCODE_MAX_RETRIES = 2
GEOCODE_CACHE_PATH = Path(".cache") / "geocode_cache.sqlite"

# piexif reads EXIF from some JPEG/HEIC/WebP files where PIL's _getexif()
# comes back empty; used only as a fallback.
try:
    import piexif

    PIEXIF_AVAILABLE = True
except ImportError:
    PIEXIF_AVAILABLE = False

# Non-EXIF textual metadata that GIF and PNG files can carry. GIF exposes a free
# text "comment" in image.info; PNG exposes these as tEXt/iTXt/zTXt chunks, read
# via image.info and PngImageFile.text. Keys mirror the PNG registered keywords
# plus GIF's lowercase "comment".
_TEXT_METADATA_KEYS: Tuple[str, ...] = (
    "comment",
    "Comment",
    "Title",
    "Author",
    "Description",
    "Copyright",
    "Software",
    "Source",
    "Creation Time",
)

# Cost tracking is optional
try:
    from cost_roi_calculator import CostTracker
except ImportError:

    class CostTracker:  # type: ignore[no-redef]
        """Stub when cost tracking is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "CostTracker":
            return self

        def __exit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
        ) -> Literal[False]:
            return False


class GeocodedLocation(TypedDict):
    """``geocode_address()`` result shape."""

    display_name: str
    latitude: float
    longitude: float
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]


class ImageMetadataParser:
    """Parses image metadata including EXIF, GPS, and timestamps."""

    def __init__(self, cost_calculator: Optional["CostROICalculator"] = None) -> None:
        """
        Initialize the metadata parser.

        Args:
            cost_calculator: Optional cost calculator for tracking usage costs
        """
        self.metadata_available = METADATA_AVAILABLE
        self.geocoder = None
        self.cost_calculator = cost_calculator
        # Rate-limited forward-geocode callable (Nominatim policy: <=1 req/s).
        # Set alongside self.geocoder; None when geocoding is unavailable.
        self._forward_geocode = None

        if self.metadata_available:
            try:
                self.geocoder = Nominatim(user_agent="file_organizer_v1.0", timeout=5)
                # 1 req/s honors OSM Nominatim usage policy; combined with the
                # on-disk cache this keeps large batches from hammering the
                # public endpoint (the reverse path has no such guard).
                self._forward_geocode = RateLimiter(
                    self.geocoder.geocode,
                    min_delay_seconds=GEOCODE_MIN_DELAY_SEC,
                    max_retries=GEOCODE_MAX_RETRIES,
                    swallow_exceptions=False,
                )
            except Exception as e:
                print(f"Warning: Could not initialize geocoder: {e}")
                self.geocoder = None
                self._forward_geocode = None

    def extract_exif_data(self, image_path: Path) -> Dict[str, Any]:
        """
        Extract EXIF data from an image.

        Returns:
            Dictionary with EXIF data
        """
        if not self.metadata_available:
            return {}

        exif_data: Dict[str, Any] = {}
        try:
            image = Image.open(image_path)
            # _getexif is the legacy private accessor; it only exists on formats
            # that carry EXIF (JPEG/TIFF/WebP/HEIC). Formats like GIF/PNG lack it,
            # so probe for it rather than letting the call raise AttributeError.
            getexif = getattr(image, "_getexif", None)
            exif = getexif() if getexif is not None else None
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    exif_data[tag] = value
            else:
                exif_data = self._extract_exif_via_public_accessor(image)
        except Exception as e:
            print(f"  EXIF extraction error: {e}")

        # piexif fallback, consolidated so piexif.load() runs at most once per
        # call:
        #  - PIL read empty (a format PIL can't decode) → take piexif's EXIF.
        #  - GPSInfo present but a bare IFD offset (int) rather than a dict → PIL
        #    left the GPS IFD undecoded; recover just that from piexif.
        # A missing GPSInfo key means the file carries no GPS, so piexif is
        # skipped entirely for non-GPS images.
        gps_is_bare_offset = GPS_INFO_TAG in exif_data and not isinstance(
            exif_data[GPS_INFO_TAG], dict
        )
        if not exif_data or gps_is_bare_offset:
            piexif_data = self._extract_exif_via_piexif(image_path)
            if not exif_data:
                exif_data = piexif_data
            elif isinstance(piexif_data.get(GPS_INFO_TAG), dict):
                exif_data[GPS_INFO_TAG] = piexif_data[GPS_INFO_TAG]

        return exif_data

    @staticmethod
    def _extract_exif_via_public_accessor(image: "Image.Image") -> Dict[str, Any]:
        """EXIF via PIL's public ``getexif()``, with the Exif/GPS sub-IFDs merged in.

        Required for HEIF/AVIF: ``pillow_heif``'s ``HeifImageFile`` implements only
        the public accessor, so the ``_getexif`` probe finds nothing, and the piexif
        fallback then rejects the container outright (``InvalidImageDataError:
        Given file is neither JPEG nor TIFF``). Every HEIC therefore came back with
        no EXIF at all -- losing capture date (dates fell back to file mtime, i.e.
        download time) and GPS (no ``file->location`` edge), and degrading
        MediaHeuristicSignal from its GPS branch to ``photos/other``, which then
        outvoted SceneSignal and misfiled interiors/exteriors under Media/Photos.

        Not a substitute for ``_getexif`` where that exists: on JPEG ``getexif()``
        returns only the top-level IFD (11 tags vs 54, no ``DateTimeOriginal``), so
        the sub-IFDs are merged explicitly rather than swapping the accessors.
        """
        exif = image.getexif()
        if not exif:
            return {}

        # cast: an unrecognized tag falls back to its numeric id as the key, the
        # same shape the two older paths produce (their loops are over Any, so
        # only this typed path surfaces the int-vs-str key to mypy).
        def tag_name(tag_id: int) -> str:
            return cast(str, TAGS.get(tag_id, tag_id))

        merged: Dict[str, Any] = {tag_name(tag_id): value for tag_id, value in exif.items()}
        # Sub-IFD values lose to the top-level IFD only when a tag is in both.
        for tag_id, value in dict(exif.get_ifd(IFD.Exif) or {}).items():
            merged.setdefault(tag_name(tag_id), value)

        # Kept keyed by numeric GPS tag id: the shape _extract_gps_from_exif's
        # GPSTAGS lookup and the piexif fallback both already produce. Tested for
        # emptiness *after* materializing, so an empty-but-truthy IFD object does
        # not plant a bare {} that reads as "this file carries GPS".
        gps_ifd = dict(exif.get_ifd(IFD.GPSInfo) or {})
        if gps_ifd:
            merged[GPS_INFO_TAG] = gps_ifd

        return merged

    def _extract_exif_via_piexif(self, image_path: Path) -> Dict[str, Any]:
        """Fallback EXIF read via piexif, normalized to the same shape as the
        PIL path: tag names as keys, ASCII bytes decoded to str, and the GPS
        IFD nested under "GPSInfo" keyed by numeric GPS tag ids."""
        # TAGS/GPSTAGS are only imported when PIL is available; guard so a caller
        # that bypasses the outer metadata_available check can't hit a NameError.
        if not PIEXIF_AVAILABLE or not METADATA_AVAILABLE:
            return {}

        try:
            exif_dict = piexif.load(str(image_path))
        except Exception:
            return {}

        def decode(value: Any) -> Any:
            if isinstance(value, bytes):
                try:
                    return value.decode("utf-8").rstrip("\x00")
                except UnicodeDecodeError:
                    return value
            return value

        exif_data: Dict[str, Any] = {}
        for ifd in ("0th", "Exif"):
            for tag_id, value in (exif_dict.get(ifd) or {}).items():
                tag = TAGS.get(tag_id, tag_id)
                exif_data.setdefault(tag, decode(value))

        gps = exif_dict.get("GPS") or {}
        if gps:
            exif_data[GPS_INFO_TAG] = {tag_id: decode(value) for tag_id, value in gps.items()}

        return exif_data

    def extract_text_metadata(self, image_path: Path) -> Dict[str, str]:
        """Extract non-EXIF textual metadata carried by GIF and PNG files.

        GIF exposes a free-text ``comment`` (plus animation fields) in
        ``image.info``; PNG exposes tEXt/iTXt/zTXt chunks (``Software``,
        ``Description``, ``Creation Time``, ...) via ``image.info`` and
        ``PngImageFile.text``. Only keys in ``_TEXT_METADATA_KEYS`` are returned,
        each normalized to a non-empty stripped ``str``.
        """
        if not self.metadata_available:
            return {}

        text_metadata: Dict[str, str] = {}
        try:
            with Image.open(image_path) as image:
                # PngImageFile.text holds decoded text chunks; image.info is the
                # superset (GIF's comment lives only there). Read both.
                for source in (getattr(image, "text", None), image.info):
                    if not source:
                        continue
                    for key, value in source.items():
                        if key not in _TEXT_METADATA_KEYS:
                            continue
                        normalized = self._normalize_text_value(value)
                        if normalized:
                            text_metadata.setdefault(str(key), normalized)
        except Exception as e:
            print(f"  Text metadata extraction error: {e}")

        return text_metadata

    @staticmethod
    def _normalize_text_value(value: object) -> Optional[str]:
        """Coerce a PNG/GIF metadata value to a non-empty stripped str, or None."""
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _parse_creation_time(self, text_metadata: Dict[str, str]) -> Optional[datetime]:
        """Parse a PNG "Creation Time" text chunk into a datetime, best-effort.

        The PNG spec suggests RFC 1123, but tools commonly write ISO 8601; try
        the formats we actually see and return None for anything unrecognized.
        """
        raw = text_metadata.get("Creation Time")
        if not raw:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y:%m:%d %H:%M:%S",
            "%Y-%m-%d",
            "%a, %d %b %Y %H:%M:%S %Z",  # RFC 1123
        ):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    def extract_datetime(
        self, image_path: Path, exif_data: Optional[Dict[str, Any]] = None
    ) -> Optional[datetime]:
        """
        Extract the datetime when the photo was taken.

        Args:
            image_path: Path to the image file
            exif_data: Pre-extracted EXIF data to avoid redundant Image.open() calls

        Returns:
            datetime object or None
        """
        if exif_data is None:
            exif_data = self.extract_exif_data(image_path)
        return self._extract_datetime_from_exif(exif_data)

    def _extract_datetime_from_exif(self, exif_data: Dict[str, Any]) -> Optional[datetime]:
        for tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            if tag in exif_data:
                try:
                    return datetime.strptime(str(exif_data[tag]), "%Y:%m:%d %H:%M:%S")
                except ValueError, TypeError:
                    continue
        return None

    def extract_gps_coordinates(
        self, image_path: Path, exif_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Extract GPS coordinates from image EXIF data.

        Args:
            image_path: Path to the image file
            exif_data: Pre-extracted EXIF data to avoid redundant Image.open() calls

        Returns:
            Tuple of (latitude, longitude) or None
        """
        if not self.metadata_available:
            return None
        if exif_data is None:
            exif_data = self.extract_exif_data(image_path)
        # extract_exif_data already normalizes a bare-offset GPSInfo into a dict
        # via piexif, so no separate GPS retry is needed here.
        return self._extract_gps_from_exif(exif_data)

    def _extract_gps_from_exif(self, exif_data: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        try:
            raw_gps = exif_data.get(GPS_INFO_TAG)
            # GPSInfo can be a bare IFD offset (int) on some files; only a
            # dict payload is usable. Non-dict values are skipped silently.
            if not raw_gps or not isinstance(raw_gps, dict):
                return None

            gps_info: Dict[str, Any] = {
                str(GPSTAGS.get(tag_id, tag_id)): value for tag_id, value in raw_gps.items()
            }

            if not gps_info:
                return None

            lat = self._convert_to_degrees(gps_info.get("GPSLatitude"))
            lon = self._convert_to_degrees(gps_info.get("GPSLongitude"))

            if lat is None or lon is None:
                return None

            if gps_info.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_info.get("GPSLongitudeRef") == "W":
                lon = -lon

            return (lat, lon)

        except Exception as e:
            print(f"  GPS extraction error: {e}")
            return None

    def _convert_to_degrees(self, value: Optional[Sequence[Any]]) -> Optional[float]:
        """
        Convert GPS coordinates to decimal degrees.

        Args:
            value: (degrees, minutes, seconds) where each component is either
                a (numerator, denominator) pair (piexif) or a number /
                PIL IFDRational (modern Pillow).

        Returns:
            Decimal degrees or None
        """
        if not value:
            return None

        def part(component: Any) -> float:
            try:
                return float(component)  # float, int, PIL IFDRational
            except TypeError:
                return float(component[0]) / float(component[1])  # (num, den)

        try:
            d, m, s = (part(value[i]) for i in range(3))
            return d + (m / 60.0) + (s / 3600.0)
        except IndexError, TypeError, ZeroDivisionError, ValueError:
            return None

    def get_location_name(self, coordinates: Tuple[float, float]) -> Optional[str]:
        """
        Get location name from GPS coordinates using reverse geocoding.

        Args:
            coordinates: Tuple of (latitude, longitude)

        Returns:
            Location name (city, state, country) or None
        """
        if not self.geocoder:
            return None

        ctx = (
            CostTracker(self.cost_calculator, "nominatim_geocoding")
            if self.cost_calculator
            else nullcontext()
        )
        with ctx:
            try:
                lat, lon = coordinates
                location = self.geocoder.reverse(f"{lat}, {lon}", exactly_one=True)

                if location and location.raw.get("address"):
                    city, state, country = self._parse_place(location.raw["address"])
                    parts = [p for p in (city, state, country) if p]
                    if parts:
                        return ", ".join(parts)

            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"  Geocoding error: {e}")
            except Exception as e:
                print(f"  Location lookup error: {e}")

            return None

    @staticmethod
    def _parse_place(
        raw_address: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Pull (city, state, country) from a Nominatim ``raw['address']`` dict.

        Shared by reverse (``get_location_name``) and forward
        (``geocode_address``) geocoding so the field-preference order
        (city→town→village→county; state→region) lives in one place.
        """
        city = (
            raw_address.get("city")
            or raw_address.get("town")
            or raw_address.get("village")
            or raw_address.get("county")
        )
        state = raw_address.get("state") or raw_address.get("region")
        country = raw_address.get("country")
        return city, state, country

    def geocode_address(self, address: str) -> Optional[GeocodedLocation]:
        """Forward-geocode a text address to a structured location dict.

        Rate-limited (<=1 req/s) and cached on disk (keyed by normalized
        address, including negative results) so repeated/batch lookups do not
        re-hit the public Nominatim endpoint. Returns ``None`` when geocoding
        is unavailable or the address can't be resolved.

        Returns: ``{display_name, latitude, longitude, city, state, country}``.
        """
        if not self._forward_geocode or not address:
            return None

        key = " ".join(address.split()).lower()
        cached = self._geocode_cache_get(key)
        if cached is not None:
            return cached or None  # {} is a cached negative result

        result: Optional[GeocodedLocation] = None
        ctx = (
            CostTracker(self.cost_calculator, "nominatim_geocoding")
            if self.cost_calculator
            else nullcontext()
        )
        with ctx:
            try:
                location = self._forward_geocode(address, exactly_one=True, addressdetails=True)
                if location:
                    raw = (location.raw or {}).get("address", {})
                    city, state, country = self._parse_place(raw)
                    display = ", ".join(p for p in (city, state, country) if p)
                    result = {
                        "display_name": display or location.address,
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                        "city": city,
                        "state": state,
                        "country": country,
                    }
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"  Forward-geocoding error: {e}")
                return None  # transient — do not cache a miss
            except Exception as e:
                print(f"  Address lookup error: {e}")
                return None

        self._geocode_cache_put(key, result or {})
        return result

    @staticmethod
    def _geocode_cache_conn() -> Optional[sqlite3.Connection]:
        try:
            GEOCODE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(GEOCODE_CACHE_PATH))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS geocode_cache "
                "(address TEXT PRIMARY KEY, result TEXT NOT NULL)"
            )
            return conn
        except sqlite3.Error:
            return None  # cache is best-effort; never block geocoding

    def _geocode_cache_get(self, key: str) -> Optional[GeocodedLocation]:
        conn = self._geocode_cache_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT result FROM geocode_cache WHERE address = ?", (key,)
            ).fetchone()
            # Safe: _geocode_cache_put is the sole writer of this table.
            return cast(GeocodedLocation, json.loads(row[0])) if row else None
        except sqlite3.Error, ValueError:
            return None
        finally:
            conn.close()

    def _geocode_cache_put(self, key: str, value: Mapping[str, object]) -> None:
        conn = self._geocode_cache_conn()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT OR REPLACE INTO geocode_cache (address, result) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            conn.commit()
        except sqlite3.Error, ValueError:
            pass
        finally:
            conn.close()

    def get_metadata_summary(self, image_path: Path) -> Dict[str, Any]:
        """
        Get a summary of image metadata.

        Returns:
            Dictionary with datetime, GPS coordinates, and location
        """
        summary: Dict[str, Any] = {
            "datetime": None,
            "gps_coordinates": None,
            "location_name": None,
            "year": None,
            "month": None,
            "date_str": None,
            "text_metadata": {},
        }

        exif_data = self.extract_exif_data(image_path)
        text_metadata = self.extract_text_metadata(image_path)
        if text_metadata:
            summary["text_metadata"] = text_metadata

        dt = self._extract_datetime_from_exif(exif_data)
        if dt is None:
            # GIF/PNG carry no EXIF datetime; fall back to a PNG "Creation Time".
            dt = self._parse_creation_time(text_metadata)
        if dt:
            summary["datetime"] = dt
            summary["year"] = dt.year
            summary["month"] = dt.month
            summary["date_str"] = dt.strftime("%Y-%m")

        coords = self.extract_gps_coordinates(image_path, exif_data)
        if coords:
            summary["gps_coordinates"] = coords
            location = self.get_location_name(coords)
            if location:
                summary["location_name"] = location

        return summary
