import random

from apiflask import APIFlask, Schema, abort
from apiflask.fields import String, Integer, Boolean, Float, DateTime, List as SchemaList, Nested, Dict
from marshmallow import validate
from flask import request, jsonify
from typing import List as TypingList
import os
import requests
import json
import pika
import uuid
from datetime import datetime, timedelta
import math
import stripe

# Schemas for documentation
class BookingOut(Schema):
    id = Integer()
    booking_id = String()
    user_id = String()
    status = String()

class DroneOut(Schema):
    id = Integer()
    drone_name = String()
    status = String()

class RouteSchema(Schema):
    pickup_location = String(required=True)
    dropoff_location = String(required=True)

class BookingIn(Schema):
    user_id = Integer(required=True)
    pickup_location = String(required=True)
    dropoff_location = String(required=True)
    # DateTime field automatically handles ISO format parsing
    timeslot = DateTime(required=True) 
    
    # Optional fields with defaults
    payment_method = String(load_default='stripe')
    package_weight_kg = Float(load_default=1.0)
    package_size = String(load_default='medium')
    fragile = Boolean(load_default=False)
    priority = Boolean(load_default=False)
    
    pickup_coordinates = Dict()
    dropoff_coordinates = Dict()
    pickup_point_id = String(load_default="")
    dropoff_point_id = String(load_default="")

class StatusIn(Schema):
    user_id = Integer(required=True)

class MilestoneOut(Schema):
    key = String()
    label = String()
    details = String()
    complete = Boolean()
    reachedAt = String()

class OrderStatusOut(Schema):
    order_id = String()
    user_id = String()
    pickup_location = String()
    dropoff_location = String()
    status = String()
    created = String()
    pickup_pin = String()
    milestones = SchemaList(Nested(MilestoneOut))

class PaymentDetailsIn(Schema):
    payment_intent_id = String(required=True)

class BookingConfirmIn(Schema):
    user_id = Integer(required=True)
    drone_id = String(required=True)
    pickup_location = String(required=True)
    dropoff_location = String(required=True)
    timeslot = DateTime(required=True)
    delivery_cost = Float(required=True)
    payment_method = String(load_default='stripe')
    payment_details = Nested(PaymentDetailsIn, required=True)

class PaymentIntentIn(Schema):
    amount = Float(required=True)
    currency = String(load_default="SGD")
    order_data = Dict()

app = APIFlask(
    __name__,
    title="Book-Drone Service",
    version="1.0.0"
)

# Service URLs (using Docker network names)
USER_SERVICE_URL = "http://kong:8000/user"
ORDER_SERVICE_URL = "http://kong:8000/order"
DRONE_SERVICE_URL = "http://kong:8000/drone"
FLIGHT_PLANNING_URL = "http://kong:8000/flight"
PAYMENT_SERVICE_URL = "http://kong:8000/payment"
INSURANCE_SERVICE_URL = "http://insurance:8500"

# Stripe configuration for webhooks
stripe.api_key = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# RabbitMQ configuration for notifications
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
if not RABBITMQ_URL:
    raise RuntimeError("RABBITMQ_URL environment variable is not set")

def get_user_info(user_id):
    """Validate and get user information from User Service"""
    try:
        response = requests.get(f"{USER_SERVICE_URL}/{user_id}", timeout=5)
        if response.status_code in [200, 201]:
            return response.json()
        return None
    except Exception as e:
        app.logger.error(f"Error calling User Service: {e}")
        return None

