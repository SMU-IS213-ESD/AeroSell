
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


# Register teardown for app context (like drone service)
@app.teardown_appcontext
def shutdown(response_or_exc=None):
	close_rabbitmq_connection()


class OrderInfoSchema(Schema):
	pickup_location = String(required=True)
	dropoff_location = String(required=True)
	item_description = String(required=True)
	user_id = String(required=True)
	


def publish_telemetry(drone_id, order_info, duration=10, interval=0.5):
	import pika
	exchange = 'drone'
	telemetry_queue = 'telemetry'
	flight_update_queue = 'flight_update'
	steps = int(duration / interval)

	# Each thread creates its own connection and channel
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
		channel.queue_declare(queue=flight_update_queue, durable=True)
		channel.queue_bind(exchange=exchange, queue=telemetry_queue)
		channel.queue_bind(exchange=exchange, queue=flight_update_queue)

		for i in range(steps + 1):
			progress = int(i * 100 / steps)
			telemetry_msg = {
				'drone_id': drone_id,
				'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
				'progress': progress
			}
			channel.basic_publish(
				exchange=exchange,
				routing_key=telemetry_queue,
				body=json.dumps(telemetry_msg),
				properties=pika.BasicProperties(delivery_mode=2)
			)
			print(f"Published telemetry: {telemetry_msg}", flush=True)
			time.sleep(interval)

		# After completion, publish landing event
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
	except Exception as e:
		print(f"[Thread] Failed to publish telemetry: {e}", flush=True)
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


#TODO: add ability to interrupt simulation and trigger anomaly event

@app.post('/dronesim/activate/<int:drone_id>')
@app.input(OrderInfoSchema, location='json')
def activate_drone(json_data, drone_id):
	order_info = json_data
	print(f"Activating drone {drone_id} with order info: {order_info}", flush=True)
	duration = order_info.get('duration', 10)
	thread = threading.Thread(target=publish_telemetry, args=(drone_id, order_info, duration))
	thread.daemon = True
	thread.start()
	return {'message': f'Simulation started for drone {drone_id}.'}, 200

if __name__ == '__main__':
	with app.app_context():
		# Open RabbitMQ connection before starting Flask app
		open_rabbitmq_connection()
	app.run(host='0.0.0.0', port=8010)
