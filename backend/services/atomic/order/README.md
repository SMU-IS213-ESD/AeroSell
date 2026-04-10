## Order Service

The Order Service stores delivery orders and tracks their status lifecycle.
It runs on port `8006` and uses `DATABASE_URL` plus `RABBITMQ_URL`.

### Contents

- `docker-compose.yml` — local service definition.
- `Dockerfile` — build instructions for the APIFlask app.
- `app/run.py` — order CRUD endpoints and RabbitMQ event handling.
- `app/order.sql` — legacy schema seed data.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check DB connectivity:

```bash
curl -i http://localhost:8006/db-check
```

### Key Endpoints

- `GET /db-check`
- `GET /orders`
- `POST /order`
- `GET /orders/<int:order_id>`
- `GET /orders/user/<string:user_id>`
- `GET /orders/drone/<int:drone_id>`
- `PATCH /orders/<int:order_id>/status`
- `GET /orders/by-timeslot`

### Notes

- The service publishes order status updates to RabbitMQ.
- It also consumes anomaly events to move affected orders through the recovery flow.