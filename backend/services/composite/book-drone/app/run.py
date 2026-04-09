import random

from flask import Flask, request, jsonify
import os
import requests
import json
import pika
import uuid
from datetime import datetime
import stripe

app = Flask(__name__)

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
    except Exception as e:
        app.logger.error(f"Error verifying payment intent: {e}")
        return None

def create_order_with_payment(user_id, drone_id, pickup, dropoff, timeslot, payment_details, insurance_id=None):
    """Create order record with payment details"""
    try:
        # Generate 8-digit pickup PIN
        import random
        pickup_pin = str(random.randint(10000000, 99999999))

        payload = {
            'user_id': str(user_id),
            'drone_id': drone_id,
            'pickup_location': pickup,
            'dropoff_location': dropoff,
            'item_description': f"Delivery booking - {timeslot}",
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

        message = {
            'type': 'booking_confirmation',
            'user_id': user_id,
            'booking_id': booking_details.get('booking_id'),
            'timeslot': booking_details.get('timeslot'),
            'pickup_location': booking_details.get('pickup_location'),
            'dropoff_location': booking_details.get('dropoff_location'),
            'amount_paid': booking_details.get('amount_paid'),
            'drone_id': booking_details.get('drone_id')
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

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "book-drone"}), 200

@app.route("/book", methods=["POST"])
def book_drone():
    """Main booking endpoint that orchestrates the entire workflow"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['user_id', 'pickup_location', 'dropoff_location', 'timeslot']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        user_id = data['user_id']
        pickup_location = data['pickup_location']
        dropoff_location = data['dropoff_location']
        timeslot = datetime.fromisoformat(data['timeslot'].replace('Z', '+00:00'))
        payment_method = data.get('payment_method', 'stripe')

        app.logger.info(f"Processing booking request for user {user_id}")

        # Step 1: Validate user account
        user_info = get_user_info(user_id)
        if not user_info:
            return jsonify({'error': 'User validation failed or user not found'}), 400

        app.logger.info("User validation successful")

        # Step 2: Get available drones for the timeslot
        available_drones = get_available_drones(timeslot)
        if not available_drones:
            return jsonify({'error': 'No drones available for the selected timeslot'}), 400

        # Select the first available drone
        selected_drone = available_drones[0]
        drone_id = selected_drone['id']

        app.logger.info(f"Selected drone {drone_id} for booking")

        # Step 3: Validate route and calculate cost
        route_validation = validate_route_and_calculate_cost(pickup_location, dropoff_location, data.get('pickup_coordinates'), data.get('dropoff_coordinates'), data.get('package_weight_kg', 1), data.get('package_size', 'medium'), data.get('fragile', False), data.get('priority', False))
        if not route_validation:
            return jsonify({'error': 'Route validation failed'}), 400

        delivery_cost = route_validation.get('total', 0.0)
        insurance_id = route_validation.get('insurance_id', '')

        app.logger.info(f"Route validated. Cost: ${delivery_cost}")

        # Step 4: Process payment
        payment_response = process_payment(user_id, delivery_cost, payment_method)
        if not payment_response:
            return jsonify({'error': 'Payment failed'}), 400

        # Verify payment was successful before creating order
        if payment_response.get("status") != "succeeded":
            return jsonify({"error": "Payment must be successful to create order", "payment_status": payment_response.get("status")}), 400

        payment_id = payment_response.get("payment_id")
        app.logger.info(f"Payment processed successfully. Payment ID: {payment_id}")

        # Step 5: Get insurance ID from insurance service
        insurance_id = None
        try:
            insurance_response = requests.get(f"{INSURANCE_SERVICE_URL}/buy", timeout=10)
            if insurance_response.status_code == 200:
                insurance_data = insurance_response.json()
                insurance_id = insurance_data.get("insurance_id")
                app.logger.info(f"Obtained insurance_id {insurance_id} for booking")
            else:
                app.logger.error(f"Failed to get insurance_id: {insurance_response.status_code}")
        except Exception as e:
            app.logger.exception("Failed to call insurance service for insurance_id")

        # Step 6: Create order with booking, payment, and insurance details
        order_data = create_order_with_payment(
            user_id, drone_id, pickup_location, dropoff_location,
            timeslot, payment_response, insurance_id
        )
        if not order_data:
            return jsonify({'error': 'Order creation failed'}), 500

        order_id = order_data.get('order_id')

        app.logger.info(f"Order created successfully. Order ID: {order_id}")

        # Generate a booking ID for tracking
        booking_id = str(uuid.uuid4())

        booking_details = {
            'booking_id': booking_id,
            'user_id': user_id,
            'drone_id': drone_id,
            'order_id': order_id,
            'payment_id': payment_id,
            'pickup_location': pickup_location,
            'dropoff_location': dropoff_location,
            'timeslot': timeslot.isoformat(),
            'amount_paid': delivery_cost,
            'insurance_id': insurance_id,
            'status': 'CONFIRMED'
        }

        # Step 6: Send notification
        send_notification(user_id, booking_details)

        app.logger.info(f"Booking record created. Booking ID: {booking_id}")

        # Return booking confirmation
        return jsonify({
            'success': True,
            'booking_id': booking_id,
            'order_id': order_id,
            'payment_id': payment_id,
            'drone_id': drone_id,
            'amount_paid': delivery_cost,
            'status': 'CONFIRMED',
            'message': 'Booking confirmed successfully'
        }), 201

    except Exception as e:
        app.logger.error(f"Booking error: {str(e)}")
        return jsonify({'error': f'Booking failed: {str(e)}'}), 500

@app.route("/available-drones", methods=["GET"])
def get_available_drones_endpoint():
    """Endpoint to check available drones for a specific timeslot"""
    try:
        timeslot_str = request.args.get('timeslot')
        if not timeslot_str:
            return jsonify({'error': 'timeslot parameter required'}), 400

        timeslot = datetime.fromisoformat(timeslot_str.replace('Z', '+00:00'))
        available_drones = get_available_drones(timeslot)

        return jsonify({
            'timeslot': timeslot.isoformat(),
            'available_drones': available_drones,
            'count': len(available_drones)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/validate", methods=["POST"])
def validate_booking():
    """Phase 1: Validate user, check available drones, and validate route

    Returns data needed for payment page: user info, available drones, route validation with cost
    """
    try:
        data = request.get_json()

        # Required fields
        required_fields = ['user_id', 'pickup_location', 'dropoff_location', 'timeslot']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        user_id = data['user_id']
        pickup_location = data['pickup_location']
        dropoff_location = data['dropoff_location']
        timeslot = datetime.fromisoformat(data['timeslot'].replace('Z', '+00:00'))

        app.logger.info(f"Validating booking for user {user_id}")

        # Step 1: Validate user account
        user_info = get_user_info(user_id)
        if not user_info:
            return jsonify({'error': 'User validation failed or user not found'}), 400

        app.logger.info("User validation successful")

        # Step 2: Get available drones for the timeslot
        available_drones = get_available_drones(timeslot)
        if not available_drones:
            return jsonify({'error': 'No drones available for the selected timeslot'}), 400

        # Select the first available drone
        selected_drone = available_drones[0]
        drone_id = selected_drone['id']

        app.logger.info(f"Selected drone {drone_id} for booking")

        # Step 3: Validate route and calculate cost
        route_validation = validate_route_and_calculate_cost(
            pickup_location, dropoff_location,
            data.get('pickup_coordinates'), data.get('dropoff_coordinates'),
        data.get('package_weight_kg', 1), data.get('package_size', 'medium'),
        data.get('fragile', False), data.get('priority', False)
        )
        if not route_validation:
            return jsonify({'error': 'Route validation failed'}), 400

        delivery_cost = route_validation.get('total', 0.0)

        app.logger.info(f"Route validated. Cost: ${delivery_cost}")

        # Return all validation data for payment page
        return jsonify({
            'success': True,
            'user': user_info,
            'selected_drone': selected_drone,
            'available_drones': available_drones,  # In case user wants to choose different drone
            'route_validation': route_validation,
            'pickup_location': pickup_location,
            'dropoff_location': dropoff_location,
            'timeslot': timeslot.isoformat(),
            'delivery_cost': delivery_cost,
            'message': 'Validation successful. Proceed to payment.'
        }), 200

    except Exception as e:
        app.logger.error(f"Validation error: {str(e)}")
        return jsonify({'error': f'Validation failed: {str(e)}'}), 500

@app.route("/status", methods=["POST"])
def get_user_status():
    """Fetch delivery status from backend Order Service"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        # Call Order Service to get user's orders
        response = requests.get(
            f"{ORDER_SERVICE_URL}/orders",
            timeout=10
        )

        if response.status_code != 200:
            return jsonify({'error': 'Failed to fetch orders'}), 502

        all_orders = response.json().get('data', {}).get('orders', [])

        # Filter orders for this user
        user_orders = [order for order in all_orders if order.get('user_id') == str(user_id)]

        # Transform to match StatusPage.vue format
        status_orders = []
        for order in user_orders:
            status_lower = (order.get('status') or '').lower()
            created_at = order.get('created', '')

            # Build milestones and mark complete based on backend status.
            milestones_template = [
                {'key': 'scheduled', 'label': 'Scheduled', 'details': 'Delivery slot reserved'},
                {'key': 'delivering', 'label': 'Delivering', 'details': 'Package are on the way to destination'},
                {'key': 'delivered', 'label': 'Delivered', 'details': 'Package has been delivered'},
                {'key': 'completed', 'label': 'Completed', 'details': 'Delivery completed'},
            ]

            milestones = []
            for m in milestones_template:
                key = m['key']
                is_complete = False

                # Always mark scheduled as complete (order exists)
                if key == 'scheduled':
                    is_complete = True
                # If backend reports "delivering", mark delivering milestone complete
                elif status_lower == 'delivering' and key == 'delivering':
                    is_complete = True
                elif status_lower == 'delivered' and key == 'delivered':
                    is_complete = True
                elif status_lower in ('completed', 'finished') and key == 'completed':
                    is_complete = True

                milestones.append({
                    'key': key,
                    'label': m.get('label', ''),
                    'details': m.get('details', ''),
                    'complete': is_complete,
                    'reachedAt': created_at if is_complete else ''
                })

            status_order = {
                'order_id': order.get('order_id'),
                'user_id': order.get('user_id'),
                'pickup_location': order.get('pickup_location'),
                'dropoff_location': order.get('dropoff_location'),
                'status': status_lower,
                'created': order.get('created'),
                'pickup_pin': order.get('pickup_pin'),
                'milestones': milestones
            }
            status_orders.append(status_order)

        return jsonify({
            'success': True,
            "code": 200,
            "data": {
                'orders': status_orders
            }
        }), 200

    except Exception as e:
        app.logger.error(f"Status fetch error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/confirm", methods=["POST"])
