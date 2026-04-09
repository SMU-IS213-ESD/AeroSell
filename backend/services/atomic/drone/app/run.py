# --- Wait for RabbitMQ to be ready ---
def wait_for_rabbitmq(max_retries=15, delay=2):
	import pika
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	print(f"[Startup] Waiting for RabbitMQ at {rabbitmq_url}")
	for i in range(max_retries):
		try:
			params = pika.URLParameters(rabbitmq_url)
			conn = pika.BlockingConnection(params)
			ch = conn.channel()
			ch.queue_declare(queue='test_amqp_wait', durable=True)
			ch.close()
			conn.close()
			print("[Startup] RabbitMQ is ready!")
			return True
		except Exception as e:
			print(f"[Startup] Waiting for RabbitMQ... ({i+1}/{max_retries}) - {e}")
			time.sleep(delay)
	raise RuntimeError("RabbitMQ not available after retries")
from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, Float
from flask import jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from datetime import datetime
import os
import time
import threading
import json
import requests
app = APIFlask(__name__)
db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)





# RabbitMQ (AMQP) setup

# --- RabbitMQ (AMQP) persistent connection setup ---
import pika

rabbitmq_connection = None
rabbitmq_channel = None

def open_rabbitmq_connection():
	"""Open and store a persistent RabbitMQ connection and channel."""
	global rabbitmq_connection, rabbitmq_channel
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	params = pika.URLParameters(rabbitmq_url)

	try:
		rabbitmq_connection = pika.BlockingConnection(params)
		rabbitmq_channel = rabbitmq_connection.channel()
		print(f"[Drone Service] Persistent connection opened for PUBLISHING ONLY", flush=True)
		print(f"[Drone Service] Connection: {rabbitmq_connection}, Channel: {rabbitmq_channel}", flush=True)
	except Exception as e:
		app.logger.exception("Failed to connect to RabbitMQ")
		print("Failed to connect to RabbitMQ!")
		print("Exception type:", type(e))
		print("Exception:", e)

def close_rabbitmq_connection(e=None):
	"""Close the persistent RabbitMQ connection and channel."""
	global rabbitmq_connection, rabbitmq_channel
	if rabbitmq_channel:
		try:
			rabbitmq_channel.close()
		except Exception:
			pass
		rabbitmq_channel = None
	if rabbitmq_connection:
		try:
			rabbitmq_connection.close()
		except Exception:
			pass
		rabbitmq_connection = None

def publish_message(exchange, routing_key, body, properties=None):
	"""DEPRECATED: Do NOT use this function.
	
	Reason: Global persistent channel causes thread-safety issues.
	Instead, always create a fresh connection per publish operation.
	See handle_drone_anomaly() for the correct pattern.
	"""
	raise NotImplementedError("Use fresh connection pattern instead - see handle_drone_anomaly()")

# sqlalchemy model


# sqlalchemy model
class Drone(db.Model):
	__tablename__ = 'drones'
	id = db.Column(db.Integer, primary_key=True)
	battery_level = db.Column(db.Integer, nullable=False)
	status = db.Column(db.String(50), nullable=False)
	current_longitude = db.Column(db.Float, nullable=False)
	current_latitude = db.Column(db.Float, nullable=False)

	def json(self):
		return {
			'id': self.id,
			'battery_level': self.battery_level,
			'status': self.status,
			'current_longitude': self.current_longitude,
			'current_latitude': self.current_latitude
		}

	# --- Telemetry Model ---
class Telemetry(db.Model):
	__tablename__ = 'telemetry'
	id = db.Column(db.Integer, primary_key=True)
	drone_id = db.Column(db.Integer, db.ForeignKey('drones.id', ondelete="CASCADE"), nullable=False)
	timestamp = db.Column(db.DateTime, server_default=db.func.current_timestamp(), nullable=False)
	error = db.Column(db.Boolean, nullable=True)
	current_longitude = db.Column(db.Float, nullable=True)
	current_latitude = db.Column(db.Float, nullable=True)

	def json(self):
		return {
			'id': self.id,
			'drone_id': self.drone_id,
			'timestamp': self.timestamp.isoformat() if self.timestamp else None,
			'error': self.error,
			'current_longitude': self.current_longitude,
			'current_latitude': self.current_latitude

		}

# --- APIFlask Schema for Drone ---
class DroneOut(Schema):
	id = Integer()
	battery_level = Integer()
	status = String()
	current_longitude = Float()
	current_latitude = Float()

# --- AMQP Consumer Thread ---

