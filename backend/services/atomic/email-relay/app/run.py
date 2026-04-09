import json
import os
import time
from typing import Any, Dict, Tuple

import pika
import requests

RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
QUEUE_NAME = os.environ.get("NOTIFICATIONS_QUEUE", "notifications")
OUTSYSTEM_ENDPOINT = os.environ.get("OUTSYSTEM_ENDPOINT")
OUTSYSTEM_TIMEOUT_SECONDS = int(os.environ.get("OUTSYSTEM_TIMEOUT_SECONDS", "10"))
RELAY_MAX_RETRIES = int(os.environ.get("RELAY_MAX_RETRIES", "5"))
RELAY_BACKOFF_SECONDS = int(os.environ.get("RELAY_BACKOFF_SECONDS", "2"))
RELAY_LOG_PAYLOAD = os.environ.get("RELAY_LOG_PAYLOAD", "false").lower() == "true"




def wait_for_rabbitmq(max_retries: int = 15, delay: int = 2) -> None:
    print(f"[email-relay] Waiting for RabbitMQ at {RABBITMQ_URL}", flush=True)
    for i in range(max_retries):
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            # Queue should already exist; passive declare checks without creating.
            ch.queue_declare(queue=QUEUE_NAME, passive=True)
            ch.close()
            conn.close()
            print("[email-relay] RabbitMQ connection and queue check passed", flush=True)
            return
        except Exception as exc:
            print(
                f"[email-relay] Waiting for RabbitMQ... ({i + 1}/{max_retries}) - {exc}",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError("RabbitMQ not available after retries")


def require_env() -> None:
    missing = []
    if not RABBITMQ_URL:
        missing.append("RABBITMQ_URL")
    if not OUTSYSTEM_ENDPOINT:
        missing.append("OUTSYSTEM_ENDPOINT")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def validate_payload(obj: Any) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "Payload must be a JSON object"

    required = ["emailAddress", "emailSubject", "emailBody"]
    for key in required:
        if key not in obj:
            return False, f"Missing required field: {key}"
        if not isinstance(obj[key], str):
            return False, f"Field {key} must be string"
        if key != "emailBody" and not obj[key].strip():
            return False, f"Field {key} cannot be empty"

    return True, ""


def post_to_outsystems(payload: Dict[str, str]) -> Tuple[bool, int, str]:
    try:
        response = requests.post(
            OUTSYSTEM_ENDPOINT,
            json=payload,
            timeout=OUTSYSTEM_TIMEOUT_SECONDS,
        )
        if 200 <= response.status_code < 300:
            return True, response.status_code, "ok"

        if 400 <= response.status_code < 500:
            return False, response.status_code, f"permanent http error: {response.text}"

        return False, response.status_code, f"transient http error: {response.text}"
    except requests.RequestException as exc:
        return False, 0, f"network error: {exc}"


class EmailRelayConsumer:
    def __init__(self) -> None:
        self.connection = None
        self.channel = None

    def connect(self) -> None:
        params = pika.URLParameters(RABBITMQ_URL)
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.channel.basic_qos(prefetch_count=1)
        self.channel.queue_declare(queue=QUEUE_NAME, passive=True)
        print(f"[email-relay] Connected. Consuming queue='{QUEUE_NAME}'", flush=True)

    def requeue_with_retry_header(self, payload_bytes: bytes, retry_count: int) -> None:
        properties = pika.BasicProperties(
            delivery_mode=2,
            headers={"x-relay-retry-count": retry_count},
        )
        self.channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=payload_bytes, properties=properties)

    def on_message(self, ch, method, properties, body) -> None:
        retry_count = 0
        headers = getattr(properties, "headers", None) or {}
        if isinstance(headers, dict):
            retry_count = int(headers.get("x-relay-retry-count", 0))

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            print(f"[email-relay] Invalid JSON. Dropping message. error={exc}", flush=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        ok, reason = validate_payload(payload)
        if not ok:
            print(f"[email-relay] Invalid payload schema. Dropping message. reason={reason}", flush=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        outbound = {
            "emailAddress": payload["emailAddress"],
            "emailSubject": payload["emailSubject"],
            "emailBody": payload["emailBody"],
        }

        if RELAY_LOG_PAYLOAD:
            print(f"[email-relay] Sending payload={outbound}", flush=True)
        else:
            print(
                f"[email-relay] Sending emailAddress={outbound['emailAddress']} "
                f"subject_len={len(outbound['emailSubject'])} body_len={len(outbound['emailBody'])}",
                flush=True,
            )

        success, status_code, detail = post_to_outsystems(outbound)
        if success:
            print(f"[email-relay] Delivered successfully. status={status_code}", flush=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        if 400 <= status_code < 500:
            print(f"[email-relay] Permanent failure. Dropping message. detail={detail}", flush=True)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        if retry_count >= RELAY_MAX_RETRIES:
            print(
                f"[email-relay] Max retries reached ({RELAY_MAX_RETRIES}). Dropping message. detail={detail}",
                flush=True,
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        next_retry = retry_count + 1
        backoff = RELAY_BACKOFF_SECONDS * (2 ** retry_count)
        print(
            f"[email-relay] Transient failure. retry={next_retry}/{RELAY_MAX_RETRIES} "
            f"backoff={backoff}s detail={detail}",
            flush=True,
        )
        time.sleep(backoff)
        self.requeue_with_retry_header(body, next_retry)
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def run(self) -> None:
        while True:
            try:
                self.connect()
                self.channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self.on_message, auto_ack=False)
                self.channel.start_consuming()
            except Exception as exc:
                print(f"[email-relay] Consumer error, reconnecting in 3s: {exc}", flush=True)
                time.sleep(3)
            finally:
                try:
                    if self.channel and self.channel.is_open:
                        self.channel.close()
                except Exception:
                    pass
                try:
                    if self.connection and self.connection.is_open:
                        self.connection.close()
                except Exception:
                    pass


def main() -> None:
    require_env()
    wait_for_rabbitmq()
    consumer = EmailRelayConsumer()
    consumer.run()


if __name__ == "__main__":
    main()
