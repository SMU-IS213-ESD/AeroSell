## Item Delivery Composite Service

The Item Delivery service runs the scheduled delivery workflow.
It runs on port `8103` and coordinates order checks, weather validation, drone dispatch, and downstream notifications.

### Contents

- `docker-compose.yml` — local service definition.
- `Dockerfile` — build instructions for the APIFlask app.
- `app/run.py` — scheduler, RabbitMQ consumers, and delivery orchestration.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check health:

```bash
curl -i http://localhost:8103/health
```

### Behavior

- Fetches confirmed orders that are ready for delivery.
- Re-checks weather before dispatching a drone.
- Moves orders to `DELAYED`, `READY_FOR_DELIVERY`, `IN_DELIVERY`, or `COMPLETED` as the workflow progresses.
- Consumes `drone_events` and `flight_update` queues to react to drone updates.

### Configuration

- The service expects `RABBITMQ_URL`.
- It reaches the atomic services through Kong-backed URLs under `http://kong:8000`.

### Notes

- The only public endpoint is `GET /health`.
- Delivery notifications are published through RabbitMQ when the workflow changes state.