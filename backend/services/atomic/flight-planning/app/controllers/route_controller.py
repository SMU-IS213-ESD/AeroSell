"""
Route controller — parse/validate HTTP requests, delegate to the service layer,
and format responses. No business logic lives here.
"""

from flask import abort, jsonify, request

from app.services.route_validation_service import (
    get_route_history,
    revalidate_route,
    validate_route,
)


def _parse_coordinate(value, field_name: str) -> float:
    """Coerce value to float; abort 400 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        abort(400, description=f"'{field_name}' must be a numeric value.")


def validate_route_handler():
    """POST /routes/validate — validate a new delivery route.

    Expected JSON body:
        {
            "orderId": "string",
            "pickup":  { "lat": number, "lon": number },
            "dropoff": { "lat": number, "lon": number }
        }

    Returns 201 with the validation result on success.
    """
    body = request.get_json(silent=True)
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
    return jsonify(record.to_dict()), 201


def revalidate_route_handler():
    """POST /routes/revalidate — re-check a previously validated route.

    Expected JSON body:
        { "orderId": "string" }

    Looks up the most recent validation for orderId and repeats it.
    Returns 201 with the new validation result, or 404 if no prior record exists.
    """
    body = request.get_json(silent=True)
    if not body:
        abort(400, description="Request body must be valid JSON.")

    order_id = body.get("orderId")
    if not order_id:
        abort(400, description="'orderId' is required.")

    try:
        record = revalidate_route(order_id)
    except ValueError as exc:
        abort(404, description=str(exc))

    return jsonify(record.to_dict()), 201


def get_route_history_handler(order_id: str):
    """GET /routes/<order_id> — retrieve all validations for an order.

    Returns 200 with an array of validation records (newest first),
    or 404 if none exist for the given orderId.
    """
    records = get_route_history(order_id)
    if not records:
        abort(404, description=f"No route validations found for orderId '{order_id}'.")

    return jsonify([r.to_dict() for r in records]), 200
