import os
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app():
    """Application factory — create and configure the Flask app."""
    app = Flask(__name__)
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
    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    # Create DB tables on startup if they don't exist
    with app.app_context():
        db.create_all()

    return app
