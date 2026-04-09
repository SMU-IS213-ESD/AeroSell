import datetime
import os
import json
import time
import threading
import logging
import sys
from flask import Flask, jsonify, request
import requests
import pika
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Configure logging so app.logger.info/debug appear on stdout (visible in Docker/container logs)
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
app.logger.setLevel(logging.INFO)
# Ensure Flask/Werkzeug loggers propagate to root
logging.getLogger('werkzeug').setLevel(logging.INFO)

# Service URLs (assume API gateway / Kong routes)
ORDER_SERVICE_URL = "http://kong:8000/order"
DRONE_SERVICE_URL = "http://kong:8000/drone"
FLIGHT_PLANNING_URL = "http://kong:8000/flight"
WEATHER_SERVICE_URL = os.environ.get("WEATHER_SERVICE_URL", "http://kong:8000/weather")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")

if not RABBITMQ_URL:
	app.logger.warning("RABBITMQ_URL not set; notifications will be disabled")


def publish_notification(message: dict, routing_key: str = "notifications"):
	if not RABBITMQ_URL:
		app.logger.warning("Skipping publish: no RABBITMQ_URL configured")
		return False
	try:
		conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
		ch = conn.channel()
		ch.queue_declare(queue=routing_key, durable=True)
		ch.basic_publish(exchange='', routing_key=routing_key, body=json.dumps(message), properties=pika.BasicProperties(delivery_mode=2))
		conn.close()
		app.logger.info(f"Published notification to {routing_key}")
		return True
	except Exception as e:
		app.logger.exception(f"Failed publishing notification: {e}")
		return False


def fetch_confirmed_bookings():
	"""Fetch confirmed bookings/orders that need delivery."""
	try:
		# Try common endpoints for orders listing filtered by status
		resp = requests.get(f"{ORDER_SERVICE_URL}/orders?status=CREATED", timeout=10)
		if resp.status_code == 200:
			data = resp.json()
			# support wrapped responses like { code:200, data: { orders: [...] } }
			orders = None
			if isinstance(data, dict):
				if "orders" in data:
					orders = data.get("orders")
				elif "data" in data and isinstance(data.get("data"), dict) and "orders" in data.get("data"):
					orders = data.get("data", {}).get("orders")
			elif isinstance(data, list):
				orders = data
			app.logger.info(f"Fetched orders with status=CREATED: {len(orders or [])} items")
			if orders is not None:
				return orders or []
		# fallback: try unfiltered orders and filter in code
		resp = requests.get(f"{ORDER_SERVICE_URL}/orders", timeout=10)
		if resp.status_code == 200:
			data = resp.json()
			# unpack wrapper if present
			items = None
			if isinstance(data, dict):
				if "orders" in data:
					items = data.get("orders")
				elif "data" in data and isinstance(data.get("data"), dict) and "orders" in data.get("data"):
					items = data.get("data", {}).get("orders")
			elif isinstance(data, list):
				items = data
			items = items or []
			return [o for o in items if (o.get("status") or "").upper() == "CREATED"]
	except Exception as e:
		app.logger.exception(f"Failed fetching bookings: {e}")
	return []


def assess_weather_for_booking(booking: dict) -> bool:
	"""Call weather service to decide if it's safe. Returns True if safe."""
	try:
		order_id = booking.get("order_id") or booking.get("id")

		resp = requests.get(f"{WEATHER_SERVICE_URL}/check", params={"lat": 1.28367, "lon": 103.85007}, timeout=10)
		if resp.status_code == 200:
			data = resp.json()
			safe = None
			if isinstance(data, dict):
				if "safe" in data:
					safe = data.get("safe")
				elif "data" in data and isinstance(data.get("data"), dict) and "safe" in data.get("data"):
					safe = data.get("data", {}).get("safe")
			return bool(safe)
		app.logger.error(f"Weather service returned {resp.status_code} for order {order_id}")
	except Exception as e:
		app.logger.exception(f"Weather check failed for order {booking.get('order_id') or booking.get('id')}: {e}")
	# conservative: if weather check fails, treat as unsafe
	return False


def update_order_status(order_id, status):
	"""Update the order status using the Order Service."""
	if not order_id:
		return False
	payload = {"status": status}
	# Try multiple possible endpoints until one succeeds
	url =f"{ORDER_SERVICE_URL}/orders/{order_id}/status",
	try:
		resp = requests.put(url, json=payload, timeout=10)
		if resp.status_code in (200, 201):
			app.logger.info(f"Updated order {order_id} -> {status} via {url}")
			return True
		# Some APIs may accept POST
		resp = requests.post(url, json=payload, timeout=10)
		if resp.status_code in (200, 201):
			app.logger.info(f"Updated order {order_id} -> {status} via POST {url}")
			return True
	except Exception:
		app.logger.debug(f"Attempt to update order via {url} failed")
	app.logger.error(f"Failed to update order {order_id} to {status}")
	return False


