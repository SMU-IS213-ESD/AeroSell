import json
import os
import time
import dotenv
import pika
dotenv.load_dotenv(".env")

def publish_error_telemetry() -> None:
    """Publish one error telemetry message and exit."""
    rabbitmq_url = os.environ.get("RABBITMQ_URL")
    if not rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL environment variable is required")

    telemetry_msg = {
        "drone_id": 1,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "error": True,
        "current_longitude": -122.4194,
        "current_latitude": 37.7749,
    }

    connection = None
    channel = None
    try:
        params = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()

        channel.exchange_declare(exchange="drone", exchange_type="direct", durable=True)
        channel.basic_publish(
            exchange="drone",
            routing_key="telemetry",
            body=json.dumps(telemetry_msg),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        print(f"Published ERROR telemetry: {telemetry_msg}", flush=True)
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


if __name__ == "__main__":
    publish_error_telemetry()
