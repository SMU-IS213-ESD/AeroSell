"""
Global error handlers.

Ensures all error responses — including unhandled exceptions — are returned
as JSON rather than Flask's default HTML error pages.
"""

from flask import jsonify


def register_error_handlers(app):
    """Attach JSON error handlers to the given Flask app instance."""

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad Request", "message": e.description}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not Found", "message": e.description}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method Not Allowed", "message": e.description}), 405

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({"error": "Unprocessable Entity", "message": e.description}), 422

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred."}), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        """Catch-all for any exception not matched by a more specific handler."""
        app.logger.exception("Unhandled exception: %s", e)
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred."}), 500
