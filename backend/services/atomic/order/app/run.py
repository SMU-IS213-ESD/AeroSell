from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, DateTime, List, Float
from flask import request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
import pika
import json
import threading
from typing import List as ListType

# Schemas for API documentation
class OrderOut(Schema):
	order_id = Integer()
	user_id = String()
	pickup_location = String()
	dropoff_location = String()
	estimated_pickup_time = DateTime()
	estimated_arrival_time = DateTime()
	final_arrival_time = DateTime()
	status = String()
	drone_id = Integer()
	pickup_pin = String()
	insurance_id = String()
	created = DateTime()
	modified = DateTime()

app = APIFlask(
	__name__,
	title="Order Service",
	version="1.0.0"
)

# --------------------------
# Database Configuration
# --------------------------
db_url = os.environ.get("DATABASE_URL", "mysql+mysqlconnector://root@localhost:3306/esd_proj_orders")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --------------------------
# Order Model
# --------------------------
class Order(db.Model):
    __tablename__ = "order"

    order_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    pickup_location = db.Column(db.String(255))
    dropoff_location = db.Column(db.String(255))
    estimated_pickup_time = db.Column(db.DateTime, nullable=True)
    estimated_arrival_time = db.Column(db.DateTime, nullable=True)
    final_arrival_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default="CREATED")
    drone_id = db.Column(db.Integer, nullable=False)
    pickup_pin = db.Column(db.String(8))  # 8-digit pickup PIN
    insurance_id = db.Column(db.String(255), nullable=True)  # Insurance ID from insurance service
    created = db.Column(db.DateTime, nullable=False, default=datetime.now)
    modified = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def json(self):
        dto = {
            'order_id': self.order_id,
            'user_id': self.user_id,
            'pickup_location': self.pickup_location,
            'dropoff_location': self.dropoff_location,
            'estimated_pickup_time': self.estimated_pickup_time.isoformat() if self.estimated_pickup_time else None,
            'estimated_arrival_time': self.estimated_arrival_time.isoformat() if self.estimated_arrival_time else None,
            'final_arrival_time': self.final_arrival_time.isoformat() if self.final_arrival_time else None,
            'status': self.status,
            'drone_id': self.drone_id,
            'pickup_pin': self.pickup_pin,
            'insurance_id': self.insurance_id,
            'created': self.created,
            'modified': self.modified
        }
        return dto

with app.app_context():
    db.create_all()

# --------------------------
# RabbitMQ Config
# --------------------------
rabbitmq_url = os.environ.get("RABBITMQ_URL")
if not rabbitmq_url:
    raise RuntimeError("RABBITMQ_URL environment variable is not set")
EXCHANGE_NAME = "drone_events"

def publish_status_event(order_id, status):
    """Publish order status updates to RabbitMQ"""
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="fanout")
    message = {"order_id": order_id, "status": status}
    channel.basic_publish(exchange=EXCHANGE_NAME, routing_key="", body=json.dumps(message))
    connection.close()

def start_consumer():
    """Consume anomaly events from RabbitMQ"""
    def callback(ch, method, properties, body):
        data = json.loads(body)
        order_id = data.get("order_id")
        anomaly = data.get("anomaly")
        mapping = {
            "DRONE_STUCK": "DELAYED",
            "DRONE_OFF_COURSE": "DELAYED",
            "DRONE_CRASH": "FAILED"
        }
        new_status = mapping.get(anomaly)
        if not new_status:
            return
        with app.app_context():
            order = Order.query.get(order_id)
            if order:
                order.status = new_status
                db.session.commit()
                print(f"[Order Updated via Event] {order_id} -> {new_status}")

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="fanout")
    result = channel.queue_declare(queue="", exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=EXCHANGE_NAME, queue=queue_name)
    channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
    print("Order Service listening for anomaly events...")
    channel.start_consuming()

# --------------------------
# API Endpoints
# --------------------------

@app.get("/db-check")
@app.doc(tags=["Health Check"], summary="Database connectivity check")
def db_check():
	"""Verify database is reachable"""
	try:
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		if not ok:
			abort(500, "Database unreachable")
		return {"status": "ok"}, 200
	except Exception:
		app.logger.exception("Database connectivity check failed")
		abort(500, "Database error")

@app.get("/orders")
@app.doc(tags=["Orders"], summary="List all orders")
def get_all():
	# Support optional status filter: /orders?status=CREATED
	status = request.args.get('status')
	if status:
		orders = db.session.scalars(db.select(Order).filter_by(status=status)).all()
		return {
			"code": 200,
			"data": {"orders": [order.json() for order in orders]}
		}, 200

	orderlist = db.session.scalars(db.select(Order)).all()
	if len(orderlist):
		return {
			"code": 200,
			"data": {
				"orders": [order.json() for order in orderlist]
			}
		}, 200

	return {
		"code": 404,
		"message": "There are no orders."
	}, 404

