"""
Distance and duration estimation service.

Uses the Haversine formula to compute straight-line great-circle distance
between two WGS-84 coordinates. Duration is derived from an assumed constant
drone cruise speed.
"""

import math

# Assumed average drone cruise speed in km/h.
_DRONE_SPEED_KMH = 60.0

# Earth's mean radius in kilometres.
_EARTH_RADIUS_KM = 6371.0


def haversine_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return the great-circle distance in kilometres between two coordinates.

    Args:
        lat1, lon1: Origin latitude and longitude in decimal degrees.
        lat2, lon2: Destination latitude and longitude in decimal degrees.

    Returns:
        Distance in kilometres, rounded to 4 decimal places.
    """
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = math.sin(d_lat / 2) ** 2 + (
        math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(_EARTH_RADIUS_KM * c, 4)


def estimate_duration_min(distance_km: float) -> float:
    """Return estimated flight time in minutes for a given distance.

    Assumes a constant cruise speed of _DRONE_SPEED_KMH km/h with no
    takeoff/landing overhead.

    Args:
        distance_km: Route distance in kilometres.

    Returns:
        Duration in minutes, rounded to 2 decimal places.
    """
    return round((distance_km / _DRONE_SPEED_KMH) * 60, 2)