def telemetry_callback(ch, method, properties, body):
	try:
		data = json.loads(body)
		print("[Telemetry] Received:", data, flush=True)
		drone_id = data.get("drone_id")
		timestamp_str = data.get("timestamp")
		error = data.get("error")
		current_longitude = data.get("current_longitude")
		current_latitude = data.get("current_latitude")
		
		# Parse timestamp string to datetime object
		try:
			timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None
		except (ValueError, TypeError) as e:
			print(f"[Telemetry] Invalid timestamp format: {timestamp_str}, {e}", flush=True)
			timestamp = None
		
		# Update telemetry table
		with app.app_context():
			drone = Drone.query.get(drone_id)
			
			# Insert telemetry record
			telemetry = Telemetry(
				drone_id=drone_id,
				timestamp=timestamp,
				error=error,
				current_longitude=current_longitude,
				current_latitude=current_latitude
			)
			db.session.add(telemetry)
			db.session.commit()
			
			# Check for anomaly and handle if error detected
			if error:
				handle_drone_anomaly(drone, timestamp, current_longitude, current_latitude)
	except Exception as e:
		app.logger.exception("Failed to process telemetry message")
		print(f"[Telemetry] Exception: {e}", flush=True)


def handle_drone_anomaly(drone, timestamp, current_longitude, current_latitude):
	"""Handle drone anomaly: update status and publish anomaly message.
	
	Uses FRESH connection (not persistent) to avoid thread interference.
	
	Args:
		drone: Drone object (already queried to avoid redundant DB query)
		timestamp: Timestamp from telemetry
		current_longitude: Drone longitude
		current_latitude: Drone latitude
	"""
	try:
		# 1. Update drone status to pending_maintenance
		if drone:
			drone.status = "pending_maintenance"
			db.session.commit()
			print(f"[Anomaly] Drone {drone.id} status updated to pending_maintenance", flush=True)
		
		# 2. Publish drone.anomaly message using FRESH connection (thread-safe)
		anomaly_msg = {
			"drone_id": drone.id,
			"timestamp": timestamp.isoformat() if timestamp else None,
			"current_longitude": current_longitude,
			"current_latitude": current_latitude
		}
		
		# Create fresh connection for publishing (thread-safe, no interference)
		rabbitmq_url = os.environ.get("RABBITMQ_URL")
		connection = None
		channel = None
		try:
			print(f"[Anomaly] Creating FRESH connection to publish anomaly...", flush=True)
			params = pika.URLParameters(rabbitmq_url)
			connection = pika.BlockingConnection(params)
			channel = connection.channel()
			print(f"[Anomaly] Connection created, declaring exchange...", flush=True)
			
			# Declare exchange
			channel.exchange_declare(
				exchange="drone_anomaly",
				exchange_type="topic",
				durable=True
			)
			
			# Publish message
			channel.basic_publish(
				exchange="drone_anomaly",
				routing_key="drone.anomaly",
				body=json.dumps(anomaly_msg),
				properties=pika.BasicProperties(delivery_mode=2, content_type='application/json')
			)
			print(f"[Anomaly] Published drone.anomaly message: {anomaly_msg}", flush=True)
		finally:
			# Always cleanup
			if channel:
				try:
					channel.close()
				except Exception:
					pass
			if connection:
				try:
					connection.close()
				except Exception:
					pass
	except Exception as e:
		app.logger.exception(f"Failed to handle drone anomaly for drone {drone.id if drone else 'unknown'}")
		print(f"[Anomaly] Error handling anomaly: {e}", flush=True)


def flight_update_callback(ch, method, properties, body):
	try:
		data = json.loads(body)
		print("[Flight Update] Received:", data)
		drone_id = data.get("drone_id")
		status = data.get("status")
		with app.app_context():
			#TODO: publish event to let composite svc know that drone has landed,
			# the idea is that it tells the composite svc that its done, it updates the ui,
			#when the customer collect and confirm delivery on the ui, then the composite svc will 
			# 1. update order status tp complete via http
			# 2. update drone status to available also via http
			drone = Drone.query.get(drone_id)
			if drone and status:
				drone.status = status
				db.session.commit()
	except Exception as e:
		app.logger.exception("Failed to process flight_update message")



