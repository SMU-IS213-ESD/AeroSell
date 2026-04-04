from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, Float
from flask import jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os

app = APIFlask(__name__)
db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)





# RabbitMQ (AMQP) setup
import pika

def get_rabbitmq_connection():
	"""Establish and return a RabbitMQ connection and channel."""
	rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp://rmqbroker.dodieboy.qzz.io")
	params = pika.URLParameters(rabbitmq_url)
	connection = pika.BlockingConnection(params)
	channel = connection.channel()
	return connection, channel

def publish_message(exchange, routing_key, body, properties=None):
	"""Publish a message to RabbitMQ."""
	connection, channel = get_rabbitmq_connection()
	try:
		channel.basic_publish(
			exchange=exchange,
			routing_key=routing_key,
			body=body,
			properties=properties
		)
	finally:
		channel.close()
		connection.close()



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

# --- APIFlask Schema for Drone ---
class DroneOut(Schema):
	id = Integer()
	battery_level = Integer()
	status = String()
	current_longitude = Float()
	current_latitude = Float()



# class Telemetry(db.Model):
# 	__tablename__ = 'telemetry'
# 	id = db.Column(db.Integer, primary_key=True)
# 	drone_id = db.Column(db.Integer, db.ForeignKey('drones.id', ondelete="CASCADE"), nullable=False)
# 	timestamp = db.Column(db.DateTime, server_default=db.func.current_timestamp(), nullable=False)
# 	longitude = db.Column(db.Float, nullable=False)
# 	latitude = db.Column(db.Float, nullable=False)
# 	altitude = db.Column(db.Float, nullable=False)
#
# 	def json(self):
# 		return {
# 			'id': self.id,
# 			'drone_id': self.drone_id,
# 			'timestamp': self.timestamp.isoformat() if self.timestamp else None,
# 			'longitude': self.longitude,
# 			'latitude': self.latitude,
# 			'altitude': self.altitude
# 		}


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
	drone = Drone.query.get(drone_id)
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


@app.post("/drones/activate/<int:drone_id>")
@app.doc(tags=["Drones"])
@app.output(DroneOut)
def activate_drone(drone_id):
	drone = Drone.query.get(drone_id)
	if not drone:
		abort(404, "Drone not found")
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
	drone = Drone.query.get(drone_id)
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
    drone = Drone.query.get(drone_id)
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


if __name__ == "__main__":
	# execute the SQL file to create tables and insert initial data
	with app.app_context():
		sql_file_path = os.path.join(os.path.dirname(__file__), 'drone.sql')
		execute_sql_file(sql_file_path)
	app.run(host="0.0.0.0", port=8002)



# Example usage of publish_message, to use later to activate drone:
#
# from pika import BasicProperties
# publish_message(
#     exchange='',  # default exchange
#     routing_key='drone_status',  # queue name
#     body='{"drone_id": 1, "status": "in-flight"}',
#     properties=BasicProperties(content_type='application/json')
# )

# This will publish a JSON message to the 'drone_status' queue.

