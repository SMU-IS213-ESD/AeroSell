## Payment Microservice

Overview
-
This atomic microservice records payments for the Smart Drone Delivery
platform and integrates with Stripe to create PaymentIntents and process
payment webhooks. It exposes a small REST API for creating payments, querying
their status, and updating payment records.

Requirements
-
- Python 3.10+ (container uses python:3-slim)
- `requirements.txt` in this folder lists runtime deps (Flask, Flask-SQLAlchemy,
	psycopg2-binary, stripe)

Configuration
-
- `DATABASE_URL` environment variable (Postgres URI) — the service reads this at
	startup and uses SQLAlchemy to connect.
- `STRIPE_API_KEY` — secret key (sk_...) used to create PaymentIntents. If not
	set the service will return an error when creating payments.
- `STRIPE_WEBHOOK_SECRET` — webhook signing secret (whsec_...) used to verify
	incoming Stripe webhook requests.

.env file
-
- You can store the service environment variables in a gitignored `.env` file
  (recommended for local development). Example `.env` (DO NOT commit this file):

```
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

- The `.env` will be loaded into the service when running with Docker Compose, reference
  it with the `env_file` option in `docker-compose.yml`. Ensure `.env` is listed in your `.gitignore`.

Database
-
Tables are created automatically on first request. If you add/remove model
columns you must update the database schema (recommended: use Alembic migrations
in production). Quick local fix examples are in the source README.

HTTP API
-
- `GET /db-check` — returns `true` when DB reachable.
- `POST /payments` — create payment
	- Body (required): `order_id` (int), `amount` (number)
	- Optional: `currency` (defaults to `USD`), `method` (e.g. `card`)
	- Behavior: creates a `Payment` row with status `pending` and attempts to
		create a Stripe PaymentIntent. If `STRIPE_API_KEY` is set the endpoint
		returns `201` with `{"client_secret": ..., "payment_id": ..., "transaction_id": ...}`.
		If `STRIPE_API_KEY` is not set the endpoint returns `502` with
		`{"error": "Stripe error"}`.
- `POST /payments/webhook` — Stripe webhook endpoint
	- Verifies the Stripe signature using `STRIPE_WEBHOOK_SECRET` and updates a
		`Payment` row's `status` to `succeeded` or `failed` on the corresponding
		`payment_intent` events.
- `GET /payments` — list payments (supports `page`, `per_page`, and `order_id` filter)
- `GET /payments/<id>` — fetch a single payment
- `PUT /payments/<id>/status` — manually update a payment's `status`

Examples
-
Create payment (server will create a Stripe PaymentIntent when configured):
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"order_id":123,"amount":19.99,"currency":"USD","method":"card"}' \
  http://localhost:8007/payments
```

If Stripe is configured response (201):
```
{"client_secret":"...","payment_id":1,"transaction_id":"pi_..."}
```

Trigger test webhooks locally with the Stripe CLI (forward events to the
running container):
```bash
stripe listen --forward-to http://localhost:8007/payments/webhook
stripe trigger payment_intent.succeeded
```

Notes
-
- This service uses Stripe PaymentIntents and webhooks for reliable status
	updates — the client is expected to confirm the PaymentIntent using
	Stripe.js / mobile SDK with the returned `client_secret`.
- The API never stores card numbers; card handling is done by Stripe.
- For schema changes in development you can either run `db.drop_all()` /
	`db.create_all()` or execute `ALTER TABLE` statements to add missing columns.

Running
-
This service is run in Docker via the repository's `docker-compose.yml`. From
the `backend` folder:
```bash
docker compose up -d --build payment
```

File: backend/services/atomic/payment/app/run.py