def amqp_consumer_thread():
	import pika
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	while True:
		connection = None
		channel = None
		try:
			print(f"[Consumer Thread] Creating SEPARATE connection for CONSUMING ONLY (not for publishing)", flush=True)
			params = pika.URLParameters(rabbitmq_url)
			connection = pika.BlockingConnection(params)
			channel = connection.channel()
			print(f"[Consumer Thread] Consumer Connection established: {connection}", flush=True)
			print(f"[Consumer Thread] Consumer Channel established: {channel}", flush=True)
			
			# Declare queues (idempotent)
			channel.queue_declare(queue='telemetry', durable=True)
			channel.queue_declare(queue='flight_update', durable=True)
			print(f"[Consumer Thread] Declared queues: telemetry, flight_update", flush=True)
			
			# Bind queues to exchange
			channel.queue_bind(exchange='drone', queue='telemetry', routing_key='telemetry')
			channel.queue_bind(exchange='drone', queue='flight_update', routing_key='flight_update')
			print(f"[Consumer Thread] Bound queues to 'drone' exchange (NOT 'drone_anomaly')", flush=True)
			
			# Set QoS to process one message at a time from each queue
			channel.basic_qos(prefetch_count=1)
			
			# Set up consumers
			channel.basic_consume(queue='telemetry', on_message_callback=telemetry_callback, auto_ack=True)
			channel.basic_consume(queue='flight_update', on_message_callback=flight_update_callback, auto_ack=True)
			print("[Consumer Thread] Started consuming from 'drone' exchange (telemetry, flight_update only)...", flush=True)
			print("[Consumer Thread] NOTE: Publishing (anomalies) uses SEPARATE fresh connection for thread safety", flush=True)
			channel.start_consuming()
		except Exception as e:
			app.logger.exception("AMQP consumer thread crashed, retrying in 5s...")
			print(f"[Consumer Thread] ERROR: {e}", flush=True)
			time.sleep(5)
		finally:
			if channel:
				try:
					channel.close()
				except Exception:
					pass
			if connection:
				try:
					connection.close()
				except Exception:
					pass

@app.route("/db-check", methods=["GET"])
@app.doc(tags=["Health Check"])
def db_check():
	"""Return JSON true if a simple DB query succeeds, otherwise false.

	Response body is a bare boolean JSON value (true/false) and status
	code is 200 on success, 500 on failure.
	"""
	try:
		# Lightweight check: run a simple SELECT 1
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		return jsonify(ok), (200 if ok else 500)
	except Exception:
		app.logger.exception("Database connectivity check failed")
		return jsonify(False), 500


# GET /drones/<int:drone_id> - get a single drone by ID (APIFlask style)
@app.get("/drones/<int:drone_id>")
@app.doc(tags=["Drones"])
@app.output(DroneOut)
def get_drone(drone_id):
	drone = db.session.get(Drone, drone_id)
	if not drone:
		abort(404, "Drone not found")
	return drone
	

# GET /drones - get all drones
from typing import List
@app.get("/drones")
@app.doc(tags=["Drones"])
@app.output(List[DroneOut])
def get_all_drones():
	try:
		drones = Drone.query.all()
	except Exception as e:
		app.logger.exception("Failed to get all drones")
		abort(500, "Internal server error")
	return drones


# GET /drones/available - get all available drones
@app.get("/drones/available")
@app.doc(tags=["Drones"])
@app.output(List[DroneOut])
def get_available_drones():
	try:
		drones = Drone.query.filter_by(status='available').all()
	except Exception as e:
		app.logger.exception("Failed to get available drones")
		abort(500, "Internal server error")
	return drones

#TODO: update endpoint such that it will call the simulate_drone.py activate endpoint

import requests

@app.post("/drones/activate/<int:drone_id>")
@app.doc(tags=["Drones"])
@app.output(DroneOut)

def activate_drone(drone_id):
	drone = db.session.get(Drone, drone_id)
	app.logger.debug(f"Activating drone {drone_id} with details: {drone.json() if drone else 'Drone not found'}")
	if not drone:
		abort(404, "Drone not found")
		app.logger.error(f"Drone {drone_id} not found for activation")
	# Accept order_info from request body
	order_info = request.get_json(silent=True)
	if not order_info:
		abort(400, "Missing or invalid JSON body for order_info")
	# Optionally, validate required fields here
	sim_url = os.environ.get("SIMULATE_DRONE_URL", "http://drone-sim:8010/dronesim/activate")
	try:
		# POST to the simulate_drone.py service
		sim_response = requests.post(f"{sim_url}/{drone_id}", json=order_info)
		if sim_response.status_code != 200:
			app.logger.error(f"Simulate drone activate failed: {sim_response.text}")
	except Exception as e:
		app.logger.exception(f"Failed to call simulate_drone.py for drone {drone_id}")
	try:
		drone.status = "in-flight"
		db.session.commit()
	except Exception as e:
		app.logger.exception(f"Failed to activate drone {drone_id}")
		abort(500, "Internal server error")
	return drone


@app.post("/drones")
@app.output(DroneOut, status_code=201)
@app.doc(tags=["Drones"])
def create_drone():
	data = request.get_json(silent=True)
	if data is None:
		abort(400, "Invalid or missing JSON in request body")
	required_fields = ["battery_level", "status", "current_longitude", "current_latitude"]
	missing_fields = [field for field in required_fields if field not in data]
	if missing_fields:
		abort(400, f"Missing required fields: {', '.join(missing_fields)}")
	# Basic type validation
	try:
		battery_level = int(data["battery_level"])
		status = str(data["status"])
		current_longitude = float(data["current_longitude"])
		current_latitude = float(data["current_latitude"])
	except (ValueError, TypeError, KeyError) as e:
		abort(400, f"Invalid field types: {str(e)}")
	try:
		drone = Drone(
			battery_level=battery_level,
			status=status,
			current_longitude=current_longitude,
			current_latitude=current_latitude
		)
		db.session.add(drone)
		db.session.commit()
	except Exception as e:
		app.logger.exception("Failed to create drone")
		abort(500, "Internal server error")
	return drone

