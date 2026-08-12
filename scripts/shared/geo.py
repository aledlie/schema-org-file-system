"""Distance helpers for GPS-based travel classification.

Single-homed so MediaHeuristicSignal and ClipVisionSignal answer "is this
photo away from home?" the same way. Coordinates only — no reverse geocoding,
because this runs inside the classification hot path and inside the backtest
replay, where a network call to Nominatim would be both slow and non-repeatable
(see CLAUDE.md on the replay's EXIF provider).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from shared.constants import HOME_LOCATION_COORDINATES, TRAVEL_MIN_DISTANCE_KM

# Mean Earth radius (km). Haversine on a sphere is far more precision than a
# 100 km threshold needs; the ellipsoid correction is well under 1%.
_EARTH_RADIUS_KM = 6371.0088


def haversine_km(first: Sequence[float], second: Sequence[float]) -> float:
    """Great-circle distance in kilometres between two (lat, lon) pairs."""
    lat1, lon1 = float(first[0]), float(first[1])
    lat2, lon2 = float(second[0]), float(second[1])
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _as_coordinate_pair(coordinates: object) -> Optional[Sequence[float]]:
    """Narrow an untyped metadata value to a usable (lat, lon) pair."""
    if not isinstance(coordinates, (tuple, list)) or len(coordinates) < 2:
        return None
    try:
        return (float(coordinates[0]), float(coordinates[1]))
    except TypeError, ValueError:
        return None


def is_away_from_home(
    coordinates: object,
    *,
    home: Sequence[float] = HOME_LOCATION_COORDINATES,
    radius_km: float = TRAVEL_MIN_DISTANCE_KM,
) -> bool:
    """True when *coordinates* sit beyond ``radius_km`` of home.

    Returns False for missing or malformed coordinates: absent evidence is not
    evidence of travel, and the caller's fallback (leave it in the generic
    photo bucket) is the safe direction to be wrong in.
    """
    pair = _as_coordinate_pair(coordinates)
    if pair is None:
        return False
    return haversine_km(pair, home) > radius_km
