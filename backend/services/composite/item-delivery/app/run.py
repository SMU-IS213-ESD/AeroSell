import datetime
import os
import json
import time
import threading
import logging
import sys
from apiflask import APIFlask, Schema, abort
from apiflask.fields import String, Integer
from flask import request
import requests
import pika
from apscheduler.schedulers.background import BackgroundScheduler

app = APIFlask(
	__name__,
	title="Item Delivery Service",
	version="1.0.0"
)

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
	try:
		resp = requests.patch(f"{ORDER_SERVICE_URL}/orders/{order_id}/status", json=payload, timeout=10)
		if resp.status_code in (200, 201):
			app.logger.info(f"Updated order {order_id} -> {status}")
			return True
		app.logger.error(
			f"Order status update returned {resp.status_code}: {resp.text}"
		)
	except Exception as e:
		app.logger.debug(f"Attempt to update order failed: {e}")
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
	app.logger.info(f"Dispatching drone for order {booking}")
	try:
		payload = {
			"pickup_location": booking.get("pickup_location"),
			"dropoff_location": booking.get("dropoff_location"),
			"order_id": str(booking.get("order_id")),
			"estimated_pickup_time": booking.get("estimated_pickup_time")
		}
		app.logger.info(f"Dispatching drone for order {drone}")
		resp = requests.post(f"{DRONE_SERVICE_URL}/drones/activate/{drone.get('id')}", json=payload, timeout=10)
		if resp.status_code in (200, 201):
			update_order_status(booking.get("order_id") or booking.get("id"), "IN_DELIVERY")
			data = resp.json()
			return data.get("mission_id") or data.get("id")
		app.logger.error(f"Drone dispatch failed: {resp.status_code} {resp.text}")
	except Exception as e:
		app.logger.exception(f"Dispatch exception: {e}")
	return None


def resolve_order_id_from_landing(payload: dict):
	"""Resolve order_id from landing payload; fallback to lookup by drone_id."""
	order_id = payload.get('order_id') or payload.get('order')
	if order_id:
		return order_id

	drone_id = payload.get('drone_id')
	if not drone_id:
		return None

	try:
		resp = requests.get(f"{ORDER_SERVICE_URL}/orders/drone/{drone_id}?status=IN_DELIVERY", timeout=10)
		if resp.status_code != 200:
			app.logger.warning(f"Could not resolve order for drone {drone_id}: order service returned {resp.status_code}")
			return None

		data = resp.json()
		if isinstance(data, list) and data:
			return data[0].get('order_id')
		if isinstance(data, dict):
			orders = data.get('orders')
			if not orders and isinstance(data.get('data'), dict):
				orders = data.get('data', {}).get('orders')
			if isinstance(orders, list) and orders:
				return orders[0].get('order_id')
	except Exception:
		app.logger.exception(f"Failed resolving order_id from drone_id {drone_id}")

	return None


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

			if update_order_status(order_id, "READY_FOR_DELIVERY"):
				mission_id = dispatch_drone(b, drone or {})
				if not mission_id:
					app.logger.error(f"Failed to dispatch drone for order {order_id}")
					continue
				update_order_status(order_id, "IN_DELIVERY")

		except Exception as e:
			app.logger.exception(f"Error processing booking {order_id}: {e}")


def start_scheduler():
	scheduler = BackgroundScheduler()
	#scheduler.add_job(process_confirmed_bookings, 'interval', minutes=30, next_run_time=None)
	scheduler.add_job(process_confirmed_bookings, 'interval', seconds=30)
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

def start_flight_update_consumer():
	if not RABBITMQ_URL:
		return

	def _consume():
		try:
			conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
			ch = conn.channel()
			ch.exchange_declare(exchange='drone', exchange_type='direct', durable=True)
			ch.queue_declare(queue='flight_update', durable=True)
			ch.queue_bind(exchange='drone', queue='flight_update', routing_key='flight_update')

			def callback(ch, method, properties, body):
				try:
					payload = json.loads(body)
					if payload.get('event') == 'landed':
						order_id = resolve_order_id_from_landing(payload)
						drone_id = payload.get('drone_id')
						app.logger.info(f"Received flight_update landed for drone {drone_id}, resolved order {order_id}")
						if not order_id:
							app.logger.warning(f"Skipping completion: unable to resolve order_id for landed drone {drone_id}")
							ch.basic_ack(delivery_tag=method.delivery_tag)
							return
						try:
							update_order_status(order_id, 'COMPLETED')
							publish_notification({'type': 'delivery_completed', 'order_id': order_id, 'drone_id': drone_id})
						except Exception:
							app.logger.exception(f"Failed to update order {order_id} to COMPLETED")
				except Exception:
					app.logger.exception('Failed handling flight_update message')
				ch.basic_ack(delivery_tag=method.delivery_tag)

			ch.basic_consume(queue='flight_update', on_message_callback=callback)
			app.logger.info('Started consuming flight_update queue')
			ch.start_consuming()
		except Exception:
			app.logger.exception('Flight update consumer stopped')

	t = threading.Thread(target=_consume, daemon=True)
	t.start()


@app.get("/health")
@app.doc(tags=["Health"], summary="Service health check")
# @app.route("/health", methods=["GET"])
def health():
	return {"status": "healthy", "service": "item-delivery"}, 200


if __name__ == '__main__':
	# start scheduler and rabbit consumer
	start_scheduler()
	start_rabbit_consumer()
	start_flight_update_consumer()
	# run flask
	app.run(host='0.0.0.0', port=8103)

