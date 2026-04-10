## Drone Service

The Drone Service manages drone records and telemetry for AeroSell.
It runs on port `8002` and uses `DATABASE_URL` plus `RABBITMQ_URL`.

### Contents

- `docker-compose.yml` — local service definition.
- `Dockerfile` — build instructions for the APIFlask app.
- `app/run.py` — service entry point with telemetry consumers and anomaly publishing.
- `sim/` — drone simulator helpers used by the local stack.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check DB connectivity:

```bash
curl -i http://localhost:8002/db-check
```

### Key Endpoints

- `GET /db-check`
- `GET /drones`
- `GET /drones/<int:drone_id>`
- `GET /drones/available`
- `POST /drones`
- `POST /drones/activate/<int:drone_id>`
- `PATCH /drones/<int:drone_id>`
- `DELETE /drones/<int:drone_id>`

### Notes

- The service consumes telemetry and flight update messages from RabbitMQ.
- When a telemetry anomaly is detected it publishes a `drone.anomaly` event for downstream services.