@app.route("/order", methods=["POST"])
def create_order():
	data = request.json
	app.logger.info(f"Received order creation request: {data}")
	import random
	pickup_pin = str(random.randint(10000000, 99999999))
	# Parse estimated_pickup_time if provided
	est_pickup = data.get("estimated_pickup_time")
	est_pickup_dt = None
	if est_pickup:
		try:
			est_pickup_dt = datetime.fromisoformat(est_pickup.replace('Z', '+00:00'))
		except Exception:
			est_pickup_dt = None
	est_arrival = data.get("estimated_arrival_time")
	est_arrival_dt = None
	if est_arrival:
		try:
			est_arrival_dt = datetime.fromisoformat(est_arrival.replace('Z', '+00:00'))
		except Exception:
			est_arrival_dt = None
	# Parse final_arrival_time if provided
	final_arrival = data.get("final_arrival_time")
	final_arrival_dt = None
	if final_arrival:
		try:
			final_arrival_dt = datetime.fromisoformat(final_arrival.replace('Z', '+00:00'))
		except Exception:
			final_arrival_dt = None

	order = Order(
		user_id=data.get("user_id"),
		pickup_location=data.get("pickup_location"),
		dropoff_location=data.get("dropoff_location"),
		estimated_pickup_time=est_pickup_dt,
		estimated_arrival_time=est_arrival_dt,
		final_arrival_time=final_arrival_dt,
		drone_id=data.get("drone_id") or 0,
		pickup_pin=pickup_pin,
		insurance_id=data.get("insurance_id"),
		status="CREATED"
	)

	try:
		db.session.add(order)
		db.session.commit()
	except Exception as e:
		print(f"Error: {str(e)}")
		abort(500, f"Error occurred while creating the order. {str(e)}")
	
	return order

@app.get("/orders/<int:order_id>")
@app.doc(tags=["Orders"], summary="Get order by ID")
@app.output(OrderOut)
def get_order(order_id):
	order = db.session.scalar(db.select(Order).filter_by(order_id=order_id))
	if not order:
		abort(404, "Order not found")
	return order

@app.get("/orders/user/<string:user_id>")
@app.doc(tags=["Orders"], summary="Get all orders for a user")
@app.output(ListType[OrderOut])
def get_orders_by_user(user_id):
	"""Get all orders for a specific user"""
	orders = db.session.scalars(
		db.select(Order).filter_by(user_id=user_id)
	).all()

	if not orders:
		abort(404, "No orders found for this user")

	return orders

@app.get("/orders/drone/<int:drone_id>")
@app.doc(tags=["Orders"], summary="Get orders for a drone")
@app.output(ListType[OrderOut])
def get_orders_by_drone(drone_id):
	"""Get orders for a specific drone, optionally filtered by status"""
	status = request.args.get('status')
	print(f"[Order Service] GET /orders/drone/{drone_id} - Status filter: {status}", flush=True)
	
	query = db.select(Order).filter_by(drone_id=drone_id)
	if status:
		query = query.filter_by(status=status)
	
	orders = db.session.scalars(query).all()
	print(f"[Order Service] Found {len(orders)} orders for drone {drone_id}", flush=True)
	
	if not orders:
		print(f"[Order Service] No orders found for drone {drone_id}", flush=True)
		abort(404, f"No orders found for drone {drone_id}")
	
	for order in orders:
		print(f"[Order Service]   - Order {order.order_id}: user={order.user_id}, status={order.status}", flush=True)
	
	return orders

@app.route("/orders/<int:order_id>/status", methods=["PUT", "PATCH"])
@app.doc(tags=["Orders"], summary="Update order status")
def update_status(order_id):
	order = Order.query.get(order_id)
	if not order:
		print(f"[Order Service] PATCH /orders/{order_id}/status - Order NOT found", flush=True)
		abort(404, "Order not found")
	data = request.json
	old_status = order.status
	order.status = data["status"]
	if "drone_id" in data:
		order.drone_id = data["drone_id"]
	db.session.commit()
	print(f"[Order Service] PATCH /orders/{order_id}/status - Updated: {old_status} → {order.status}", flush=True)
	# Publish event
	# publish_status_event(order.id, order.status)
	return {"message": "Order updated"}, 200

@app.get("/orders/by-timeslot")
@app.doc(tags=["Orders"], summary="Get orders by timeslot")
@app.output(ListType[OrderOut])
def get_orders_by_timeslot():
	"""Get orders filtered by timeslot parameter"""
	timeslot = request.args.get('timeslot')

	if not timeslot:
		abort(400, "timeslot parameter is required")

	try:
		# Parse the datetime to extract date string
		# Fix URL-decoded timeslot: replace ' 00:00' with '+00:00' and handle both 'T' and space separators
		timeslot_clean = timeslot.replace(' 00:00', '+00:00')

		if 'T' in timeslot_clean:
			timeslot_clean = timeslot_clean.replace('Z', '+00:00')

		timeslot_dt = datetime.fromisoformat(timeslot_clean)
		# Build date range for the day of timeslot
		start_dt = datetime(timeslot_dt.year, timeslot_dt.month, timeslot_dt.day)
		end_dt = datetime(timeslot_dt.year, timeslot_dt.month, timeslot_dt.day, 23, 59, 59)

		orderlist = db.session.scalars(
			db.select(Order).filter(Order.estimated_pickup_time >= start_dt).filter(Order.estimated_pickup_time <= end_dt)
		).all()

		# Return array directly to match book-drone expectations
		return orderlist

	except Exception as e:
		# Log and return generic error for debugging
		app.logger.error(f"Error filtering orders by timeslot: {str(e)}")
		abort(400, f"Error processing request: {str(e)}")

# --------------------------
# Run App
# --------------------------
if __name__ == "__main__":
    # Start RabbitMQ consumer in background thread
    threading.Thread(target=start_consumer, daemon=True).start()
    app.run(host="0.0.0.0", port=8006, debug=True)