from datetime import timezone
from app import db


class RouteValidation(db.Model):
    """Persisted record of a single route feasibility check."""

    __tablename__ = "route_validations"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(255), nullable=False, index=True)

    # Coordinates
    pickup_lat = db.Column(db.Float, nullable=False)
    pickup_lon = db.Column(db.Float, nullable=False)
    dropoff_lat = db.Column(db.Float, nullable=False)
    dropoff_lon = db.Column(db.Float, nullable=False)

    # Validation result
    feasible = db.Column(db.Boolean, nullable=False)
    reason = db.Column(db.Text, nullable=True)

    # Estimates
    estimated_distance_km = db.Column(db.Float, nullable=False)
    estimated_duration_min = db.Column(db.Float, nullable=False)

    checked_at = db.Column(db.DateTime(timezone=True), nullable=False)

    def to_dict(self):
        """Serialize this record to the standard API response shape."""
        # Normalize to UTC "Z" suffix regardless of stored tz info
        checked_at_iso = self.checked_at.isoformat().replace("+00:00", "Z")
        if not checked_at_iso.endswith("Z"):
            checked_at_iso += "Z"

        return {
            "orderId": self.order_id,
            "feasible": self.feasible,
            "reason": self.reason,
            "estimatedDistanceKm": self.estimated_distance_km,
            "estimatedDurationMin": self.estimated_duration_min,
            "checkedAt": checked_at_iso,
            "pickup": {"lat": self.pickup_lat, "lon": self.pickup_lon},
            "dropoff": {"lat": self.dropoff_lat, "lon": self.dropoff_lon},
        }
