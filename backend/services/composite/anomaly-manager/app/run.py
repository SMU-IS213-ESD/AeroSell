#!/usr/bin/env python3
"""
Anomaly Manager - Composite Service
Orchestrates drone anomaly recovery by coordinating:
- Order service (to identify affected orders)
- Operations-support service (to assign repair staff)
- RabbitMQ messaging (for retries and notifications)
"""

import os
import json
import pika
import time
import requests
import threading
from datetime import datetime

# --- Configuration ---
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
ORDER_SERVICE_URL = os.environ.get("ORDER_SERVICE_URL", "http://kong:5000")
SUPPORT_SERVICE_URL = os.environ.get("SUPPORT_SERVICE_URL", "http://kong:5000")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://kong:5000")

# Exchange and Queue Configuration
ANOMALY_EXCHANGE = "drone_anomaly"
REPAIR_EXCHANGE = "repair_exchange"
REPAIR_QUEUE = "repair_queue"
REPAIR_DLX = "repair_dlx"
NOTIFICATION_EXCHANGE = "notification_exchange"


class AnomalyOrchestrator:
    """Orchestrates drone anomaly recovery workflow"""
    
    def __init__(self):
        self.connection = None
        self.channel = None
        self.running = True
    
    def connect(self):
        """Establish RabbitMQ connection"""
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()
            print("[Orchestrator] Connected to RabbitMQ")
        except Exception as e:
            print(f"[Orchestrator] Failed to connect: {e}")
            raise
    
    def close(self):
        """Close RabbitMQ connection"""
        if self.channel and not self.channel.is_closed:
            try:
                self.channel.close()
            except Exception:
                pass
        if self.connection and not self.connection.is_closed:
            try:
                self.connection.close()
            except Exception:
                pass
    
    def setup_exchanges_queues(self):
        """Setup RabbitMQ infrastructure"""
        # Declare exchanges
        print(f"[Orchestrator] Declaring exchange '{ANOMALY_EXCHANGE}' (type=topic)", flush=True)
        self.channel.exchange_declare(
            exchange=ANOMALY_EXCHANGE,
            exchange_type="topic",
            durable=True
        )
        
        print(f"[Orchestrator] Declaring exchange '{NOTIFICATION_EXCHANGE}' (type=topic)", flush=True)
        self.channel.exchange_declare(
            exchange=NOTIFICATION_EXCHANGE,
            exchange_type="topic",
            durable=True
        )
        
        print(f"[Orchestrator] Declaring exchange '{REPAIR_EXCHANGE}' (type=direct)", flush=True)
        self.channel.exchange_declare(
            exchange=REPAIR_EXCHANGE,
            exchange_type="direct",
            durable=True
        )
        
        print(f"[Orchestrator] Declaring exchange '{REPAIR_DLX}' (type=direct)", flush=True)
        self.channel.exchange_declare(
            exchange=REPAIR_DLX,
            exchange_type="direct",
            durable=True
        )
        
        # Anomaly consumer queue
        print(f"[Orchestrator] Declaring queue 'anomaly_recovery_queue'", flush=True)
        self.channel.queue_declare(queue="anomaly_recovery_queue", durable=True)
        
        print(f"[Orchestrator] Binding queue 'anomaly_recovery_queue' to exchange '{ANOMALY_EXCHANGE}' with routing_key='drone.anomaly'", flush=True)
        self.channel.queue_bind(
            exchange=ANOMALY_EXCHANGE,
            queue="anomaly_recovery_queue",
            routing_key="drone.anomaly"
        )
        
        # Repair consumer queue with DLX
        print(f"[Orchestrator] Declaring queue 'repair_queue' with DLX configuration", flush=True)
        self.channel.queue_declare(
            queue=REPAIR_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": REPAIR_DLX,
                "x-dead-letter-routing-key": "repair.retry",
                "x-message-ttl": 3000,  # 3 seconds
            }
        )
        
        print(f"[Orchestrator] Binding queue '{REPAIR_QUEUE}' to exchange '{REPAIR_EXCHANGE}' with routing_key='repair.request'", flush=True)
        self.channel.queue_bind(
            exchange=REPAIR_EXCHANGE,
            queue=REPAIR_QUEUE,
            routing_key="repair.request"
        )
        
        # DLX queue for retry
        print(f"[Orchestrator] Declaring queue 'repair_dlx_queue'", flush=True)
        self.channel.queue_declare(queue="repair_dlx_queue", durable=True)
        
        print(f"[Orchestrator] Binding queue 'repair_dlx_queue' to exchange '{REPAIR_DLX}' with routing_key='repair.retry'", flush=True)
        self.channel.queue_bind(
            exchange=REPAIR_DLX,
            queue="repair_dlx_queue",
            routing_key="repair.retry"
        )
        
        print("[Orchestrator] AMQP infrastructure ready", flush=True)
    
    def get_orders_for_drone(self, drone_id):
        """Fetch orders associated with drone"""
        try:
            url = f"{ORDER_SERVICE_URL}/orders/drone/{drone_id}?status=IN_DELIVERY"
            print(f"[Orchestrator] Calling: GET {url}", flush=True)
            response = requests.get(url, timeout=5)
            print(f"[Orchestrator] Response status: {response.status_code}", flush=True)
            if response.status_code == 200:
                data = response.json()
                orders = data.get("data", {}).get("orders", [])
                print(f"[Orchestrator] Fetched {len(orders)} orders: {orders}", flush=True)
                return orders
            print(f"[Orchestrator] Order service returned error: {response.status_code} - {response.text}", flush=True)
            return []
        except Exception as e:
            print(f"[Orchestrator] Failed to fetch orders: {e}", flush=True)
            return []
    
    def get_available_staff(self):
        """Fetch available support staff"""
        try:
            url = f"{SUPPORT_SERVICE_URL}/operations-support/staff/available"
            print(f"[Orchestrator] Calling: GET {url}", flush=True)
            response = requests.get(url, timeout=5)
            print(f"[Orchestrator] Response status: {response.status_code}", flush=True)
            if response.status_code == 200:
                staff = response.json()
                print(f"[Orchestrator] Fetched {len(staff)} staff members: {staff}", flush=True)
                return staff
            print(f"[Orchestrator] Support service returned error: {response.status_code} - {response.text}", flush=True)
            return []
        except Exception as e:
            print(f"[Orchestrator] Failed to fetch available staff: {e}", flush=True)
            return []
    
    def get_user_email(self, user_id):
        """Fetch user email from User service"""
        try:
            url = f"{USER_SERVICE_URL}/{user_id}"
            print(f"[Orchestrator] Calling: GET {url}", flush=True)
            response = requests.get(url, timeout=5)
            print(f"[Orchestrator] Response status: {response.status_code}", flush=True)
            if response.status_code == 200:
                user = response.json()
                email = user.get("email")
                print(f"[Orchestrator] User {user_id} email: {email}", flush=True)
                return email
            print(f"[Orchestrator] User service returned error: {response.status_code}", flush=True)
            return None
        except Exception as e:
            print(f"[Orchestrator] Failed to fetch user email for {user_id}: {e}", flush=True)
            return None
    
    def assign_staff(self, staff_id, drone_id, longitude, latitude):
        """Create staff assignment for drone repair"""
        try:
            url = f"{SUPPORT_SERVICE_URL}/operations-support/assignment"
            payload = {
                "staff_id": staff_id,
                "drone_id": drone_id,
                "longitude": longitude,
                "latitude": latitude,
                "status": "ASSIGNED"
            }
            print(f"[Orchestrator] Calling: POST {url} with payload {payload}", flush=True)
            response = requests.post(url, json=payload, timeout=5)
            print(f"[Orchestrator] Response status: {response.status_code}", flush=True)
            if response.status_code in [200, 201]:
                result = response.json()
                print(f"[Orchestrator] Assignment created: {result}", flush=True)
                return result
            print(f"[Orchestrator] Assignment failed: {response.status_code} - {response.text}", flush=True)
            return None
        except Exception as e:
            print(f"[Orchestrator] Failed to assign staff: {e}", flush=True)
            return None
    
    def update_order_status(self, order_id, status):
        """Update order status to DELAYED"""
        try:
            url = f"{ORDER_SERVICE_URL}/orders/{order_id}/status"
            payload = {"status": status}
            response = requests.patch(url, json=payload, timeout=5)
            if response.status_code in [200, 204]:
                print(f"[Orchestrator] Order {order_id} status updated to {status}")
                return True
            print(f"[Orchestrator] Status update failed: {response.status_code}")
            return False
        except Exception as e:
            print(f"[Orchestrator] Failed to update order: {e}")
            return False
    
    def publish_notification(self, notification_type, message, routing_key=None):
        """Publish notification message"""
        try:
            # All notifications use the unified routing key.
            if routing_key is None:
                routing_key = "notification"
            
            self.channel.basic_publish(
                exchange=NOTIFICATION_EXCHANGE,
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            print(f"[Orchestrator] Published {notification_type} notification to routing_key='{routing_key}'", flush=True)
        except Exception as e:
            print(f"[Orchestrator] Failed to publish notification: {e}", flush=True)
    
    def publish_repair_request(self, drone_id, longitude, latitude, timestamp):
        """Publish repair request to repair exchange"""
        try:
            repair_request = {
                "drone_id": drone_id,
                "longitude": longitude,
                "latitude": latitude,
                "timestamp": timestamp
            }
            
            self.channel.basic_publish(
                exchange=REPAIR_EXCHANGE,
                routing_key="repair.request",
                body=json.dumps(repair_request),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            print(f"[Orchestrator] Published repair request to repair_exchange for drone {drone_id}", flush=True)
        except Exception as e:
            print(f"[Orchestrator] Failed to publish repair request: {e}", flush=True)
    
    def handle_anomaly(self, ch, method, properties, body):
        """Main orchestration workflow for drone anomaly"""
        try:
            print(f"\n[Orchestrator] MESSAGE RECEIVED from queue='anomaly_recovery_queue'", flush=True)
            print(f"[Orchestrator] Raw body: {body}", flush=True)
            anomaly = json.loads(body)
            drone_id = anomaly.get("drone_id")
            timestamp = anomaly.get("timestamp")
            longitude = anomaly.get("current_longitude")
            latitude = anomaly.get("current_latitude")
            
            print(f"[Orchestrator] ================================", flush=True)
            print(f"[Orchestrator] Processing anomaly for Drone {drone_id}", flush=True)
            print(f"[Orchestrator] Timestamp: {timestamp}", flush=True)
            print(f"[Orchestrator] Location: ({latitude}, {longitude})", flush=True)
            print(f"[Orchestrator] ================================", flush=True)
            
            # Step 1: Get orders affected by this drone
            orders = self.get_orders_for_drone(drone_id)
            print(f"[Orchestrator] Found {len(orders)} active orders for drone {drone_id}", flush=True)
            
            # Step 2: If there ARE active orders, notify customers and update statuses
            if orders:
                print(f"[Orchestrator] Processing {len(orders)} affected orders...", flush=True)
                
                # Step 2a: Update order status to DELAYED for each affected order
                for order in orders:
                    order_id = order.get("order_id")
                    print(f"[Orchestrator] Updating order {order_id} status to DELAYED", flush=True)
                    self.update_order_status(order_id, "DELAYED")
                
                # Step 2b: Publish customer delay notifications
                for order in orders:
                    order_id = order.get("order_id")
                    user_id = order.get("user_id")
                    
                    # Fetch customer email from User service
                    customer_email = self.get_user_email(user_id)
                    if not customer_email:
                        print(f"[Orchestrator] WARNING: Could not fetch email for user {user_id}", flush=True)
                    
                    customer_notification = {
                        "user_id": user_id,
                        "order_id": order_id,
                        "customer_email": customer_email,
                        "message": f"Your delivery (Order {order_id}) has been delayed due to drone maintenance. Support staff has been assigned.",
                        "timestamp": timestamp,
                        "type": "delivery_delay"
                    }
                    print(f"[Orchestrator] Publishing customer delay notification for order {order_id}", flush=True)
                    self.publish_notification("customer", customer_notification)
            else:
                print(f"[Orchestrator] No active orders for drone {drone_id} - skipping order updates", flush=True)
            
            # Step 3: Publish repair request to repair exchange
            print(f"[Orchestrator] Publishing repair request for drone {drone_id}", flush=True)
            self.publish_repair_request(drone_id, longitude, latitude, timestamp)
            
            # Step 4: ACK the anomaly message (repair orchestration continues in repair queue consumer)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[Orchestrator] ✓ Anomaly message processed and published to repair queue", flush=True)
        
        except Exception as e:
            print(f"[Orchestrator] Error processing anomaly: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # NACK on error - will retry via DLX
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def handle_repair_request(self, ch, method, properties, body):
        """Handle repair request from repair queue with DLX retry logic"""
        try:
            print(f"\n[Orchestrator] REPAIR MESSAGE RECEIVED from queue='repair_queue'", flush=True)
            print(f"[Orchestrator] Raw body: {body}", flush=True)
            repair_request = json.loads(body)
            drone_id = repair_request.get("drone_id")
            longitude = repair_request.get("longitude")
            latitude = repair_request.get("latitude")
            timestamp = repair_request.get("timestamp")
            
            print(f"[Orchestrator] ================================", flush=True)
            print(f"[Orchestrator] Processing repair request for Drone {drone_id}", flush=True)
            print(f"[Orchestrator] Location: ({latitude}, {longitude})", flush=True)
            print(f"[Orchestrator] ================================", flush=True)
            
            # Step 1: Get available repair staff
            staff_list = self.get_available_staff()
            print(f"[Orchestrator] Found {len(staff_list)} available staff members", flush=True)
            
            if not staff_list:
                print("[Orchestrator] No available staff - NACKing with requeue=False to trigger DLX retry", flush=True)
                # NACK with requeue=False sends to DLX, waits TTL, then returns to repair_queue
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                return
            
            # Step 2: Assign first available staff to drone repair
            staff = staff_list[0]
            staff_id = staff.get("id")
            print(f"[Orchestrator] Attempting to assign staff {staff_id} to drone {drone_id}", flush=True)
            assignment = self.assign_staff(staff_id, drone_id, longitude, latitude)
            
            if assignment:
                print(f"[Orchestrator] Successfully assigned staff {staff_id} to drone {drone_id}", flush=True)
                
                # Step 3: Publish staff notification
                staff_email = staff.get("email")
                staff_notification = {
                    "staff_id": staff_id,
                    "staff_email": staff_email,
                    "drone_id": drone_id,
                    "location": {"latitude": latitude, "longitude": longitude},
                    "timestamp": timestamp,
                    "type": "drone_repair_assignment"
                }
                print(f"[Orchestrator] Publishing staff notification for staff {staff_id}", flush=True)
                self.publish_notification("staff", staff_notification)
                
                # ACK the message
                ch.basic_ack(delivery_tag=method.delivery_tag)
                print(f"[Orchestrator] ✓ Repair request completed - staff assigned and notified", flush=True)
            else:
                print("[Orchestrator] Failed to assign staff - NACKing with requeue=False for DLX retry", flush=True)
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        
        except Exception as e:
            print(f"[Orchestrator] Error processing repair request: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # NACK on error - will retry via DLX
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def start_consuming(self):
        """Start consuming both anomaly and repair messages"""
        try:
            print("[Orchestrator] Connecting to RabbitMQ...", flush=True)
            self.connect()
            print(f"[Orchestrator] Connected. Configuring exchanges and queues...", flush=True)
            self.setup_exchanges_queues()
            
            # Set QoS
            self.channel.basic_qos(prefetch_count=1)
            
            # Setup anomaly consumer
            print("[Orchestrator] Setting up consumer on anomaly_recovery_queue...", flush=True)
            self.channel.basic_consume(
                queue="anomaly_recovery_queue",
                on_message_callback=self.handle_anomaly,
                auto_ack=False
            )
            
            # Setup repair consumer
            print("[Orchestrator] Setting up consumer on repair_queue...", flush=True)
            self.channel.basic_consume(
                queue=REPAIR_QUEUE,
                on_message_callback=self.handle_repair_request,
                auto_ack=False
            )
            
            print("[Orchestrator] Started consuming anomaly and repair messages - waiting for messages...", flush=True)
            self.channel.start_consuming()
        
        except KeyboardInterrupt:
            print("[Orchestrator] Shutting down...")
        except Exception as e:
            print(f"[Orchestrator] Consumer error: {e}", flush=True)
        finally:
            self.close()


if __name__ == "__main__":
    print("[Orchestrator] ========================================", flush=True)
    print("[Orchestrator] Starting Anomaly Manager Orchestration Service", flush=True)
    print(f"[Orchestrator] RABBITMQ_URL={RABBITMQ_URL}", flush=True)
    print(f"[Orchestrator] ORDER_SERVICE_URL={ORDER_SERVICE_URL}", flush=True)
    print(f"[Orchestrator] SUPPORT_SERVICE_URL={SUPPORT_SERVICE_URL}", flush=True)
    print(f"[Orchestrator] USER_SERVICE_URL={USER_SERVICE_URL}", flush=True)
    print("[Orchestrator] ========================================", flush=True)
    orchestrator = AnomalyOrchestrator()
    orchestrator.start_consuming()
