from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
app = Flask(__name__)
db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)





# RabbitMQ (AMQP) setup
import pika

def get_rabbitmq_connection():
	"""Establish and return a RabbitMQ connection and channel."""
	rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp:rmqbroker.dodieboy.qzz.io")
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

	# telemetry = db.relationship('Telemetry', backref='drone', cascade="all, delete-orphan", lazy=True)

	def json(self):
		return {
			'id': self.id,
			'battery_level': self.battery_level,
			'status': self.status,
			'current_longitude': self.current_longitude,
			'current_latitude': self.current_latitude
		}



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


# GET /drones - get all drones
@app.route("/drones", methods=["GET"])
def get_all_drones():
	try:
		drones = Drone.query.all()
	except Exception as e:
		app.logger.exception("Failed to get all drones")
		return jsonify({"error": "Internal server error", "details": str(e)}), 500
	return jsonify([drone.json() for drone in drones]), 200

# GET /drones/available - get all available drones
@app.route("/drones/available", methods=["GET"])
def get_available_drones():
	try:
		drones = Drone.query.filter_by(status='available').all()
	except Exception as e:
		app.logger.exception("Failed to get available drones")
		return jsonify({"error": "Internal server error", "details": str(e)}), 500
	return jsonify([drone.json() for drone in drones]), 200

@app.route("/drones/activate/<int:drone_id>", methods=["POST"])
def activate_drone(drone_id):
	drone = Drone.query.get(drone_id)
	if not drone:
		return jsonify({"error": "Drone not found"}), 404
	try:
		drone.status = "in-flight"
		db.session.commit()
	except Exception as e:
		app.logger.exception(f"Failed to activate drone {drone_id}")
		return jsonify({"error": "Internal server error", "details": str(e)}), 500
	return jsonify(drone.json()), 200

@app.route("/drones", methods=["POST"])
def create_drone():
	data = request.get_json(silent=True)
	if data is None:
		return jsonify({"error": "Invalid or missing JSON in request body"}), 400
	required_fields = ["battery_level", "status", "current_longitude", "current_latitude"]
	missing_fields = [field for field in required_fields if field not in data]
	if missing_fields:
		return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400
	# Basic type validation
	try:
		battery_level = int(data["battery_level"])
		status = str(data["status"])
		current_longitude = float(data["current_longitude"])
		current_latitude = float(data["current_latitude"])
	except (ValueError, TypeError, KeyError) as e:
		return jsonify({"error": "Invalid field types", "details": str(e)}), 400
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
		return jsonify({"error": "Internal server error", "details": str(e)}), 500
	return jsonify(drone.json()), 201

# PATCH /drones/<int:drone_id> - update specific drone
@app.route("/drones/<int:drone_id>", methods=["PATCH"])
def update_drone(drone_id):
	drone = Drone.query.get(drone_id)
	if not drone:
		return jsonify({"error": "Drone not found"}), 404
	data = request.get_json(silent=True)
	if data is None:
		return jsonify({"error": "Invalid or missing JSON in request body"}), 400
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
				return jsonify({"error": f"Invalid type for field '{field}'", "details": str(e)}), 400
	if updated:
		try:
			db.session.commit()
		except Exception as e:
			app.logger.exception(f"Failed to update drone {drone_id}")
			return jsonify({"error": "Internal server error", "details": str(e)}), 500
		return jsonify(drone.json()), 200
	else:
		return jsonify({"error": "No valid fields to update"}), 400


# DELETE /drones/<int:drone_id> - delete a specific drone
@app.route("/drones/<int:drone_id>", methods=["DELETE"])
def delete_drone(drone_id):
	drone = Drone.query.get(drone_id)
	if not drone:
		return jsonify({"error": "Drone not found"}), 404
	try:
		db.session.delete(drone)
		db.session.commit()
	except Exception as e:
		app.logger.exception(f"Failed to delete drone {drone_id}")
		return jsonify({"error": "Internal server error", "details": str(e)}), 500
	return jsonify({"message": f"Drone {drone_id} deleted"}), 200



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

