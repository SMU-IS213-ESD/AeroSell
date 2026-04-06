from flask import Blueprint

from app.controllers.route_controller import (
    get_route_history_handler,
    list_pickup_points,
    revalidate_route_handler,
    validate_route_handler,
)

routes_bp = Blueprint("routes", __name__, url_prefix="/routes")

routes_bp.add_url_rule("/validate",       view_func=validate_route_handler,     methods=["POST"])
routes_bp.add_url_rule("/revalidate",     view_func=revalidate_route_handler,   methods=["POST"])
routes_bp.add_url_rule("/<string:order_id>", view_func=get_route_history_handler, methods=["GET"])
routes_bp.add_url_rule("/pickup-points", view_func=list_pickup_points, methods=["GET"])