# PATCH /drones/<int:drone_id> - update specific drone

@app.patch("/drones/<int:drone_id>")
@app.doc(tags=["Drones"])
@app.output(DroneOut)
def update_drone(drone_id):
	drone = db.session.get(Drone, drone_id)
	if not drone:
		abort(404, "Drone not found")
	data = request.get_json(silent=True)
	if data is None:
		abort(400, "Invalid or missing JSON in request body")
	allowed_fields = {"battery_level", "status", "current_longitude", "current_latitude"}
	updated = False
	for field in allowed_fields:
		if field in data:
			try:
				# Type conversion for PATCH
				if field == "battery_level":
					setattr(drone, field, int(data[field]))
				elif field in ("current_longitude", "current_latitude"):
					setattr(drone, field, float(data[field]))
				else:
					setattr(drone, field, str(data[field]))
				updated = True
			except (ValueError, TypeError) as e:
				abort(400, f"Invalid type for field '{field}': {str(e)}")
	if updated:
		try:
			db.session.commit()
		except Exception as e:
			app.logger.exception(f"Failed to update drone {drone_id}")
			abort(500, "Internal server error")
		return drone
	else:
		abort(400, "No valid fields to update")



# DELETE /drones/<int:drone_id> - delete a specific drone (APIFlask style)
@app.delete("/drones/<int:drone_id>")
@app.doc(tags=["Drones"])
@app.output({"message": String()}, status_code=200)
def delete_drone(drone_id):
	drone = db.session.get(Drone, drone_id)
	if not drone:
		abort(404, "Drone not found")
	try:
		db.session.delete(drone)
		db.session.commit()
	except Exception as e:
		app.logger.exception(f"Failed to delete drone {drone_id}")
		abort(500, "Internal server error")
	return {"message": f"Drone {drone_id} deleted"}



def execute_sql_file(sql_path):
	"""Executes SQL statements from a file using SQLAlchemy's engine."""
	with open(sql_path, "r") as f:
		sql_statements = f.read()
	with db.engine.connect() as connection:
		for statement in sql_statements.split(';'):
			stmt = statement.strip()
			# Skip empty statements and statements that are only comments
			if not stmt:
				continue
			# If all lines in the statement are comments or blank, skip
			if all(line.strip().startswith('--') or not line.strip() for line in stmt.splitlines()):
				continue
			connection.execute(text(stmt))

@app.teardown_appcontext
def shutdown(response_or_exc=None):
	close_rabbitmq_connection()


def wait_for_db(max_retries=10, delay=2):
    for i in range(max_retries):
        try:
            db.session.execute(text("SELECT 1"))
            return True
        except OperationalError:
            print(f"Waiting for DB... ({i+1}/{max_retries})")
            time.sleep(delay)
    raise RuntimeError("Database not available after retries")


if __name__ == "__main__":
	with app.app_context():
		wait_for_db()  # Wait for DB to be ready before proceeding
		db.create_all()  # Create tables if they don't exist

		# Insert dummy drones if not already present
		if Drone.query.count() == 0:
			drones = [
				Drone(id=1, battery_level=100, status='available', current_longitude=-122.4194, current_latitude=37.7749),
				Drone(id=2, battery_level=100, status='maintenance', current_longitude=-122.4194, current_latitude=37.7749),
				Drone(id=3, battery_level=100, status='available', current_longitude=-122.4194, current_latitude=37.7749),
			]
			db.session.bulk_save_objects(drones)
			db.session.commit()

		wait_for_rabbitmq()  # Wait for RabbitMQ to be ready before proceeding
		
		print("\n[Drone Service] ===============================================", flush=True)
		print("[Drone Service] AMQP TWO-CONNECTION ARCHITECTURE:", flush=True)
		print("[Drone Service] 1. CONSUMER thread: Long-lived connection for telemetry/flight_update", flush=True)
		print("[Drone Service] 2. ANOMALY publishing: Fresh connection per anomaly (thread-safe)", flush=True)
		print("[Drone Service] ===============================================\n", flush=True)
		
		# Note: We no longer use persistent connection for publishing
		# open_rabbitmq_connection()  # DEPRECATED - see handle_drone_anomaly() for correct pattern
		
		# Start AMQP consumer thread
		consumer_thread = threading.Thread(target=amqp_consumer_thread, daemon=True)
		consumer_thread.start()

	app.run(host="0.0.0.0", port=8002)








