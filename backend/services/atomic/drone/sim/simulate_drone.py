
from apiflask import APIFlask, Schema
from apiflask.fields import String, Integer
from flask import jsonify
import threading
import time
import pika
import json
import os


app = APIFlask(__name__)

# --- RabbitMQ (AMQP) persistent connection setup ---
rabbitmq_connection = None
rabbitmq_channel = None

# --- Active drones tracking ---
active_drones = [1]  
telemetry_thread = None
telemetry_running = False
is_error = False  # Simulated error status for telemetry

def open_rabbitmq_connection():
	global rabbitmq_connection, rabbitmq_channel
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	params = pika.URLParameters(rabbitmq_url)
	rabbitmq_connection = pika.BlockingConnection(params)
	rabbitmq_channel = rabbitmq_connection.channel()
	# Declare exchange and queues once at startup
	exchange = 'drone'
	telemetry_queue = 'telemetry'
	flight_update_queue = 'flight_update'
	rabbitmq_channel.exchange_declare(exchange=exchange, exchange_type='direct', durable=True)
	rabbitmq_channel.queue_declare(queue=telemetry_queue, durable=True)
	rabbitmq_channel.queue_declare(queue=flight_update_queue, durable=True)
	rabbitmq_channel.queue_bind(exchange=exchange, queue=telemetry_queue)
	rabbitmq_channel.queue_bind(exchange=exchange, queue=flight_update_queue)

def close_rabbitmq_connection(e=None):
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
	global rabbitmq_channel
	if rabbitmq_channel is None:
		raise RuntimeError("RabbitMQ channel is not initialized.")
	rabbitmq_channel.basic_publish(
		exchange=exchange,
		routing_key=routing_key,
		body=body,
		properties=properties
	)


def continuous_telemetry_publisher():
	"""Background thread that publishes telemetry for all active drones every 2 seconds."""
	global active_drones, telemetry_running,is_error
	import pika
	
	exchange = 'drone'
	telemetry_queue = 'telemetry'
	
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	params = pika.URLParameters(rabbitmq_url)
	connection = None
	channel = None
	
	try:
		connection = pika.BlockingConnection(params)
		channel = connection.channel()
		# Ensure exchange and queues exist
		channel.exchange_declare(exchange=exchange, exchange_type='direct', durable=True)
		channel.queue_declare(queue=telemetry_queue, durable=True)
		channel.queue_bind(exchange=exchange, queue=telemetry_queue)
		
		while telemetry_running:
			for drone_id  in active_drones:
				telemetry_msg = {
					'drone_id': drone_id,
					'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
					'error': is_error,  # Simulated error status
					'current_longitude': -122.4194,  # Simulated longitude
					'current_latitude': 37.7749  # Simulated latitude
				}
				channel.basic_publish(
					exchange=exchange,
					routing_key=telemetry_queue,
					body=json.dumps(telemetry_msg),
					properties=pika.BasicProperties(delivery_mode=2)
				)
				print(f"Published telemetry for drone {drone_id}: {telemetry_msg}", flush=True)
			time.sleep(2)  # Publish every 2 seconds
			if is_error:
				telemetry_running = False  # Stop telemetry if error is simulated
	except Exception as e:
		print(f"[Telemetry Thread] Failed: {e}", flush=True)
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


# Register teardown for app context (like drone service)
@app.teardown_appcontext
def shutdown(response_or_exc=None):
	global telemetry_running
	telemetry_running = False
	close_rabbitmq_connection()


class OrderInfoSchema(Schema):
	pickup_location = String(required=True)
	dropoff_location = String(required=True)
	item_description = String(required=True)
	user_id = String(required=True)


def publish_landing_event(drone_id, order_info):
	"""Publish a landing event for a drone."""
	exchange = 'drone'
	flight_update_queue = 'flight_update'
	
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	params = pika.URLParameters(rabbitmq_url)
	connection = None
	channel = None
	try:
		connection = pika.BlockingConnection(params)
		channel = connection.channel()
		# Ensure queues exist
		channel.exchange_declare(exchange=exchange, exchange_type='direct', durable=True)
		channel.queue_declare(queue=flight_update_queue, durable=True)
		channel.queue_bind(exchange=exchange, queue=flight_update_queue)
		
		landing_msg = {
			'drone_id': drone_id,
			'event': 'landed',
			'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
			'pickup_location': order_info.get('pickup_location'),
			'dropoff_location': order_info.get('dropoff_location'),
			'item_description': order_info.get('item_description'),
			'user_id': order_info.get('user_id'),
		}
		channel.basic_publish(
			exchange=exchange,
			routing_key=flight_update_queue,
			body=json.dumps(landing_msg),
			properties=pika.BasicProperties(delivery_mode=2)
		)
		print(f"Published landing event for drone {drone_id}: {landing_msg}", flush=True)
	except Exception as e:
		print(f"Failed to publish landing event: {e}", flush=True)
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


def drone_flight_simulator(drone_id, order_info, duration=10, interval=0.5):
	"""Simulate a drone flight, print progress every interval seconds, then publish landing event."""

	steps = int(duration / interval)
	
	try:
		for i in range(steps + 1):
			progress = int(i * 100 / steps)
			print(f"[Drone {drone_id}] Flight progress: {progress}%", flush=True)
			time.sleep(interval)
		
		# Flight complete, publish landing event
		publish_landing_event(drone_id, order_info)
	except Exception as e:
		print(f"[Drone {drone_id}] Flight simulation error: {e}", flush=True)
	
@app.post('/dronesim/error')
def simulate_error():
	global is_error
	is_error = True
	return {'message': 'Error simulated.'}, 200

@app.post('/dronesim/reset')
def reset_simulation():
	global is_error, telemetry_running, telemetry_thread
	is_error = False  # Reset error status
	telemetry_running = True  # Ensure telemetry thread is running
	telemetry_thread = threading.Thread(target=continuous_telemetry_publisher, daemon=True)
	telemetry_thread.start()
	return {'message': 'Drone simulation reset. Active drones set to [1].'}, 200

@app.post('/dronesim/activate/<int:drone_id>')
@app.input(OrderInfoSchema, location='json')
def activate_drone(json_data, drone_id):
	order_info = json_data
	
	duration = order_info.get('duration', 10)
	print(f"Drone {drone_id} activated. Starting flight simulation for {duration} seconds.", flush=True)
	
	# Spawn background thread to simulate flight
	thread = threading.Thread(target=drone_flight_simulator, args=(drone_id, order_info, duration))
	thread.daemon = True
	thread.start()
	
	return {'message': f'Drone {drone_id} flight activated.'}, 200


if __name__ == '__main__':
	with app.app_context():
		# Open RabbitMQ connection before starting Flask app
		open_rabbitmq_connection()
	
	# Start the continuous telemetry publisher thread
	telemetry_running = True
	telemetry_thread = threading.Thread(target=continuous_telemetry_publisher, daemon=True)
	telemetry_thread.start()
	
	app.run(host='0.0.0.0', port=8010)
