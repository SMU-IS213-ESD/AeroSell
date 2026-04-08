from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
from decimal import Decimal
import stripe
from flask import request, abort
import json
import requests

app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

_created_tables = False


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="USD")
    method = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending")
    transaction_id = db.Column(db.String(128), nullable=True, unique=True)
    # Order data stored as JSON for order creation after payment succeeds
    order_data = db.Column(db.Text, nullable=True)
    pickup_pin = db.Column(db.String(8), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "pickup_pin": self.pickup_pin,
            "amount": float(self.amount),
            "currency": self.currency,
            "method": self.method,
            "status": self.status,
            "transaction_id": self.transaction_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@app.route("/db-check", methods=["GET"])
def db_check():
    """Return JSON true if a simple DB query succeeds, otherwise false."""
    try:
        result = db.session.execute(text("SELECT 1")).scalar()
        ok = bool(result)
        return jsonify(ok), (200 if ok else 500)
    except Exception:
        app.logger.exception("Database connectivity check failed")
        return jsonify(False), 500


# configure stripe if available
stripe.api_key = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
ORDER_SERVICE_URL = "http://kong:8000/order"

@app.before_request
def ensure_tables():
    global _created_tables
    if _created_tables:
        return
    try:
        db.create_all()
        _created_tables = True
    except Exception:
        app.logger.exception("Failed creating database tables")

@app.route("/", methods=["POST"])
def create_payment():
    """Create and process a payment.

    Expected JSON: { "amount": number, "currency": str, "method": str, "order_data": object }
    """
    data = None
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    amount = data.get("amount")
    currency = data.get("currency", "USD")
    method = data.get("method")
    order_data = data.get("order_data")

    if amount is None:
        return jsonify({"error": "amount is required"}), 400

    try:
        amt = Decimal(str(amount))
    except Exception:
        return jsonify({"error": "invalid amount"}), 400

    payment = Payment(
        amount=amt,
        currency=currency,
        method=method,
        status="pending",
        order_data=json.dumps(order_data) if order_data else None
    )

    try:
        if stripe.api_key:
            db.session.add(payment)
            db.session.flush()

            import time
            idempotency_key = f"payment-{payment.id}-{int(time.time())}"
            try:
                pi = stripe.PaymentIntent.create(
                    amount=int(amt * 100),
                    currency=currency.lower(),
                    metadata={"payment_id": str(payment.id)},
                    description=f"Payment {payment.id}",
                    payment_method_types=["card"],
                    idempotency_key=idempotency_key,
                )
            except Exception:
                app.logger.exception("Stripe PaymentIntent creation failed")
                db.session.rollback()
                return jsonify({"error": "payment provider error"}), 502

            payment.transaction_id = pi.id
            payment.status = pi.status
            db.session.commit()

            return jsonify({
                "client_secret": getattr(pi, "client_secret", None),
                "payment_id": payment.id,
                "transaction_id": payment.transaction_id
            }), 201
        else:
            db.session.rollback()
            return jsonify({"error": "Stripe error"}), 502
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed creating payment")
        return jsonify({"error": "internal error"}), 500


@app.route("/<int:payment_id>", methods=["GET"])
def get_payment(payment_id: int):
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({"error": "not found"}), 404
    return jsonify(p.to_dict()), 200


@app.route("/", methods=["GET"])
def list_payments():
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 50))
    except Exception:
        per_page = 50
    order_id = request.args.get("order_id")
    transaction_id = request.args.get("transaction_id")
    query = Payment.query
    if order_id:
        try:
            query = query.filter_by(order_id=int(order_id))
        except Exception:
            return jsonify({"error": "invalid order_id"}), 400
    if transaction_id:
        query = query.filter_by(transaction_id=transaction_id)

    pagination = query.order_by(Payment.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    items = [p.to_dict() for p in pagination.items]
    return jsonify({"payments": items, "page": page, "per_page": per_page, "total": pagination.total}), 200


def create_order_from_payment(payment):
    """Create an order in the order service after payment succeeds"""
    if not payment.order_data:
        # Order data is optional - log but don't fail
        app.logger.warning(f"No order data for payment {payment.id}, skipping order creation")
        return None

    try:
        order_data = json.loads(payment.order_data)
        # Prepare order data for order service
        order_payload = {
            "user_id": order_data.get("user_id"),
            "pickup_location": order_data.get("pickup_location"),
            "dropoff_location": order_data.get("dropoff_location"),
            "item_description": order_data.get("item_description"),
            "drone_id": order_data.get("drone_id"),
            "pickup_pin": order_data.get("pickup_pin")
        }

        response = requests.post(
            f"{ORDER_SERVICE_URL}/order",
            json=order_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 201:
            result = response.json()
            # The order_id field contains the full order object
            order_obj = result.get("order_id")
            if order_obj and isinstance(order_obj, dict):
                order_id = order_obj.get("order_id")
                pickup_pin = order_obj.get("pickup_pin")

                # Update payment with order details
                payment.order_id = order_id
                payment.pickup_pin = pickup_pin
                db.session.commit()

                app.logger.info(f"Order {order_id} created for payment {payment.id}")
                return {"order_id": order_id, "pickup_pin": pickup_pin}
            else:
                app.logger.error(f"Invalid order response format: {result}")
                return None
        else:
            app.logger.error(f"Failed to create order: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        app.logger.exception("Failed to create order from payment")
        return None


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhooks to update payment status."""
    def _get_obj_id(o):
        try:
            return o['id']
        except Exception:
            return getattr(o, 'id', None)

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "webhook secret not configured"}), 500
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return jsonify({"error": "invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "invalid signature"}), 400

    typ = event["type"]
    obj = event["data"]["object"]
    if typ == "payment_intent.succeeded":
        tid = _get_obj_id(obj)
        p = Payment.query.filter_by(transaction_id=tid).first()
        if p:
            p.status = "succeeded"
            try:
                db.session.commit()
                # CREATE ORDER AFTER PAYMENT SUCCEEDS
                order_result = create_order_from_payment(p)
                if order_result:
                    app.logger.info(f"Order created successfully: {order_result}")
                else:
                    app.logger.error("Failed to create order after payment success")
            except Exception:
                db.session.rollback()
                app.logger.exception("Failed updating payment status from webhook")
    elif typ == "payment_intent.payment_failed":
        tid = _get_obj_id(obj)
        p = Payment.query.filter_by(transaction_id=tid).first()
        if p:
            p.status = "failed"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("Failed updating payment status from webhook")

    return jsonify({"received": True}), 200


@app.route("/<int:payment_id>/status", methods=["PUT"])
def update_payment_status(payment_id: int):
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    status = data.get("status")
    if not status:
        return jsonify({"error": "status is required"}), 400
    p.status = status
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed updating payment status")
        return jsonify({"error": "internal error"}), 500
    return jsonify({"success": True}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8007)
