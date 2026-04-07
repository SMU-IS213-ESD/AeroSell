from flask import Flask, request, jsonify
import os
import requests
import json
import pika
import uuid
from datetime import datetime

app = Flask(__name__)

# Service URLs (using Docker network names)
USER_SERVICE_URL = "http://user:8008"
ORDER_SERVICE_URL = "http://order:8006"
DRONE_SERVICE_URL = "http://drone:8002"
FLIGHT_PLANNING_URL = "http://flight-planning:8004"
PAYMENT_SERVICE_URL = "http://payment:8007"

# RabbitMQ configuration for notifications
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rmqbroker.dodieboy.qzz.io:5672/")

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
        response = requests.get(f"{DRONE_SERVICE_URL}/drones", timeout=5)
        if response.status_code != 200:
            return []

        all_drones = response.json()

        # Get all orders for the timeslot
        orders_response = requests.get(
            f"{ORDER_SERVICE_URL}/orders/by-timeslot?timeslot={timeslot}",
            timeout=5
        )

        booked_drone_ids = []
        if orders_response.status_code == 200:
            orders = orders_response.json()
            booked_drone_ids = [order['drone_id'] for order in orders]

        # Filter available drones
        available_drones = []
        for drone in all_drones:
            drone_status = drone.get('status', '').lower()
            if (drone['id'] not in booked_drone_ids and
                drone_status != 'broken' and
                drone_status != 'maintenance'):
                available_drones.append(drone)

        return available_drones
    except Exception as e:
        app.logger.error(f"Error getting available drones: {e}")
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

def create_order_with_payment(user_id, drone_id, pickup, dropoff, timeslot, payment_details):
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

        payment_id = payment_response.get('payment_id')

        app.logger.info(f"Payment processed successfully. Payment ID: {payment_id}")

        # Step 5: Create order with booking and payment details
        order_data = create_order_with_payment(
            user_id, drone_id, pickup_location, dropoff_location,
            timeslot, payment_response
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
            status_order = {
                'trackingCode': f"AS-{order.get('order_id', '000000')}",
                'ownerEmail': '',  # Would need to fetch from user service
                'fromLocation': order.get('pickup_location'),
                'toLocation': order.get('dropoff_location'),
                'status': order.get('status', 'unknown').lower(),
                'milestones': [
                    {'key': 'scheduled', 'label': 'Scheduled', 'details': 'Delivery slot reserved', 'complete': True, 'reachedAt': order.get('created', '')},
                    {'key': 'picked_up', 'label': 'Picked Up', 'details': 'Package collected', 'complete': False, 'reachedAt': ''},
                    {'key': 'in_flight', 'label': 'In Flight', 'details': 'Drone en route', 'complete': False, 'reachedAt': ''},
                    {'key': 'delivered', 'label': 'Delivered', 'details': 'Package delivered', 'complete': False, 'reachedAt': ''}
                ]
            }
            status_orders.append(status_order)

        return jsonify({
            'success': True,
            'orders': status_orders
        }), 200

    except Exception as e:
        app.logger.error(f"Status fetch error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/confirm", methods=["POST"])
def confirm_booking():
    """Phase 2: Process payment and create order after validation

    Expects the validated data from /validate endpoint
    """
    try:
        data = request.get_json()

        # Required fields
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

        app.logger.info(f"Processing booking confirmation for user {user_id}")

        # Step 4: Process payment
        payment_response = process_payment(user_id, delivery_cost, payment_method)
        if not payment_response:
            return jsonify({'error': 'Payment failed'}), 400

        payment_id = payment_response.get('payment_id')

        app.logger.info(f"Payment processed successfully. Payment ID: {payment_id}")

        # Step 5: Create order with booking and payment details
        order_data = create_order_with_payment(
            user_id, drone_id, pickup_location, dropoff_location,
            timeslot, payment_response
        )
        if not order_data:
            return jsonify({'error': 'Order creation failed'}), 500

        order_id = order_data.get('order_id')
        pickup_pin = order_data.get('pickup_pin')

        app.logger.info(f"Order created successfully. Order ID: {order_id}, Pickup PIN: {pickup_pin}")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8101, debug=True)