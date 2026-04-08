#!/usr/bin/env python3
"""
AMQP Setup Script for AeroSell Drone Anomaly Recovery System

This script sets up all necessary exchanges and queues for the drone anomaly orchestration:
- drone_anomaly exchange (topic) - for publishing drone errors
- repair_exchange with Dead Letter Exchange (DLX) - for repair request orchestration
- notification_exchange (topic) - for customer/staff notifications

Run this once during system initialization to configure RabbitMQ.
"""

import pika
import sys

# Configuration
AMQP_HOST = "rmqbroker.dodieboy.qzz.io"
AMQP_PORT = 5672
AMQP_USERNAME = "admin"
AMQP_PASSWORD = "58nczhxy"
AMQP_HEARTBEAT = 300
AMQP_BLOCKED_TIMEOUT = 300

# Exchange configurations
EXCHANGES = [
    {"name": "drone_anomaly", "type": "topic", "durable": True},
    {"name": "repair_exchange", "type": "direct", "durable": True},
    {"name": "repair_dlx", "type": "direct", "durable": True},
    {"name": "notification_exchange", "type": "topic", "durable": True},
]

# Queue configurations
QUEUES = [
    # Anomaly logging
    {
        "name": "error.anomaly_log",
        "exchange": "drone_anomaly",
        "routing_key": "*.anomaly",
        "durable": True,
    },
    # Anomaly recovery orchestration
    {
        "name": "anomaly_recovery_queue",
        "exchange": "drone_anomaly",
        "routing_key": "drone.anomaly",
        "durable": True,
    },
    # Repair request queue with DLX
    {
        "name": "repair_queue",
        "exchange": "repair_exchange",
        "routing_key": "repair.request",
        "durable": True,
        "arguments": {
            "x-dead-letter-exchange": "repair_dlx",
            "x-dead-letter-routing-key": "repair.retry",
            "x-message-ttl": 30000,  # 30 seconds in milliseconds
        },
    },
    # Dead letter queue for repair retries
    {
        "name": "repair_dlx_queue",
        "exchange": "repair_dlx",
        "routing_key": "repair.retry",
        "durable": True,
    },
    # Customer notification queue
    {
        "name": "customer_notification_queue",
        "exchange": "notification_exchange",
        "routing_key": "notification.customer.delay",
        "durable": True,
    },
    # Staff notification queue
    {
        "name": "staff_notification_queue",
        "exchange": "notification_exchange",
        "routing_key": "notification.staff.repair",
        "durable": True,
    },
]


def connect_to_broker(hostname, port, username, password):
    """Establish connection to RabbitMQ broker."""
    try:
        print(f"[*] Connecting to AMQP broker {username}@{hostname}:{port}...")
        credentials = pika.PlainCredentials(username, password)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=hostname,
                port=port,
                credentials=credentials,
                heartbeat=AMQP_HEARTBEAT,
                blocked_connection_timeout=AMQP_BLOCKED_TIMEOUT,
            )
        )
        print("[✓] Connected to broker")
        return connection
    except pika.exceptions.AMQPConnectionError as e:
        print(f"[✗] Failed to connect to AMQP broker: {e}")
        raise


def create_exchanges(channel):
    """Create all required exchanges."""
    print("\n[*] Creating exchanges...")
    for exchange in EXCHANGES:
        try:
            channel.exchange_declare(
                exchange=exchange["name"],
                exchange_type=exchange["type"],
                durable=exchange["durable"],
            )
            print(f"    [✓] Exchange '{exchange['name']}' ({exchange['type']})")
        except Exception as e:
            print(f"    [✗] Failed to create exchange '{exchange['name']}': {e}")
            raise


def create_queues(channel):
    """Create all required queues and bind to exchanges."""
    print("\n[*] Creating queues and bindings...")
    for queue in QUEUES:
        try:
            # Declare queue with optional arguments (e.g., DLX, TTL)
            queue_args = queue.get("arguments", {})
            channel.queue_declare(
                queue=queue["name"],
                durable=queue["durable"],
                arguments=queue_args if queue_args else None,
            )
            
            # Bind queue to exchange
            channel.queue_bind(
                exchange=queue["exchange"],
                queue=queue["name"],
                routing_key=queue["routing_key"],
            )
            
            args_str = f" (args: {queue_args})" if queue_args else ""
            print(
                f"    [✓] Queue '{queue['name']}' → {queue['exchange']} "
                f"(key: {queue['routing_key']}){args_str}"
            )
        except Exception as e:
            print(f"    [✗] Failed to create queue '{queue['name']}': {e}")
            raise


def main():
    """Main setup routine."""
    connection = None
    try:
        print("=" * 70)
        print("AeroSell AMQP Infrastructure Setup")
        print("=" * 70)
        
        # Connect to broker
        connection = connect_to_broker(AMQP_HOST, AMQP_PORT, AMQP_USERNAME, AMQP_PASSWORD)
        channel = connection.channel()
        
        # Create exchanges and queues
        create_exchanges(channel)
        create_queues(channel)
        
        print("\n" + "=" * 70)
        print("[✓] AMQP setup completed successfully!")
        print("=" * 70)
        print("\nSetup Summary:")
        print(f"  • Exchanges created: {len(EXCHANGES)}")
        print(f"  • Queues created: {len(QUEUES)}")
        print("\nKey Components:")
        print("  • drone_anomaly exchange: Publishes drone error events")
        print("  • repair_exchange: Direct queue for repair request orchestration")
        print("  • repair_dlx: Dead letter exchange for retry logic (30s TTL)")
        print("  • notification_exchange: Topic for customer/staff notifications")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n[✗] Setup failed: {e}")
        sys.exit(1)
    finally:
        if connection:
            connection.close()
            print("\n[*] Connection closed")


if __name__ == "__main__":
    main()
