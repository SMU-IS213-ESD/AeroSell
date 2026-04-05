#!/usr/bin/env python3
import os
from os import environ
import amqp_lib
import json

rabbit_host = environ.get("rabbit_host") or "localhost"
rabbit_port = environ.get("rabbit_port") or 5672
exchange_name = environ.get("exchange_name") or "order_topic"
exchange_type = environ.get("exchange_type") or "topic"
queue_name = environ.get("queue_name") or "Error"


def callback(channel, method, properties, body):
    # required signature for the callback; no return
    try:
        error = json.loads(body)
        print(f"Error message (JSON): {error}")
    except Exception as e:
        print(f"Unable to parse JSON: {e=}")
        print(f"Error message: {body}")
    print()


if __name__ == "__main__":
    print(f"This is {os.path.basename(__file__)} - amqp consumer...")
    try:
        amqp_lib.start_consuming(
            rabbit_host, rabbit_port, exchange_name, exchange_type, queue_name, callback
        )
    except Exception as exception:
        print(f"  Unable to connect to RabbitMQ.\n     {exception=}\n")
