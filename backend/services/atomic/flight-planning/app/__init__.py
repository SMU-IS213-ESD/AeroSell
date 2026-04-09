import os
from apiflask import APIFlask, abort
from flask import jsonify
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app():
    """Application factory — create and configure the APIFlask app."""
    app = APIFlask(
        __name__,
        title="Flight Planning Service",
        version="1.0.0"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # Register route blueprints
    from app.routes.route_routes import routes_bp
    app.register_blueprint(routes_bp)

    # Register global error handlers
    from app.middleware.error_handler import register_error_handlers
    register_error_handlers(app)

    # Health check — lightweight endpoint for liveness probes
    @app.get("/health")
    @app.doc(tags=["Health"], summary="Service health check")
    def health():
        return {"status": "ok"}, 200

    # Create DB tables on startup if they don't exist
    with app.app_context():
        db.create_all()

        # Seed default pickup points if they don't exist
        from app.models.pickup_point import PickupPoint

        # Check if we already have pickup points
        if PickupPoint.query.count() == 0:
            # Add default pickup points for Singapore locations
            default_points = [
                {
                    "name": "SMU (Singapore Management University)",
                    "latitude": 1.2966,
                    "longitude": 103.8523
                },
                {
                    "name": "Bugis Junction",
                    "latitude": 1.2994,
                    "longitude": 103.8562
                },
                {
                    "name": "Plaza Singapura",
                    "latitude": 1.3006,
                    "longitude": 103.8473
                }
            ]

            for point_data in default_points:
                point = PickupPoint(**point_data)
                db.session.add(point)

            db.session.commit()
            print(f"✅ Seeded {len(default_points)} pickup points")

    return app