def get_drone_details(drone_id):
	try:
		resp = requests.get(f"{DRONE_SERVICE_URL}/drones/{drone_id}", timeout=10)
		if resp.status_code == 200:
			return resp.json()
	except Exception:
		app.logger.exception("Failed fetching drone details")
	return None


def dispatch_drone(booking: dict, drone: dict):
	"""Send booking + route to drone service to initiate dispatch. Returns mission_id or None."""
	try:
		payload = {
			"pickup_location": booking.get("pickup_location"),
			"dropoff_location": booking.get("dropoff_location"),
			"user_id": booking.get("user_id"),
			"estimated_pickup_time": booking.get("estimated_pickup_time")
		}
		resp = requests.post(f"{DRONE_SERVICE_URL}/drones/activate", json=payload, timeout=10)
		if resp.status_code in (200, 201):
			update_order_status(booking.get("order_id") or booking.get("id"), "IN_DELIVERY")
			data = resp.json()
			return data.get("mission_id") or data.get("id")
		app.logger.error(f"Drone dispatch failed: {resp.status_code} {resp.text}")
	except Exception as e:
		app.logger.exception(f"Dispatch exception: {e}")
	return None


def poll_mission_and_finalize(order_id, mission_id, timeout_seconds=1800, interval=5):
	"""Poll drone service for mission status until complete or timeout."""
	start = time.time()
	while time.time() - start < timeout_seconds:
		try:
			resp = requests.get(f"{DRONE_SERVICE_URL}/missions/{mission_id}", timeout=10)
			if resp.status_code == 200:
				status = resp.json().get("status")
				app.logger.info(f"Mission {mission_id} status: {status}")
				if status and status.lower() in ("completed", "done", "finished"):
					# Mark order completed and notify
					update_order_status(order_id, "COMPLETED")
					publish_notification({
						"type": "delivery_completed",
						"order_id": order_id,
						"mission_id": mission_id
					})
					return True
		except Exception:
			app.logger.debug("Failed polling mission status")
		time.sleep(interval)
	app.logger.warning(f"Mission {mission_id} did not complete within timeout")
	return False


def process_confirmed_bookings():
	app.logger.info("Item-Delivery: running scheduled delivery check")
	bookings = fetch_confirmed_bookings()
	app.logger.info(f"Found {len(bookings)} confirmed bookings")
	for b in bookings:
		order_id = b.get("order_id") or b.get("id")
		try:
			safe = assess_weather_for_booking(b)
			if not safe:
				app.logger.info(f"Weather unsafe for order {order_id}; delaying")
				update_order_status(order_id, "DELAYED")
				publish_notification({
					"type": "delivery_delayed",
					"order_id": order_id,
					"reason": "Weather conditions unsafe"
				})
				continue

			drone_id = b.get("drone_id")
			drone = get_drone_details(drone_id) if drone_id else None

			update_order_status(order_id, "READY_FOR_DELIVERY")
			mission_id = dispatch_drone(b, drone or {})
			if not mission_id:
				app.logger.error(f"Failed to dispatch drone for order {order_id}")
				continue

			update_order_status(order_id, "IN_TRANSIT")
			threading.Thread(target=poll_mission_and_finalize, args=(order_id, mission_id), daemon=True).start()

		except Exception as e:
			app.logger.exception(f"Error processing booking {order_id}: {e}")


def start_scheduler():
	scheduler = BackgroundScheduler()
	#scheduler.add_job(process_confirmed_bookings, 'interval', minutes=30, next_run_time=None)
	scheduler.add_job(process_confirmed_bookings, 'interval', seconds=20)
	scheduler.start()
	#app.logger.info("Scheduler started: will run delivery check every 30 minutes")


def start_rabbit_consumer():
	if not RABBITMQ_URL:
		return

	def _consume():
		try:
			conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
			ch = conn.channel()
			ch.queue_declare(queue='drone_events', durable=True)

			def callback(ch, method, properties, body):
				try:
					payload = json.loads(body)
					if payload.get('type') == 'delivery_completed':
						order_id = payload.get('order_id')
						app.logger.info(f"Received delivery_completed for order {order_id}")
						update_order_status(order_id, 'COMPLETED')
						publish_notification({
							'type': 'delivery_success',
							'order_id': order_id
						})
				except Exception:
					app.logger.exception('Failed handling drone event')
				ch.basic_ack(delivery_tag=method.delivery_tag)

			ch.basic_consume(queue='drone_events', on_message_callback=callback)
			app.logger.info('Started consuming drone_events queue')
			ch.start_consuming()
		except Exception:
			app.logger.exception('Rabbit consumer stopped')

	t = threading.Thread(target=_consume, daemon=True)
	t.start()


@app.route("/health", methods=["GET"])
def health():
	return jsonify({"status": "healthy", "service": "item-delivery"}), 200


if __name__ == '__main__':
	# start scheduler and rabbit consumer
	start_scheduler()
	start_rabbit_consumer()
	# run flask
	app.run(host='0.0.0.0', port=8103)

