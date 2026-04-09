
from apiflask import APIFlask, Schema
from apiflask.fields import String, Integer
from flask import jsonify
import threading
import time
import pika
import json
import os


app = APIFlask(__name__)

# --- Active drones tracking ---
active_drones = [1]  
telemetry_thread = None
telemetry_stop_event = threading.Event()
is_error = False  # Simulated error status for telemetry


def continuous_telemetry_publisher():
	"""Background thread that publishes telemetry for all active drones every 2 seconds."""
	global active_drones, telemetry_stop_event, is_error
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
		# Only declare exchange for publishing - don't declare/bind queues (consumer's job)
		channel.exchange_declare(exchange=exchange, exchange_type='direct', durable=True)
		
		while not telemetry_stop_event.is_set():
			print(f"{is_error}", flush=True)
			for drone_id in active_drones:
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
			if is_error:
				telemetry_stop_event.set()  # Stop telemetry if error is simulated
			time.sleep(2)  # Publish every 2 seconds
	except Exception as e:
		print(f"[Telemetry Thread] Failed: {e}", flush=True)
	finally:
		print(f"{is_error}", flush=True)
		if channel:
			try:
				channel.close()
			except Exception as e:
				print(f"Error closing channel: {e}", flush=True)
		if connection:
			try:
				connection.close()
			except Exception as e:
				print(f"Error closing connection: {e}", flush=True)


# Register teardown for app context
@app.teardown_appcontext
def shutdown(response_or_exc=None):
	global telemetry_stop_event
	telemetry_stop_event.set()


class OrderInfoSchema(Schema):
	pickup_location = String(required=True)
	dropoff_location = String(required=True)
	estimated_pickup_time = String(required=False)
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
		# Only declare exchange for publishing - don't declare/bind queues (consumer's job)
		channel.exchange_declare(exchange=exchange, exchange_type='direct', durable=True)
		
		landing_msg = {
			'drone_id': drone_id,
			'event': 'landed',
			'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
			'pickup_location': order_info.get('pickup_location'),
			'dropoff_location': order_info.get('dropoff_location'),
			'estimated_pickup_time': order_info.get('estimated_pickup_time'),
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
	
	# Publish error telemetry immediately with fresh connection
	rabbitmq_url = os.environ.get("RABBITMQ_URL")
	connection = None
	channel = None
	try:
		params = pika.URLParameters(rabbitmq_url)
		connection = pika.BlockingConnection(params)
		channel = connection.channel()
		channel.exchange_declare(exchange='drone', exchange_type='direct', durable=True)
		
		error_telemetry = {
			'drone_id': 1,
			'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
			'error': True,
			'current_longitude': -122.4194,
			'current_latitude': 37.7749
		}
		channel.basic_publish(
			exchange='drone',
			routing_key='telemetry',
			body=json.dumps(error_telemetry),
			properties=pika.BasicProperties(delivery_mode=2)
		)
		print(f"Published ERROR telemetry: {error_telemetry}", flush=True)
	except Exception as e:
		print(f"Failed to publish error telemetry: {e}", flush=True)
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
	
	return {'message': 'Error telemetry published.'}, 200

#removed reset endpoint, use docker compose restart drone-sim instead


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
	# Start the continuous telemetry publisher thread
	telemetry_stop_event.clear()
	telemetry_thread = threading.Thread(target=continuous_telemetry_publisher, daemon=True)
	telemetry_thread.start()
	
	app.run(host='0.0.0.0', port=8010)
