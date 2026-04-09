from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, Float, DateTime, Nested, List
from flask import request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
from decimal import Decimal
import stripe
import json
import requests
from typing import List as ListType

# Schemas for API documentation
class PaymentOut(Schema):
	id = Integer()
	order_id = Integer()
	pickup_pin = String()
	amount = Float()
	currency = String()
	method = String()
	status = String()
	transaction_id = String()
	created_at = DateTime()
	updated_at = DateTime()

class PaymentIntentOut(Schema):
	client_secret = String()
	payment_id = Integer()
	transaction_id = String()

app = APIFlask(
	__name__,
	title="Payment Service",
	version="1.0.0"
)

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
            "order_data": self.order_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@app.get("/db-check")
@app.doc(tags=["Health Check"], summary="Database connectivity check")
def db_check():
	"""Verify database is reachable"""
	try:
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		if not ok:
			abort(500, "Database unreachable")
		return {"status": "ok"}
	except Exception:
		app.logger.exception("Database connectivity check failed")
		abort(500, "Database error")


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

@app.post("/")
@app.doc(tags=["Payments"], summary="Create payment intent")
@app.output(PaymentIntentOut, status_code=201)
def create_payment():
	"""Create and process a payment.

	Expected JSON: { "amount": number, "currency": str, "method": str, "order_data": object }
	"""
	data = None
	try:
		data = request.get_json(force=True)
	except Exception:
		abort(400, "invalid JSON")

	if not data:
		abort(400, "missing JSON body")

	amount = data.get("amount")
	currency = data.get("currency", "USD")
	method = data.get("method")
	order_data = data.get("order_data")

	if amount is None:
		abort(400, "amount is required")

	try:
		amt = Decimal(str(amount))
	except Exception:
		abort(400, "invalid amount")

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
				abort(502, "payment provider error")

			payment.transaction_id = pi.id
			payment.status = pi.status
			db.session.commit()

			return {
				"client_secret": getattr(pi, "client_secret", None),
				"payment_id": payment.id,
				"transaction_id": payment.transaction_id
			}
		else:
			db.session.rollback()
			abort(502, "Stripe error")
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed creating payment")
		abort(500, "internal error")


@app.get("/<int:payment_id>")
@app.doc(tags=["Payments"], summary="Get payment by ID")
@app.output(PaymentOut)
def get_payment(payment_id: int):
	p = Payment.query.get(payment_id)
	if not p:
		abort(404, "not found")
	return p


@app.get("/")
@app.doc(tags=["Payments"], summary="List payments")
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
			abort(400, "invalid order_id")
	if transaction_id:
		query = query.filter_by(transaction_id=transaction_id)

	pagination = query.order_by(Payment.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
	items = [p.to_dict() for p in pagination.items]
	return {"payments": items, "page": page, "per_page": per_page, "total": pagination.total}




@app.put("/<int:payment_id>/status")
@app.doc(tags=["Payments"], summary="Update payment status")
def update_payment_status(payment_id: int):
	p = Payment.query.get(payment_id)
	if not p:
		abort(404, "not found")
	data = request.get_json(force=True, silent=True) or {}
	status = data.get("status")
	if not status:
		abort(400, "status is required")
	p.status = status
	try:
		db.session.commit()
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed updating payment status")
		abort(500, "internal error")
	return {"success": True}

@app.put("/<int:payment_id>")
@app.doc(tags=["Payments"], summary="Update payment")
@app.output(PaymentOut)
def update_payment(payment_id: int):
	p = Payment.query.get(payment_id)
	if not p:
		abort(404, "not found")

	data = request.get_json(force=True, silent=True) or {}

	# Only allow updating specific fields used by the composite service
	order_id = data.get("order_id")
	pickup_pin = data.get("pickup_pin")

	if order_id is None and pickup_pin is None:
		abort(400, "nothing to update")

	if order_id is not None:
		try:
			p.order_id = int(order_id)
		except Exception:
			abort(400, "invalid order_id")

	if pickup_pin is not None:
		p.pickup_pin = str(pickup_pin)

	try:
		db.session.commit()
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed updating payment record")
		abort(500, "internal error")

	return p

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8007)