def get_available_drones(timeslot):
    """Get drones that are not booked and not under maintenance"""
    try:
        # Get all drones
        response = requests.get(f"{DRONE_SERVICE_URL}/drones", timeout=10)
        if response.status_code != 200:
            app.logger.error(f"Failed to get drones from drone service: {response.status_code}")
            response = requests.get(f"{DRONE_SERVICE_URL}/drones", timeout=10)
            if response.status_code == 200:
                all_drones = response.json()
                return [drone for drone in all_drones
                        if drone.get('status', '').lower() not in ['broken', 'maintenance']]
            return []

        all_drones = response.json()

        # Get all orders for the timeslot - increased timeout
        try:
            orders_response = requests.get(
                f"{ORDER_SERVICE_URL}/orders/by-timeslot?timeslot={timeslot}",
                timeout=15  # Increased timeout for slower order service
            )

            booked_drone_ids = []
            if orders_response.status_code == 200:
                orders = orders_response.json()
                booked_drone_ids = [order.get('drone_id') for order in orders if order.get('drone_id')]
        except Exception as e:
            app.logger.warning(f"Timeout/error checking orders: {e}. Proceeding with all drones.")
            booked_drone_ids = []  # Assume no bookings if service times out

        # Filter available drones
        available_drones = []
        for drone in all_drones:
            drone_status = drone.get('status', '').lower()
            if (drone['id'] not in booked_drone_ids and
                drone_status not in ['broken', 'maintenance']):
                available_drones.append(drone)

        app.logger.info(f"Found {len(available_drones)} available drones out of {len(all_drones)} total drones")
        return available_drones
    except Exception as e:
        app.logger.error(f"Error getting available drones: {e}")
        try:
            response = requests.get(f"{DRONE_SERVICE_URL}/drones", timeout=10)
            if response.status_code == 200:
                all_drones = response.json()
                return [d for d in all_drones if d.get('status', '').lower() not in ['broken', 'maintenance']]
        except:
            pass
        return []

def calculate_delivery_cost(distance_km, weight_kg=1, size='medium', fragile=False, priority=False):
    """Calculate delivery cost using same logic as BookingPage Live Price Estimate

    Mimics the calculateQuote function from frontend:
    - Base fare: $12
    - Distance fee: $0.95 per km
    - Weight fee: $2.10 per kg
    - Size multiplier: small=1.0, medium=1.22, large=1.48
    - Handling fee: $8 if fragile
    - Priority fee: $15 if priority
    - Platform fee: 6% of subtotal

    Args:
        distance_km: Delivery distance in kilometers
        weight_kg: Package weight in kilograms
        size: Package size - 'small', 'medium', or 'large'
        fragile: Boolean for fragile handling
        priority: Boolean for priority delivery

    Returns:
        Total delivery cost including all fees
    """
    # Base pricing from BookingPage
    base_fare = 12.0
    distance_fee = distance_km * 0.95
    weight_fee = weight_kg * 2.1

    # Size multipliers (match BookingPage.vue sizeMultiplier)
    size_multipliers = {'small': 1.0, 'medium': 1.22, 'large': 1.48}
    package_factor = size_multipliers.get(size, 1.22)

    # Additional fees
    handling_fee = 8.0 if fragile else 0.0
    priority_fee = 15.0 if priority else 0.0

    # Calculate subtotal before platform fee
    subtotal = (base_fare + distance_fee + weight_fee + handling_fee + priority_fee) * package_factor

    # Platform fee (6%)
    platform_fee = subtotal * 0.06

    # Total delivery cost
    total = subtotal + platform_fee

    # Return full breakdown to match calculateQuote from appStore.js
    return {
        'baseFare': round(base_fare, 2),
        'distanceFee': round(distance_fee, 2),
        'weightFee': round(weight_fee, 2),
        'packageFactor': round(package_factor, 2),
        'handlingFee': round(handling_fee, 2),
        'priorityFee': round(priority_fee, 2),
        'platformFee': round(platform_fee, 2),
        'total': round(total, 2)
    }

