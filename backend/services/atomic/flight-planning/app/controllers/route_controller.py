"""
Route controller — parse/validate HTTP requests, delegate to the service layer,
and format responses. No business logic lives here.
"""

from flask import abort, request

from app.models.pickup_point import PickupPoint
from app.services.route_validation_service import (
    get_route_history,
    revalidate_route,
    validate_route_by_ids,
    validate_route,
)


def list_pickup_points():
    """GET /routes/pickup-points - Return all available pickup/dropoff locations."""
    points = PickupPoint.query.all()
    return [point.to_dict() for point in points]


def validate_route_by_ids_handler(json_data=None, **kwargs):
    """POST /routes/validate-by-ids — validate using pickup point IDs instead of coordinates."""
    body = json_data if isinstance(json_data, dict) else request.get_json(silent=True)
    if not body:
        abort(400, description="Request body must be valid JSON.")

    order_id = body.get("orderId")
    pickup_point_id = body.get("pickupPointId")
    dropoff_point_id = body.get("dropoffPointId")

    if not order_id:
        abort(400, description="'orderId' is required.")
    if not pickup_point_id:
        abort(400, description="'pickupPointId' is required.")
    if not dropoff_point_id:
        abort(400, description="'dropoffPointId' is required.")

    try:
        pickup_point_id_int = int(pickup_point_id)
        dropoff_point_id_int = int(dropoff_point_id)
    except (TypeError, ValueError):
        abort(400, description="Pickup and dropoff point IDs must be integers.")

    record = validate_route(
        order_id=order_id,
        pickup_lat=None,
        pickup_lon=None,
        dropoff_lat=None,
        dropoff_lon=None,
        pickup_point_id=pickup_point_id_int,
        dropoff_point_id=dropoff_point_id_int
    )
    return record.to_dict()


def _parse_coordinate(value, field_name: str) -> float:
    """Coerce value to float; abort 400 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        abort(400, description=f"'{field_name}' must be a numeric value.")


def validate_route_handler(json_data=None, **kwargs):
    """POST /routes/validate — validate a new delivery route.

    Expected JSON body:
        {
            "orderId": "string",
            "pickup":  { "lat": number, "lon": number },
            "dropoff": { "lat": number, "lon": number }
        }

    Returns 201 with the validation result on success.
    """
    body = json_data if isinstance(json_data, dict) else request.get_json(silent=True)
    if not body:
        abort(400, description="Request body must be valid JSON.")

    order_id = body.get("orderId")
    pickup = body.get("pickup")
    dropoff = body.get("dropoff")

    if not order_id:
        abort(400, description="'orderId' is required.")
    if not isinstance(pickup, dict) or "lat" not in pickup or "lon" not in pickup:
        abort(400, description="'pickup' must be an object with 'lat' and 'lon'.")
    if not isinstance(dropoff, dict) or "lat" not in dropoff or "lon" not in dropoff:
        abort(400, description="'dropoff' must be an object with 'lat' and 'lon'.")

    pickup_lat = _parse_coordinate(pickup["lat"], "pickup.lat")
    pickup_lon = _parse_coordinate(pickup["lon"], "pickup.lon")
    dropoff_lat = _parse_coordinate(dropoff["lat"], "dropoff.lat")
    dropoff_lon = _parse_coordinate(dropoff["lon"], "dropoff.lon")

    record = validate_route(order_id, pickup_lat, pickup_lon, dropoff_lat, dropoff_lon)
    return record.to_dict()


def revalidate_route_handler(json_data=None, **kwargs):
    """POST /routes/revalidate — re-check a previously validated route.

    Expected JSON body:
        { "orderId": "string" }

    Looks up the most recent validation for orderId and repeats it.
    Returns 201 with the new validation result, or 404 if no prior record exists.
    """
    body = json_data if isinstance(json_data, dict) else request.get_json(silent=True)
    if not body:
        abort(400, description="Request body must be valid JSON.")

    order_id = body.get("orderId")
    if not order_id:
        abort(400, description="'orderId' is required.")

    try:
        record = revalidate_route(order_id)
    except ValueError as exc:
        abort(404, description=str(exc))

    return record.to_dict()


def get_route_history_handler(order_id: str):
    """GET /routes/<order_id> — retrieve all validations for an order.

    Returns 200 with an array of validation records (newest first),
    or 404 if none exist for the given orderId.
    """
    records = get_route_history(order_id)
    if not records:
        abort(404, description=f"No route validations found for orderId '{order_id}'.")

    return [r.to_dict() for r in records]
