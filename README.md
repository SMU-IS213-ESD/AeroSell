# AeroSell

<div align="center">
	<img src="frontend/Aerosell_User/public/favicon.svg" alt="AeroSell logo" width="88" />
	<p>Event-driven drone delivery platform built with atomic and composite microservices.</p>
</div>

## Overview

AeroSell is a microservices-based drone delivery system that combines synchronous orchestration (REST via Kong) with asynchronous workflows (RabbitMQ).

The platform supports end-to-end delivery operations:

- Customer booking and payment orchestration
- Route and feasibility checks with flight planning
- Scheduled delivery execution with weather re-checks
- Drone anomaly detection and repair assignment orchestration
- Insurance claim submission with document evidence
- Notification relay to external channels

## Project Structure

```text
AeroSell/
├─ backend/
│  ├─ docker-compose.yml
│  ├─ db/init/
│  │  ├─ init-dbs.sql
│  │  └─ amqp_setup.py
│  ├─ kong/config.yml
│  └─ services/
│     ├─ atomic/
│     ├─ composite/
│     └─ third-party/
└─ frontend/
   ├─ Aerosell_Terminal/
   └─ Aerosell_User/

```

## Backend Architecture

### Core Infrastructure

- Kong API Gateway for service routing
- PostgreSQL for service data stores
- Redis (weather-service caching)
- RabbitMQ for event-driven workflows

### Atomic Services

- document
- drone
- flight-planning
- operations-support
- order
- payment
- user
- weather
- email-relay

### Composite Services

- book-drone
- item-delivery
- insurance-claim
- anomaly-manager

### Third-Party Simulators

- insurance
- stripe-cli (webhook forwarding)
- drone-sim

## Frontend Applications

### Aerosell_Terminal

Terminal-side workflow UI for:

- Booking input
- Route estimate and validation handoff
- Stripe payment flow
- Booking confirmation

### Aerosell_User

Customer-facing UI for:

- Authentication
- Delivery status tracking
- Insurance claim submission

## Key Scenarios Implemented

1. Customer books a drone delivery
2. Delivery execution with weather re-check and status transitions
3. Drone anomaly detection with operations escalation and retry workflow
4. Insurance claim request with evidence upload and referral handling

> [!NOTE]
> Scenario details are implemented across multiple composite and atomic services. Service-level README files under backend/services provide endpoint-level references.

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Node.js 20+ and npm (for frontend local development)
- Valid environment variables for Stripe, OpenWeather, and RabbitMQ

### 1) Start backend stack

From backend:

```bash
docker compose up -d --build
```

### 2) Verify gateway and services

- Kong proxy: http://localhost:8880
- Kong admin API: http://localhost:8881
- Kong manager: http://localhost:8882

### 3) Run frontend apps

From frontend/Aerosell_Terminal:

```bash
npm install
npm run dev
```

From frontend/Aerosell_User:

```bash
npm install
npm run dev
```

## API Docs

The backend API specification is available in [swagger.json](swagger.json). Use it as the source OpenAPI document for Swagger-compatible tools and local API documentation.

## Configuration

Important environment variables include:

- `RABBITMQ_URL`
- `STRIPE_API_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `OPENWEATHER_API_KEY`
- `OUTSYSTEM_ENDPOINT`
- per-service `DATABASE_URL`

The main backend wiring is defined in:

- backend/docker-compose.yml
- backend/kong/config.yml
- backend/db/init/amqp_setup.py

> [!IMPORTANT]
> RabbitMQ queue arguments are immutable once a queue exists. If you change DLX/TTL arguments, delete and recreate the affected queues before retesting.

## Useful Entry Points

- Backend compose: backend/docker-compose.yml
- API gateway routes: backend/kong/config.yml
- AMQP bootstrap: backend/db/init/amqp_setup.py
- Drone simulator: backend/services/atomic/drone/sim/simulate_drone.py
- One-shot anomaly trigger helper: backend/services/atomic/drone/sim/drone_error.py

## Troubleshooting

- If delayed repair retries do not loop, recreate `repair_queue` and `repair_dlx_queue` and rerun AMQP setup.
- If assignment selection appears stuck on one staff, check operations-support startup logic and persisted DB state.
- If payment does not finalize booking, verify Stripe webhook forwarding path to book-drone webhook endpoint.
- If weather checks fail unexpectedly, verify `OPENWEATHER_API_KEY` and weather service health.