def validate_route_and_calculate_cost(pickup, dropoff, pickup_coords=None, dropoff_coords=None, package_weight_kg=1, package_size='medium', fragile=False, priority=False):
    """Validate route feasibility and calculate delivery cost"""
    try:
        # Build the payload based on available data
        payload = {
            'orderId': str(uuid.uuid4())  # Generate a unique order ID
        }

        # Use coordinates if available
        if pickup_coords and 'lat' in pickup_coords:
            payload['pickup'] = {'lat': pickup_coords['lat'], 'lon': pickup_coords['lon']}
        else:
            payload['pickup'] = {'lat': 1.2966, 'lon': 103.8523}  # Default to SMU

        if dropoff_coords and 'lat' in dropoff_coords:
            payload['dropoff'] = {'lat': dropoff_coords['lat'], 'lon': dropoff_coords['lon']}
        else:
            payload['dropoff'] = {'lat': 1.2994, 'lon': 103.8562}  # Default to Bugis

        response = requests.post(
            f"{FLIGHT_PLANNING_URL}/routes/validate",
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            route_validation = response.json()
            # Calculate cost based on estimated distance with package details
            distance_km = route_validation.get('estimatedDistanceKm', 0.0)
            delivery_cost = calculate_delivery_cost(distance_km, package_weight_kg, package_size, fragile, priority)
            route_validation.update(delivery_cost)
            return route_validation
        app.logger.error(f"Route validation failed with status {response.status_code}: {response.text}")
        return None
    except Exception as e:
        app.logger.error(f"Error validating route: {e}")
        return None

def process_payment(user_id, amount, payment_method):
    """Process payment via Payment Service"""
    try:
        # Generate temporary order_id (integer) since we haven't created the order yet
        # Use random number in safe range for PostgreSQL INTEGER (max: 2,147,483,647)
        import random
        temp_order_id = random.randint(1, 1000000000)  # Safe range for PostgreSQL INTEGER
        payload = {
            'order_id': temp_order_id,
            'amount': amount,
            'method': payment_method,
            'currency': 'SGD'
        }

        response = requests.post(
            f"{PAYMENT_SERVICE_URL}/",
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            return response.json()
        return None
    except Exception as e:
        app.logger.error(f"Error processing payment: {e}")
        return None

def verify_payment_intent(payment_intent_id):
    """Verify payment status via Payment Service using payment_intent_id from Stripe Elements"""
    try:
        # Call payment service to verify PaymentIntent status
        response = requests.get(
            f"{PAYMENT_SERVICE_URL}/",
            params={"transaction_id": payment_intent_id},
            timeout=10
        )

        if response.status_code not in (200, 201):
            app.logger.error(f"Payment service returned status {response.status_code} while verifying {payment_intent_id}")
            return None

        response_data = response.json()
        payments = response_data.get("payments") or []
        if not payments:
            app.logger.info(f"No payments found for transaction_id={payment_intent_id}")
            return None

        payment_details = payments[0]

        status = payment_details.get('status')
        # Map returned payment dict fields to expected keys
        payment_id = payment_details.get('id') or payment_details.get('payment_id')

        if status == 'succeeded':
            return {
                'status': 'succeeded',
                'payment_id': payment_id,
                'amount': payment_details.get('amount'),
                'currency': payment_details.get('currency'),
                'transaction_id': payment_details.get('transaction_id')
            }
        else:
            return {
                'status': status,
                'error': payment_details.get('error', 'Payment verification failed')
            }
    except Exception as e:
        app.logger.error(f"Error verifying payment intent: {e}")
        return None

def create_order_with_payment(user_id, drone_id, pickup, dropoff, timeslot, payment_details, insurance_id=None):
    """Create order record with payment details"""
    try:
        # Generate 8-digit pickup PIN
        import random
        pickup_pin = str(random.randint(10000000, 99999999))
        # Treat `timeslot` as the user's selected arrival time (estimated_arrival_time)
        arrival_iso = timeslot.isoformat() if hasattr(timeslot, 'isoformat') else str(timeslot)

        # Try to compute flight_time_min via validating the route so we can derive pickup time
        flight_time_min = None
        try:
            rv = validate_route_and_calculate_cost(pickup, dropoff)
            if rv:
                flight_time_min = rv.get('flightTimeMin') or rv.get('estimatedDurationMin')
        except Exception:
            app.logger.debug("Could not obtain flight_time_min from flight planning; defaulting to 0")

        if flight_time_min is not None:
            try:
                ft = float(flight_time_min)
                ft_ceil = math.ceil(ft)
                pickup_dt = timeslot - timedelta(minutes=ft_ceil)
                pickup_iso = pickup_dt.isoformat()
            except Exception:
                pickup_iso = arrival_iso
        else:
            pickup_iso = arrival_iso

        payload = {
            'user_id': str(user_id),
            'drone_id': drone_id,
            'pickup_location': pickup,
            'dropoff_location': dropoff,
            'estimated_pickup_time': pickup_iso,
            'estimated_arrival_time': arrival_iso,
            'status': 'CONFIRMED',
            'pickup_pin': pickup_pin,
            'insurance_id': insurance_id,
            'payment_details': payment_details
        }

        response = requests.post(
            f"{ORDER_SERVICE_URL}/order",
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            result = response.json()
            # Add pickup_pin to the result so it can be returned to frontend
            if result and 'order_id' in result:
                result['pickup_pin'] = pickup_pin
            return result
        return None
    except Exception as e:
        app.logger.error(f"Error creating order: {e}")
        return None

def send_notification(user_id, booking_details):
    """Send booking confirmation notification"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()

        # Declare notification queue if it doesn't exist
        channel.queue_declare(queue='notifications', durable=True)
        r = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=10)
        if r.status_code == 200:
            email = r.json().get("email")
        message = {
            "emailAddress": email,
            "emailSubject": "booking_confirmation",
            "emailBody": "Your booking is confirmed. Pickup PIN: " + booking_details.get('pickup_pin')
        }

        channel.basic_publish(
            exchange='',
            routing_key='notifications',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            )
        )

        connection.close()
        return True
    except Exception as e:
        app.logger.error(f"Error sending notification: {e}")
        return False

@app.get("/health")
@app.doc(tags=["Health"], summary="Service health check")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "book-drone"}

@app.post("/book")
@app.doc(tags=["Bookings"], summary="Book a drone for delivery")
@app.input(BookingIn)
@app.output(BookingOut, status_code=201)
def book_drone(json_data=None, **kwargs):
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")

    app.logger.info(f"Processing booking request for user {data['user_id']}")

    # Step 1: Validate user account
    user_info = get_user_info(data['user_id'])
    if not user_info:
        abort(400, 'User validation failed or user not found')

    # Step 2: Get available drones
    available_drones = get_available_drones(data['timeslot'])
    if not available_drones:
        abort(400, 'No drones available for the selected timeslot')

    drone_id = available_drones[0]['id']
    app.logger.info(f"Selected drone {drone_id} for booking")

    # Step 3: Validate route and calculate cost
    # We can pass the 'data' dict or unpack it
    route_validation = validate_route_and_calculate_cost(
        data['pickup_location'], 
        data['dropoff_location'], 
        data.get('pickup_coordinates'),
        data.get('dropoff_coordinates'),
        data['package_weight_kg'],
        data['package_size'],
        data['fragile'],
        data['priority']
    )
    
    if not route_validation:
        abort(400, 'Route validation failed')

    delivery_cost = route_validation.get('total', 0.0)

    # Step 4: Process payment
    payment_response = process_payment(data['user_id'], delivery_cost, data['payment_method'])
    if not payment_response or payment_response.get("status") != "succeeded":
        abort(400, f"Payment failed: {payment_response.get('status', 'Unknown')}")

    payment_id = payment_response.get("payment_id")

    # Step 5: Get insurance (External service)
    insurance_id = None
    try:
        r = requests.get(f"{INSURANCE_SERVICE_URL}/buy", timeout=10)
        if r.status_code == 200:
            insurance_id = r.json().get("insurance_id")
    except Exception:
        app.logger.exception("Insurance service call failed")

    # Step 6: Create order
    order_data = create_order_with_payment(
        data['user_id'], drone_id, data['pickup_location'], 
        data['dropoff_location'], data['timeslot'], payment_response, insurance_id
    )
    
    if not order_data:
        abort(500, 'Order creation failed')

    # Step 7: Finalize & Notify
    booking_id = str(uuid.uuid4())
    return {
        'success': True,
        'booking_id': booking_id,
        'order_id': order_data.get('order_id'),
        'payment_id': payment_id,
        'drone_id': drone_id,
        'amount_paid': delivery_cost,
        'status': 'CONFIRMED',
        'message': 'Booking confirmed successfully'
    }

@app.get("/available-drones")
@app.doc(tags=["Drones"], summary="Get available drones")
@app.output(TypingList[DroneOut])
def get_available_drones_endpoint():
    """Endpoint to check available drones for a specific timeslot"""
    try:
        timeslot_str = request.args.get('timeslot')
        if not timeslot_str:
            abort(400, 'timeslot parameter required')

        timeslot = datetime.fromisoformat(timeslot_str.replace('Z', '+00:00'))
        available_drones = get_available_drones(timeslot)
        return available_drones
    except Exception as e:
        abort(500, str(e))

@app.post("/validate")
@app.doc(tags=["Bookings"], summary="Validate booking parameters")
@app.input(BookingIn)
def validate_booking(json_data=None, **kwargs):
    """Phase 1: Validate user, check available drones, and validate route"""
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")
    
    # APIFlask has already:
    # 1. Verified all required fields exist
    # 2. Parsed 'timeslot' into a datetime object
    # 3. Handled defaults for package_weight_kg, etc.

    # Step 1: Validate user account
    user_info = get_user_info(data['user_id'])
    if not user_info:
        abort(400, 'User validation failed or user not found')

    # Step 2: Get available drones
    available_drones = get_available_drones(data['timeslot'])
    if not available_drones:
        abort(400, 'No drones available for the selected timeslot')

    selected_drone = available_drones[0]
    
    # Step 3: Validate route and calculate cost
    route_validation = validate_route_and_calculate_cost(
        data['pickup_location'], 
        data['dropoff_location'],
        data.get('pickup_coordinates'), 
        data.get('dropoff_coordinates'),
        data['package_weight_kg'], 
        data['package_size'],
        data['fragile'], 
        data['priority']
    )
    
    if not route_validation:
        abort(400, 'Route validation failed')

    return {
        'success': True,
        'user': user_info,
        'selected_drone': selected_drone,
        'available_drones': available_drones,
        'route_validation': route_validation,
        'pickup_location': data['pickup_location'],
        'dropoff_location': data['dropoff_location'],
        'timeslot': data['timeslot'].isoformat(),
        'delivery_cost': route_validation.get('total', 0.0),
        'message': 'Validation successful. Proceed to payment.'
    }

@app.post("/status")
@app.doc(tags=["Status"], summary="Get delivery status")
@app.input(StatusIn)
# No output schema added here for brevity, but you could use @app.output
def get_user_status(json_data=None, **kwargs):
    """Fetch delivery status from backend Order Service"""
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")

    user_id = data['user_id'] # Validated by @app.input

    # Step 1: External API Call
    try:
        response = requests.get(f"{ORDER_SERVICE_URL}/orders", timeout=10)
        response.raise_for_status() # Automatically handles non-200 codes
    except requests.RequestException:
        abort(502, 'Failed to connect to Order Service')

    raw = response.json()
    if isinstance(raw, list):
        all_orders = raw
    elif isinstance(raw, dict):
        all_orders = raw.get('orders') or raw.get('data', {}).get('orders', [])
    else:
        all_orders = []

    # Step 2: Filter and Transform
    status_orders = []
    # Filter for the user (converting user_id to string to match your original logic)
    user_orders = [o for o in all_orders if str(o.get('user_id')) == str(user_id)]

    for order in user_orders:
        status_lower = (order.get('status') or '').lower()
        created_at = order.get('created', '')

        # Define template inside the loop or as a constant
        milestones_template = [
            ('scheduled', 'Scheduled', 'Delivery slot reserved'),
            ('delivering', 'Delivering', 'Package are on the way'),
            ('delivered', 'Delivered', 'Package has been delivered'),
            ('completed', 'Completed', 'Delivery completed'),
        ]

        milestones = []
        for key, label, details in milestones_template:
            # Logic check for completeness
            is_complete = (
                (key == 'scheduled') or
                (status_lower == 'delivering' and key == 'delivering') or
                (status_lower == 'delivered' and key == 'delivered') or
                (status_lower in ('completed', 'finished') and key == 'completed')
            )

            milestones.append({
                'key': key,
                'label': label,
                'details': details,
                'complete': is_complete,
                'reachedAt': created_at if is_complete else ''
            })

        status_orders.append({
            'order_id': order.get('order_id'),
            'user_id': order.get('user_id'),
            'pickup_location': order.get('pickup_location'),
            'dropoff_location': order.get('dropoff_location'),
            'status': status_lower,
            'created': order.get('created'),
            'pickup_pin': order.get('pickup_pin'),
            'milestones': milestones
        })

    return {
        'success': True,
        'data': {
            'orders': status_orders
        }
    }

@app.post("/confirm")
@app.doc(tags=["Bookings"], summary="Confirm booking after payment")
@app.input(BookingConfirmIn)
@app.output(BookingOut, status_code=201)
def confirm_booking(json_data=None, **kwargs):
    """Phase 2: Verify payment and create order after Stripe confirmation"""
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")

    # 1. Accessing nested data is now safe and clean
    payment_intent_id = data['payment_details']['payment_intent_id']
    user_id = data['user_id']

    app.logger.info(f"Processing booking confirmation for user {user_id}")

    # 2. Verify Payment
    verification = verify_payment_intent(payment_intent_id)
    if not verification or verification.get('status') != 'succeeded':
        status = verification.get('status', 'unknown') if verification else 'failed'
        abort(400, f"Payment verification failed (status: {status})")

    payment_id = verification.get('payment_id')

    # 3. Insurance Service (External Call)
    insurance_id = None
    try:
        r = requests.get(f"{INSURANCE_SERVICE_URL}/buy", timeout=10)
        if r.status_code == 200:
            insurance_id = r.json().get("insurance_id")
    except Exception:
        app.logger.warning("Insurance service unavailable, proceeding without ID")

    # 4. Create Order
    order_data = create_order_with_payment(
        user_id, data['drone_id'], data['pickup_location'],
        data['dropoff_location'], data['timeslot'], verification, insurance_id
    )
    
    if not order_data:
        # In APIFlask, always use abort() for consistency over jsonify, status
        abort(500, 'Order creation failed')

    order_id = order_data.get('order_id')
    pickup_pin = order_data.get('pickup_pin')

    # 5. Finalize & Notify
    booking_id = str(uuid.uuid4())
    booking_details = {
        **data, # Includes user_id, pickup, etc.
        'booking_id': booking_id,
        'order_id': order_id,
        'payment_id': payment_id,
        'amount_paid': data['delivery_cost'],
        'pickup_pin': pickup_pin,
        'status': 'CONFIRMED'
    }
    
    send_notification(user_id, booking_details)

    return {
        'booking_id': booking_id,
        'order_id': order_id,
        'payment_id': payment_id,
        'drone_id': data['drone_id'],
        'pickup_pin': pickup_pin,
        'status': 'CONFIRMED'
    }

@app.post("/validate-route")
@app.doc(tags=["Routes"], summary="Validate and estimate route cost")
@app.input(RouteSchema)  # Injects validated data as 'data'
def validate_route(json_data=None, **kwargs):
    """Validate a route and get cost estimate"""
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")
    
    # Logic is now clean and focused
    result = validate_route_and_calculate_cost(
        data['pickup_location'],
        data['dropoff_location']
    )

    # If business logic fails, use APIFlask's abort
    if not result:
        abort(400, 'Route validation failed')

@app.post("/webhook")
@app.doc(tags=["Payments"], summary="Stripe webhook handler")
def stripe_webhook():
    """Handle Stripe webhooks to create orders after payment succeeds."""
    def _get_obj_id(o):
        try:
            return o['id']
        except Exception:
            return getattr(o, 'id', None)

    # Handle both Stripe webhooks (with signature) and direct test calls (without signature)
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    # If no signature and no STRIPE_WEBHOOK_SECRET configured, treat as test call
    if not sig_header:
        if not STRIPE_WEBHOOK_SECRET:
            app.logger.warning("No Stripe signature and no SECRET configured - treating as test")
            try:
                event = json.loads(payload)
            except:
                abort(400, "invalid JSON payload")
        else:
            abort(400, "missing Stripe signature header")
    else:
        # Verify Stripe signature
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            abort(400, "invalid payload")
        except stripe.error.SignatureVerificationError:
            abort(400, "invalid signature")

    typ = event["type"]
    obj = event["data"]["object"]

    if typ == "payment_intent.succeeded":
        tid = _get_obj_id(obj)
        app.logger.info(f"Processing payment_intent.succeeded: {tid}")

        # Step 1: Update payment status in payment service
        try:
            # Find payment by transaction_id
            payment_response = requests.get(
                f"{PAYMENT_SERVICE_URL}/",
                params={"transaction_id": tid},
                timeout=10
            )

            if payment_response.status_code != 200:
                app.logger.error(f"Failed to get payment: {payment_response.status_code}")
                abort(404, "Payment not found")

            payments = payment_response.json().get("payments", [])
            if not payments:
                app.logger.error(f"No payment found for transaction_id {tid}")
                abort(404, "Payment not found")

            payment = payments[0]
            payment_id = payment.get("id")
            payment_status = "succeeded"

            # Update payment status
            update_resp = requests.put(
                f"{PAYMENT_SERVICE_URL}/{payment_id}/status",
                json={"status": payment_status},
                timeout=10
            )

            if update_resp.status_code != 200:
                app.logger.error(f"Failed to update payment status: {update_resp.status_code}")
                abort(500, "Failed to update payment")

            app.logger.info(f"Payment {payment_id} status updated to succeeded")

        except Exception as e:
            app.logger.exception(f"Error updating payment status: {e}")
            abort(500, "Failed to update payment")

        # Step 2: Call insurance service to get insurance_id
        insurance_id = None
        try:
            insurance_response = requests.get(f"{INSURANCE_SERVICE_URL}/buy", timeout=10)
            if insurance_response.status_code == 200:
                insurance_data = insurance_response.json()
                insurance_id = insurance_data.get("insurance_id")
                app.logger.info(f"Obtained insurance_id {insurance_id}")
            else:
                app.logger.error(f"Failed to get insurance_id: {insurance_response.status_code}")
        except Exception as e:
            app.logger.exception("Failed to call insurance service")

        # Step 3: Create order with payment details
        # Fetch complete payment details including order_data from payment service
        try:
            payment_detail_response = requests.get(
                f"{PAYMENT_SERVICE_URL}/{payment_id}",
                timeout=10
            )


            if payment_detail_response.status_code == 200:
                full_payment_details = payment_detail_response.json()
                app.logger.error(f"DEBUG BOOK: payment_detail_response status_code = {full_payment_details}")
                order_data_str = full_payment_details.get("order_data")

                if order_data_str:
                    order_data = json.loads(order_data_str)

                    # Generate and keep pickup PIN so we can update payment record later
                    pickup_pin = str(random.randint(10000000, 99999999))

                    # # Map order_data fields to new order schema: compute estimated_pickup_time from arrival_time and flight_time_min
                    # estimated_arrival = order_data.get("estimated_arrival_time") or order_data.get("estimated_pickup_time") or order_data.get("item_description")
                    # flight_time_min = order_data.get("flight_time_min") or order_data.get("flightTimeMin")

                    # # Compute pickup time = arrival - ceil(flight_time_min) (minutes)
                    # pickup_iso = None
                    # try:
                    #     if estimated_arrival:
                    #         arrival_dt = datetime.fromisoformat(estimated_arrival.replace('Z', '+00:00'))
                    #         if flight_time_min is not None:
                    #             # coerce to float then round up to nearest whole minute
                    #             ft = float(flight_time_min)
                    #             ft_ceil = math.ceil(ft)
                    #             pickup_dt = arrival_dt - timedelta(minutes=ft_ceil)
                    #             pickup_iso = pickup_dt.isoformat()
                    #         else:
                    #             pickup_iso = arrival_dt.isoformat()
                    # except Exception:
                    #     pickup_iso = estimated_arrival

                    order_payload = {
                        "user_id": order_data.get("user_id"),
                        "pickup_location": order_data.get("pickup_location"),
                        "dropoff_location": order_data.get("dropoff_location"),
                        "estimated_pickup_time": order_data.get("estimated_pickup_time"),
                        "estimated_arrival_time": order_data.get("estimated_arrival_time"),
                        "drone_id": order_data.get("drone_id"),
                        "pickup_pin": pickup_pin,
                        "insurance_id": insurance_id
                    }

                    # Create order
                    order_response = requests.post(
                        f"{ORDER_SERVICE_URL}/order",
                        json=order_payload,
                        timeout=10
                    )

                    if order_response.status_code == 201:
                        order_result = order_response.json()

                        # Determine order_id robustly from response
                        order_id = None
                        o = order_result.get("order_id")
                        if isinstance(o, dict):
                            order_id = o.get("order_id")
                        else:
                            order_id = o or order_result.get("id") or order_result.get("orderId")

                        if order_id:
                            app.logger.info(f"Order {order_id} created successfully with insurance_id {insurance_id}")

                            # Update payment record so frontend polling sees order_id and pickup_pin
                            try:
                                update_resp = requests.put(
                                    f"{PAYMENT_SERVICE_URL}/{payment_id}",
                                    json={"order_id": order_id, "pickup_pin": pickup_pin},
                                    timeout=10
                                )

                                if update_resp.status_code in [200, 201]:
                                    app.logger.info(f"Payment {payment_id} updated with order_id {order_id} and pickup_pin")
                                else:
                                    app.logger.error(f"Failed to update payment {payment_id}: {update_resp.status_code} - {update_resp.text}")
                            except Exception as e:
                                app.logger.exception(f"Exception updating payment record: {e}")

                            return {
                                "received": True,
                                "order_id": order_id,
                                "insurance_id": insurance_id
                            }
                    else:
                        app.logger.error(f"Failed to create order: {order_response.status_code}")
                        abort(500, "Failed to create order")
                else:
                    app.logger.warning("No order_data in payment details, order creation skipped")
            else:
                app.logger.error(f"Failed to fetch payment details: {payment_detail_response.status_code}")
                abort(500, "Failed to fetch payment details")
        except Exception as e:
            app.logger.exception("Failed to create order")
            abort(500, "Failed to create order")

    elif typ == "payment_intent.payment_failed":
        tid = _get_obj_id(obj)
        app.logger.info(f"Processing payment_intent.payment_failed: {tid}")
        # Update payment status to failed
        try:
            payment_response = requests.get(
                f"{PAYMENT_SERVICE_URL}/",
                params={"transaction_id": tid},
                timeout=10
            )

            if payment_response.status_code == 200:
                payments = payment_response.json().get("payments", [])
                if payments:
                    payment = payments[0]
                    payment_id = payment.get("id")

                    update_resp = requests.put(
                        f"{PAYMENT_SERVICE_URL}/{payment_id}/status",
                        json={"status": "failed"},
                        timeout=10
                    )

                    if update_resp.status_code == 200:
                        app.logger.info(f"Payment {payment_id} status updated to failed")
        except Exception as e:
            app.logger.exception(f"Error updating payment status: {e}")

    return {"received": True}


@app.post("/create-payment-intent")
@app.doc(tags=["Payments"], summary="Create Stripe PaymentIntent")
@app.input(PaymentIntentIn)
def create_payment_intent(json_data=None, **kwargs):
    """Create a PaymentIntent and return client_secret for Stripe Elements"""
    data = json_data if isinstance(json_data, dict) else kwargs.get("data")
    if data is None:
        abort(400, "Request body must be valid JSON")
    
    # 1. Prepare payload (amount and currency are pre-validated)
    temp_order_id = random.randint(1, 1_000_000_000)
    payload = {
        "order_id": temp_order_id,
        "amount": data['amount'],
        "method": "stripe",
        "currency": data['currency']
    }
    
    if 'order_data' in data:
        payload["order_data"] = data['order_data']

    # 2. Call Payment Service to create
    try:
        resp = requests.post(f"{PAYMENT_SERVICE_URL}/", json=payload, timeout=10)
        resp.raise_for_status()
        create_result = resp.json()
        payment_id = create_result.get("payment_id")
    except requests.RequestException as e:
        app.logger.error(f"Payment service create error: {e}")
        abort(502, "Failed to create payment intent")

    # 3. Get Details (for client_secret/transaction_id)
    try:
        detail_resp = requests.get(f"{PAYMENT_SERVICE_URL}/{payment_id}", timeout=5)
        detail_resp.raise_for_status()
        details = detail_resp.json()
        
        # Using .get() with a fallback to the create_result for robustness
        client_secret = details.get("client_secret") or create_result.get("client_secret")
        transaction_id = details.get("transaction_id")

        return {
            "success": True,
            "client_secret": client_secret,
            "payment_id": payment_id,
            "transaction_id": transaction_id
        }
    except requests.RequestException as e:
        app.logger.error(f"Payment detail fetch error: {e}")
        abort(502, "Failed to retrieve payment details")

@app.get("/payments/<int:payment_id>")
@app.doc(tags=["Payments"], summary="Get payment details")
def get_payment(payment_id):
    """Get payment details from Payment Service"""
    try:
        response = requests.get(
            f"{PAYMENT_SERVICE_URL}/{payment_id}",
            timeout=10
        )

        if response.status_code == 200:
            return jsonify(response.json()), 200
        elif response.status_code == 404:
            return jsonify({"error": "Payment not found"}), 404
        else:
            return jsonify({"error": f"Payment service error: {response.status_code}"}), 502

    except Exception as e:
        app.logger.error(f"Error fetching payment: {e}")
        return jsonify({"error": "Failed to fetch payment details"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8101, debug=True)