def confirm_booking():
    """Phase 2: Verify payment and create order after Stripe Elements confirmation

    Expects the validated data from /validate endpoint plus payment_intent_id
    """
    try:
        data = request.get_json()

        required_fields = ['user_id', 'drone_id', 'pickup_location', 'dropoff_location',
                          'timeslot', 'delivery_cost', 'payment_method']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        user_id = data['user_id']
        drone_id = data['drone_id']
        pickup_location = data['pickup_location']
        dropoff_location = data['dropoff_location']
        timeslot = datetime.fromisoformat(data['timeslot'].replace('Z', '+00:00'))
        delivery_cost = data['delivery_cost']
        payment_method = data.get('payment_method', 'stripe')
        payment_details = data.get('payment_details', {})
        payment_intent_id = payment_details.get('payment_intent_id')

        app.logger.info(f"Processing booking confirmation for user {user_id}")

        # Verify payment using payment_intent_id from Stripe Elements
        if not payment_intent_id:
            return jsonify({'error': 'payment_intent_id is required after Stripe Elements confirmation'}), 400

        verification_result = verify_payment_intent(payment_intent_id)
        if not verification_result:
            return jsonify({'error': 'Payment verification failed'}), 400

        if verification_result.get('status') != 'succeeded':
            return jsonify({
                'error': 'Payment must be successful to create order',
                'payment_status': verification_result.get('status')
            }), 400

        payment_id = verification_result.get('payment_id')

        app.logger.info(f"Payment processed successfully. Payment ID: {payment_id}")

        # Step 5: Get insurance ID from insurance service
        insurance_id = None
        app.logger.error(f"DEBUG BOOK: insurance_id extracted = {insurance_id}")
        try:
            insurance_response = requests.get(f"{INSURANCE_SERVICE_URL}/buy", timeout=10)
            app.logger.error(f"DEBUG BOOK: insurance_id extracted = {insurance_id}")
            if insurance_response.status_code == 200:
                insurance_data = insurance_response.json()
                insurance_id = insurance_data.get("insurance_id")
                app.logger.info(f"Obtained insurance_id {insurance_id} for booking")
            else:
                app.logger.error(f"Failed to get insurance_id: {insurance_response.status_code}")
        except Exception as e:
            app.logger.exception("Failed to call insurance service for insurance_id")

        # Step 6: Create order with booking, payment, and insurance details
        order_data = create_order_with_payment(
            user_id, drone_id, pickup_location, dropoff_location,
            timeslot, verification_result, insurance_id
        )
        if not order_data:
            return jsonify({'error': 'Order creation failed'}), 500

        order_id = order_data.get('order_id')
        pickup_pin = order_data.get('pickup_pin')

        app.logger.info(f"Order created successfully. Order ID: {order_id}, Pickup PIN: {pickup_pin}")

        booking_id = str(uuid.uuid4())

        booking_details = {
            'booking_id': booking_id,
            'user_id': user_id,
            'drone_id': drone_id,
            'order_id': order_id,
            'payment_id': payment_id,
            'pickup_location': pickup_location,
            'dropoff_location': dropoff_location,
            'timeslot': timeslot.isoformat(),
            'amount_paid': delivery_cost,
            'pickup_pin': pickup_pin,
            'status': 'CONFIRMED'
        }

        # Step 6: Send notification
        send_notification(user_id, booking_details)

        app.logger.info(f"Booking confirmed. Booking ID: {booking_id}")

        # Return booking confirmation
        return jsonify({
            'success': True,
            'booking_id': booking_id,
            'order_id': order_id,
            'payment_id': payment_id,
            'drone_id': drone_id,
            'amount_paid': delivery_cost,
            'pickup_pin': pickup_pin,
            'status': 'CONFIRMED',
            'message': 'Booking confirmed successfully'
        }), 201

    except Exception as e:
        app.logger.error(f"Booking confirmation error: {str(e)}")
        return jsonify({'error': f'Booking confirmation failed: {str(e)}'}), 500

