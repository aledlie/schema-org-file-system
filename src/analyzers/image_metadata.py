"""
Image metadata parsing: EXIF, GPS coordinates, timestamps, and reverse geocoding.
"""

from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# PIL / piexif / geopy are optional
try:
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS
    import piexif  # noqa: F401 — imported to confirm availability
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderServiceError, GeocoderTimedOut

    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    METADATA_AVAILABLE = True
except ImportError:
    METADATA_AVAILABLE = False

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

        def __exit__(self, *args: Any) -> bool:
            return False


class ImageMetadataParser:
    """Parses image metadata including EXIF, GPS, and timestamps."""

    def __init__(self, cost_calculator: Any = None) -> None:
        """
        Initialize the metadata parser.

        Args:
            cost_calculator: Optional cost calculator for tracking usage costs
        """
        self.metadata_available = METADATA_AVAILABLE
        self.geocoder = None
        self.cost_calculator = cost_calculator

        if self.metadata_available:
            try:
                self.geocoder = Nominatim(user_agent="file_organizer_v1.0", timeout=5)
            except Exception as e:
                print(f"Warning: Could not initialize geocoder: {e}")
                self.geocoder = None

    def extract_exif_data(self, image_path: Path) -> Dict[str, Any]:
        """
        Extract EXIF data from an image.

        Returns:
            Dictionary with EXIF data
        """
        if not self.metadata_available:
            return {}

        try:
            image = Image.open(image_path)
            exif_data: Dict[str, Any] = {}

            exif = image._getexif()  # type: ignore[attr-defined]
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    exif_data[tag] = value

            return exif_data

        except Exception as e:
            print(f"  EXIF extraction error: {e}")
            return {}

    def extract_datetime(self, image_path: Path) -> Optional[datetime]:
        """
        Extract the datetime when the photo was taken.

        Returns:
            datetime object or None
        """
        return self._extract_datetime_from_exif(self.extract_exif_data(image_path))

    def _extract_datetime_from_exif(self, exif_data: Dict[str, Any]) -> Optional[datetime]:
        for tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            if tag in exif_data:
                try:
                    return datetime.strptime(str(exif_data[tag]), "%Y:%m:%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue
        return None

    def extract_gps_coordinates(self, image_path: Path) -> Optional[Tuple[float, float]]:
        """
        Extract GPS coordinates from image EXIF data.

        Returns:
            Tuple of (latitude, longitude) or None
        """
        if not self.metadata_available:
            return None
        return self._extract_gps_from_exif(self.extract_exif_data(image_path))

    def _extract_gps_from_exif(self, exif_data: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        try:
            raw_gps = exif_data.get("GPSInfo")
            if not raw_gps:
                return None

            gps_info: Dict[str, Any] = {
                GPSTAGS.get(tag_id, tag_id): value
                for tag_id, value in raw_gps.items()
            }

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

    def _convert_to_degrees(self, value: Any) -> Optional[float]:
        """
        Convert GPS coordinates to decimal degrees.

        Args:
            value: GPS coordinate in format ((deg, 1), (min, 1), (sec, 1))

        Returns:
            Decimal degrees or None
        """
        if not value:
            return None

        try:
            d = float(value[0][0]) / float(value[0][1])
            m = float(value[1][0]) / float(value[1][1])
            s = float(value[2][0]) / float(value[2][1])
            return d + (m / 60.0) + (s / 3600.0)
        except (IndexError, TypeError, ZeroDivisionError):
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

        ctx = CostTracker(self.cost_calculator, "nominatim_geocoding") if self.cost_calculator else nullcontext()
        with ctx:
            try:
                lat, lon = coordinates
                location = self.geocoder.reverse(f"{lat}, {lon}", exactly_one=True)

                if location and location.raw.get("address"):
                    address = location.raw["address"]
                    parts = []

                    city = address.get("city") or address.get("town") or address.get("village")
                    if city:
                        parts.append(city)

                    state = address.get("state") or address.get("region")
                    if state:
                        parts.append(state)

                    country = address.get("country")
                    if country:
                        parts.append(country)

                    if parts:
                        return ", ".join(parts)

            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"  Geocoding error: {e}")
            except Exception as e:
                print(f"  Location lookup error: {e}")

            return None

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
        }

        exif_data = self.extract_exif_data(image_path)

        dt = self._extract_datetime_from_exif(exif_data)
        if dt:
            summary["datetime"] = dt
            summary["year"] = dt.year
            summary["month"] = dt.month
            summary["date_str"] = dt.strftime("%Y-%m")

        coords = self._extract_gps_from_exif(exif_data)
        if coords:
            summary["gps_coordinates"] = coords
            location = self.get_location_name(coords)
            if location:
                summary["location_name"] = location

        return summary
