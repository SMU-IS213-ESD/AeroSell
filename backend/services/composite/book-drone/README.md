## Book-Drone Composite Service

The Book-Drone service orchestrates the end-to-end booking flow.
It runs on port `8101` and coordinates booking validation, payment intent creation, webhook handling, and order confirmation.

### Contents

- `docker-compose.yml` — local service definition.
- `Dockerfile` — build instructions for the APIFlask app.
- `app/run.py` — booking orchestration, Stripe integration, and gateway-backed service calls.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check health:

```bash
curl -i http://localhost:8101/health
```

### Key Endpoints

- `GET /health`
- `POST /book`
- `POST /validate`
- `GET /available-drones`
- `POST /validate-route`
- `POST /status`
- `POST /confirm`
- `POST /webhook`
- `POST /create-payment-intent`
- `GET /payments/<int:payment_id>`

### Configuration

- The service expects `RABBITMQ_URL`, `STRIPE_API_KEY`, and `STRIPE_WEBHOOK_SECRET`.
- It reaches the atomic services through Kong-backed URLs under `http://kong:8000`.

### Notes

- `POST /create-payment-intent` returns `success`, `client_secret`, `payment_id`, and `transaction_id`.
- The service is the main orchestration layer for the terminal frontend.