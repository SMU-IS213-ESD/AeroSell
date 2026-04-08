from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
import pika
import json
import threading

app = Flask(__name__)

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
    item_description = db.Column(db.String(255))
    status = db.Column(db.String(50), default="CREATED")
    drone_id = db.Column(db.Integer, nullable=False)
    pickup_pin = db.Column(db.String(8))  # 8-digit pickup PIN
    created = db.Column(db.DateTime, nullable=False, default=datetime.now)
    modified = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def json(self):
        dto = {
            'order_id': self.order_id,
            'user_id': self.user_id,
            'pickup_location': self.pickup_location,
            'dropoff_location': self.dropoff_location,
            'item_description': self.item_description,
            'status': self.status,
            'drone_id': self.drone_id,
            'pickup_pin': self.pickup_pin,
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

@app.route("/orders")
def get_all():
    orderlist = db.session.scalars(db.select(Order)).all()
    if len(orderlist):
        return jsonify(
            {
                "code": 200,
                "data": {
                    "orders": [order.json() for order in orderlist]
                }
            }
        )
    
    return jsonify(
        {
            "code": 404,
            "message": "There are no orders."
        }
    ), 404

@app.route("/order", methods=["POST"])
def create_order():
    data = request.json
    import random
    pickup_pin = str(random.randint(10000000, 99999999))
    order = Order(
        user_id=data.get("user_id"),
        pickup_location=data.get("pickup_location"),
        dropoff_location=data.get("dropoff_location"),
        item_description=data.get("item_description"),
        drone_id=data.get("drone_id"),
        pickup_pin=pickup_pin,
        status="CREATED"
    )

    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify(
            {
                "code": 500,
                "message": f"Error occurred while creating the order. {str(e)}"
            }
        ), 500
    
    return jsonify(
        {
            "code": 201,
            "order_id": order.json()
        }
    ), 201

@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    # order = Order.query.get(order_id)
    order = db.session.scalar(db.select(Order).filter_by(order_id=order_id))
    if not order:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({
        "order_id": order.order_id,
        "user_id": order.user_id,
        "pickup_location": order.pickup_location,
        "dropoff_location": order.dropoff_location,
        "item_description": order.item_description,
        "status": order.status,
        "drone_id": order.drone_id,
        "created": order.created,
        "modified": order.modified
    })

@app.route("/orders/user/<string:user_id>", methods=["GET"])
def get_orders_by_user(user_id):
    """Get all orders for a specific user"""
    orders = db.session.scalars(
        db.select(Order).filter_by(user_id=user_id)
    ).all()

    if not orders:
        return jsonify({
            "code": 404,
            "message": "No orders found for this user"
        }), 404

    return jsonify({
        "code": 200,
        "data": {
            "orders": [order.json() for order in orders]
        }
    }), 200

@app.route("/orders/drone/<int:drone_id>", methods=["GET"])
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
        return jsonify({
            "code": 404,
            "message": f"No orders found for drone {drone_id}"
        }), 404
    
    for order in orders:
        print(f"[Order Service]   - Order {order.order_id}: user={order.user_id}, status={order.status}", flush=True)
    
    return jsonify({
        "code": 200,
        "data": {
            "orders": [order.json() for order in orders]
        }
    })

@app.route("/orders/<int:order_id>/status", methods=["PUT", "PATCH"])
def update_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        print(f"[Order Service] PATCH /orders/{order_id}/status - Order NOT found", flush=True)
        return jsonify({"error": "Order not found"}), 404
    data = request.json
    old_status = order.status
    order.status = data["status"]
    if "drone_id" in data:
        order.drone_id = data["drone_id"]
    db.session.commit()
    print(f"[Order Service] PATCH /orders/{order_id}/status - Updated: {old_status} → {order.status}", flush=True)
    # Publish event
    publish_status_event(order.id, order.status)
    return jsonify({"message": "Order updated"})

@app.route("/orders/by-timeslot")
def get_orders_by_timeslot():
    """Get orders filtered by timeslot parameter"""
    timeslot = request.args.get('timeslot')

    if not timeslot:
        return jsonify({"error": "timeslot parameter is required"}), 400

    try:
        # Parse the datetime to extract date string
        # Fix URL-decoded timeslot: replace ' 00:00' with '+00:00' and handle both 'T' and space separators
        timeslot_clean = timeslot.replace(' 00:00', '+00:00')

        if 'T' in timeslot_clean:
            timeslot_clean = timeslot_clean.replace('Z', '+00:00')

        timeslot_dt = datetime.fromisoformat(timeslot_clean)
        date_str = timeslot_dt.strftime('%Y-%m-%d')

        # Filter orders where item_description contains the date
        orderlist = db.session.scalars(
            db.select(Order).filter(Order.item_description.ilike(f'%{date_str}%'))
        ).all()

        # Return array directly to match book-drone expectations
        return jsonify([order.json() for order in orderlist]), 200

    except Exception as e:
        # Log and return generic error for debugging
        app.logger.error(f"Error filtering orders by timeslot: {str(e)}")
        return jsonify({"error": f"Error processing request: {str(e)}"}), 400

# --------------------------
# Run App
# --------------------------
if __name__ == "__main__":
    # Start RabbitMQ consumer in background thread
    threading.Thread(target=start_consumer, daemon=True).start()
    app.run(host="0.0.0.0", port=8006, debug=True)