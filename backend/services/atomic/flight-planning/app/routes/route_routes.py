from apiflask import APIBlueprint, Schema
from apiflask.fields import String, Float, Nested
from typing import List

from app.controllers.route_controller import (
    get_route_history_handler,
    list_pickup_points,
    revalidate_route_handler,
    validate_route_handler,
)

routes_bp = APIBlueprint("routes", __name__, url_prefix="/routes")

# Schemas for documentation
class CoordinateIn(Schema):
    lat = Float(required=True)
    lon = Float(required=True)

class ValidateRouteIn(Schema):
    orderId = String(required=True)
    pickup = Nested(CoordinateIn, required=True)
    dropoff = Nested(CoordinateIn, required=True)

class RevalidateRouteIn(Schema):
    orderId = String(required=True)

class PickupPointOut(Schema):
    id = String()
    name = String()
    lat = Float()
    lon = Float()

class RouteValidationOut(Schema):
    order_id = String()
    is_valid = String()
    message = String()

# Route decorators with APIFlask documentation
@routes_bp.post("/validate")
@routes_bp.doc(tags=["Routes"], summary="Validate a delivery route")
@routes_bp.input(ValidateRouteIn)
@routes_bp.output(RouteValidationOut, status_code=201)
def validate_route():
    return validate_route_handler()

@routes_bp.post("/revalidate")
@routes_bp.doc(tags=["Routes"], summary="Revalidate an existing route")
@routes_bp.input(RevalidateRouteIn)
@routes_bp.output(RouteValidationOut)
def revalidate_route():
    return revalidate_route_handler()

@routes_bp.get("/<string:order_id>")
@routes_bp.doc(tags=["Routes"], summary="Get route history for an order")
@routes_bp.output(RouteValidationOut)
def get_route_history(order_id):
    return get_route_history_handler(order_id)

@routes_bp.get("/pickup-points")
@routes_bp.doc(tags=["Routes"], summary="List all pickup/dropoff points")
@routes_bp.output(List[PickupPointOut])
def list_points():
    return list_pickup_points()
