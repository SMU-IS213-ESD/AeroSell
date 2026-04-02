"""
Route validation service — core business logic.

Orchestrates no-fly zone checks, distance/duration estimation, and persistence.
All public functions return RouteValidation ORM instances so callers can
serialize or inspect results uniformly.
"""

from datetime import datetime, timezone

from app import db
from app.models.route_validation import RouteValidation
from app.services.distance_service import estimate_duration_min, haversine_distance_km
from app.services.no_fly_zone_service import check_route_for_no_fly_zones

# Hard ceiling on supported delivery range.
_MAX_RANGE_KM = 50.0


def validate_route(
    order_id: str,
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
) -> RouteValidation:
    """Validate a delivery route and persist the result.

    Checks (in order):
      1. Maximum range constraint — routes over _MAX_RANGE_KM km are rejected.
      2. No-fly zone intersection — the straight-line path is sampled for
         restricted airspace.

    Args:
        order_id:    Caller-supplied order identifier (not validated for uniqueness).
        pickup_lat:  Pickup latitude in decimal degrees.
        pickup_lon:  Pickup longitude in decimal degrees.
        dropoff_lat: Dropoff latitude in decimal degrees.
        dropoff_lon: Dropoff longitude in decimal degrees.

    Returns:
        A committed RouteValidation record.
    """
    distance_km = haversine_distance_km(pickup_lat, pickup_lon, dropoff_lat, dropoff_lon)
    duration_min = estimate_duration_min(distance_km)

    if distance_km > _MAX_RANGE_KM:
        feasible = False
        reason = (
            f"Route distance {distance_km} km exceeds the maximum supported "
            f"range of {_MAX_RANGE_KM} km."
        )
    else:
        violated, zone_name = check_route_for_no_fly_zones(
            pickup_lat, pickup_lon, dropoff_lat, dropoff_lon
        )
        if violated:
            feasible = False
            reason = f"Route passes through restricted no-fly zone: {zone_name}."
        else:
            feasible = True
            reason = None

    record = RouteValidation(
        order_id=order_id,
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        dropoff_lat=dropoff_lat,
        dropoff_lon=dropoff_lon,
        feasible=feasible,
        reason=reason,
        estimated_distance_km=distance_km,
        estimated_duration_min=duration_min,
        checked_at=datetime.now(timezone.utc),
    )

    db.session.add(record)
    db.session.commit()

    return record


def revalidate_route(order_id: str) -> RouteValidation:
    """Re-validate a route using coordinates from the most recent prior check.

    Looks up the latest RouteValidation record for order_id and re-runs
    validation with the same pickup/dropoff coordinates, producing a new record.

    Args:
        order_id: The order whose previous validation should be repeated.

    Returns:
        A newly committed RouteValidation record.

    Raises:
        ValueError: If no prior validation exists for order_id.
    """
    prior = (
        RouteValidation.query
        .filter_by(order_id=order_id)
        .order_by(RouteValidation.checked_at.desc())
        .first()
    )

    if prior is None:
        raise ValueError(f"No prior validation found for orderId '{order_id}'.")

    return validate_route(
        order_id,
        prior.pickup_lat,
        prior.pickup_lon,
        prior.dropoff_lat,
        prior.dropoff_lon,
    )


def get_route_history(order_id: str) -> list[RouteValidation]:
    """Return all validation records for an order, newest first.

    Args:
        order_id: The order to look up.

    Returns:
        A list of RouteValidation records (may be empty).
    """
    return (
        RouteValidation.query
        .filter_by(order_id=order_id)
        .order_by(RouteValidation.checked_at.desc())
        .all()
    )
