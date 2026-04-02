"""
No-fly zone service.

Zones are represented as lat/lon bounding boxes. The route check samples
SAMPLE_COUNT evenly-spaced points along the straight-line path and tests each
point against every zone. This is intentionally simple — replace with a proper
spatial query (e.g. PostGIS) when zone data grows beyond a handful of entries.
"""

# Hardcoded restricted zones (Singapore-area coordinates for realism).
# Each zone is an axis-aligned bounding box: min/max lat and lon.
NO_FLY_ZONES = [
    {
        "name": "Changi Airport Exclusion Zone",
        "min_lat": 1.3400, "max_lat": 1.3700,
        "min_lon": 103.9600, "max_lon": 104.0100,
    },
    {
        "name": "Paya Lebar Air Base",
        "min_lat": 1.3600, "max_lat": 1.3800,
        "min_lon": 103.9000, "max_lon": 103.9200,
    },
    {
        "name": "Tengah Air Base",
        "min_lat": 1.3700, "max_lat": 1.3900,
        "min_lon": 103.7000, "max_lon": 103.7300,
    },
    {
        "name": "Seletar Airport Zone",
        "min_lat": 1.4100, "max_lat": 1.4300,
        "min_lon": 103.8600, "max_lon": 103.8900,
    },
    {
        "name": "Central Water Catchment Reserve",
        "min_lat": 1.3700, "max_lat": 1.4000,
        "min_lon": 103.7900, "max_lon": 103.8200,
    },
]

# Number of interpolated points to sample along the route segment.
_SAMPLE_COUNT = 20


def _point_in_zone(lat: float, lon: float, zone: dict) -> bool:
    """Return True if (lat, lon) falls inside the bounding box of zone."""
    return (
        zone["min_lat"] <= lat <= zone["max_lat"]
        and zone["min_lon"] <= lon <= zone["max_lon"]
    )


def check_route_for_no_fly_zones(
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
) -> tuple[bool, str | None]:
    """Check whether the straight-line route intersects any no-fly zone.

    Samples _SAMPLE_COUNT + 1 evenly-spaced points (including endpoints) along
    the path and tests each against every bounding box.

    Returns:
        (violated, zone_name) — violated is True and zone_name is set if any
        sampled point falls inside a restricted zone; otherwise (False, None).
    """
    for i in range(_SAMPLE_COUNT + 1):
        t = i / _SAMPLE_COUNT
        lat = pickup_lat + t * (dropoff_lat - pickup_lat)
        lon = pickup_lon + t * (dropoff_lon - pickup_lon)

        for zone in NO_FLY_ZONES:
            if _point_in_zone(lat, lon, zone):
                return True, zone["name"]

    return False, None
