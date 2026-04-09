#!/usr/bin/env python3
"""
Test script to publish a sample notification message to the notifications queue.
Useful for testing the email-relay service locally.

Usage:
    python publish_test_message.py
"""

import json
import os
import sys

import pika

# Configuration
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://admin:58nczhxy@rmqbroker.dodieboy.qzz.io:5672/")
QUEUE_NAME = "notifications"

# Example notification payload
TEST_MESSAGE = {
    "emailAddress": "test@example.com",
    "emailSubject": "Test Notification",
    "emailBody": "This is a test notification message from email-relay test script.",
}


def publish_test_message() -> None:
    """Publish a test message to the notifications queue."""
    try:
        # Connect to RabbitMQ
        params = pika.URLParameters(RABBITMQ_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()

        # Declare the queue (passive=False to ensure it exists)
        channel.queue_declare(queue=QUEUE_NAME, durable=True, passive=False)

        # Publish the message
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps(TEST_MESSAGE),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
                content_type="application/json",
            ),
        )

        print(f"✓ Test message published to '{QUEUE_NAME}'")
        print(f"  Payload: {json.dumps(TEST_MESSAGE, indent=2)}")
        print(f"  RabbitMQ: {RABBITMQ_URL}")

        connection.close()

    except Exception as exc:
        print(f"✗ Error publishing message: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    publish_test_message()