@app.route("/validate-route", methods=["POST"])
def validate_route():
    """Validate a route and get cost estimate"""
    try:
        data = request.get_json()
        if 'pickup_location' not in data or 'dropoff_location' not in data:
            return jsonify({'error': 'Missing pickup or dropoff location'}), 400

        result = validate_route_and_calculate_cost(
            data['pickup_location'],
            data['dropoff_location']
        )

        if not result:
            return jsonify({'error': 'Route validation failed'}), 400

        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/webhook", methods=["POST"])
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
                return jsonify({"error": "invalid JSON payload"}), 400
        else:
            return jsonify({"error": "missing Stripe signature header"}), 400
    else:
        # Verify Stripe signature
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            return jsonify({"error": "invalid payload"}), 400
        except stripe.error.SignatureVerificationError:
            return jsonify({"error": "invalid signature"}), 400

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
                return jsonify({"error": "Payment not found"}), 404

            payments = payment_response.json().get("payments", [])
            if not payments:
                app.logger.error(f"No payment found for transaction_id {tid}")
                return jsonify({"error": "Payment not found"}), 404

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
                return jsonify({"error": "Failed to update payment"}), 500

            app.logger.info(f"Payment {payment_id} status updated to succeeded")

        except Exception as e:
            app.logger.exception(f"Error updating payment status: {e}")
            return jsonify({"error": "Failed to update payment"}), 500

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

                    order_payload = {
                        "user_id": order_data.get("user_id"),
                        "pickup_location": order_data.get("pickup_location"),
                        "dropoff_location": order_data.get("dropoff_location"),
                        "item_description": order_data.get("item_description"),
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

                            return jsonify({
                                "received": True,
                                "order_id": order_id,
                                "insurance_id": insurance_id
                            }), 200
                    else:
                        app.logger.error(f"Failed to create order: {order_response.status_code}")
                        return jsonify({"error": "Failed to create order"}), 500
                else:
                    app.logger.warning("No order_data in payment details, order creation skipped")
            else:
                app.logger.error(f"Failed to fetch payment details: {payment_detail_response.status_code}")
                return jsonify({"error": "Failed to fetch payment details"}), 500
        except Exception as e:
            app.logger.exception("Failed to create order")
            return jsonify({"error": "Failed to create order"}), 500

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

    return jsonify({"received": True}), 200


@app.route("/create-payment-intent", methods=["POST"])
def create_payment_intent():
    """Create a PaymentIntent and return client_secret for Stripe Elements"""
    try:
        data = request.get_json()

        if not data or "amount" not in data:
            return jsonify({"error": "amount is required"}), 400

        amount = data.get("amount")
        currency = data.get("currency", "SGD")

        # Generate temporary order_id
        import random
        temp_order_id = random.randint(1, 1000000000)

        payload = {
            "order_id": temp_order_id,
            "amount": amount,
            "method": "stripe",
            "currency": currency
        }

        # Add order_data if provided (needed for webhook-driven order creation)
        order_data = data.get("order_data")
        if order_data:
            payload["order_data"] = order_data

        response = requests.post(
            f"{PAYMENT_SERVICE_URL}/",
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            result = response.json()
            payment_id = result.get("payment_id")

            # Get payment details to get client_secret and status
            payment_detail_response = requests.get(
                f"{PAYMENT_SERVICE_URL}/{payment_id}",
                timeout=5
            )

            if payment_detail_response.status_code in [200, 201]:
                payment_details = payment_detail_response.json()
                client_secret = payment_details.get("client_secret")
                transaction_id = payment_details.get("transaction_id")

                if not client_secret:
                    # Fallback for create response
                    client_secret = result.get("client_secret")

                return jsonify({
                    "success": True,
                    "client_secret": client_secret,
                    "payment_id": payment_id,
                    "transaction_id": transaction_id
                }), 200

        return jsonify({"error": "Failed to create payment intent"}), 502
    except Exception as e:
        app.logger.error(f"Error creating payment intent: {e}")
        return jsonify({"error": f"Payment intent creation failed: {str(e)}"}), 500
@app.route("/payments/<int:payment_id>", methods=["GET"])
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