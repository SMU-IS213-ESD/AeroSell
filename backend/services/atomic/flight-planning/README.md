# Flight Planning Service

## Overview

The Flight Planning Service is responsible for determining whether a drone delivery route is safe and operationally feasible. Given a pickup and dropoff location, it checks the straight-line path for restricted airspace (no-fly zones) and enforces a maximum delivery range. It also estimates the expected flight distance and duration, and keeps a full history of every validation it performs.

This service is stateless by design — each validation request is self-contained. It does not coordinate drones, place orders, or emit events. It simply answers the question: **can a drone fly this route?**

It is called by the **Book Drone Composite Service** (to check feasibility before confirming a booking) and the **Item Delivery Composite Service** (to re-validate routes when rescheduling is needed).

## Responsibilities

- Validate a delivery route (pickup → dropoff coordinates) for feasibility
- Check that the route does not pass through restricted no-fly zones
- Estimate straight-line distance and flight duration
- Support rescheduling by re-validating routes on demand
- Persist a full validation history per order

## Tech Stack

- **Python 3.11** + **Flask**
- **PostgreSQL 15** via SQLAlchemy (table auto-created on startup)
- **Docker** + **docker-compose**

## Project Structure

```
flight-planning-microservices/
├── run.py                              # Entry point
├── app/
│   ├── __init__.py                     # App factory
│   ├── models/
│   │   └── route_validation.py         # SQLAlchemy model
│   ├── controllers/
│   │   └── route_controller.py         # Request parsing & response formatting
│   ├── services/
│   │   ├── route_validation_service.py # Core business logic
│   │   ├── no_fly_zone_service.py      # No-fly zone bounding-box checks
│   │   └── distance_service.py         # Haversine distance & duration estimate
│   ├── routes/
│   │   └── route_routes.py             # Flask Blueprint
│   └── middleware/
│       └── error_handler.py            # Global JSON error handlers
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Quickstart

```bash
cp .env.example .env
docker compose up --build
```

The service will be available at `http://localhost:8004`.

## API Endpoints

### `POST /routes/validate`

Validate a new delivery route. Creates and persists a validation record.

**Request body**
```json
{
  "orderId": "order-123",
  "pickup":  { "lat": 1.30, "lon": 103.85 },
  "dropoff": { "lat": 1.32, "lon": 103.87 }
}
```

**Response `201`**
```json
{
  "orderId": "order-123",
  "feasible": true,
  "reason": null,
  "estimatedDistanceKm": 2.9842,
  "estimatedDurationMin": 2.98,
  "checkedAt": "2026-03-23T10:00:00.000000Z",
  "pickup":  { "lat": 1.30, "lon": 103.85 },
  "dropoff": { "lat": 1.32, "lon": 103.87 }
}
```

---

### `POST /routes/revalidate`

Re-check a previously validated route using the same coordinates. Useful for rescheduling decisions.

**Request body**
```json
{
  "orderId": "order-123"
}
```

Returns `201` with the same shape as `/routes/validate`, or `404` if no prior record exists.

---

### `GET /routes/:orderId`

Retrieve the full validation history for an order, newest first.

**Response `200`** — array of validation records in the same shape as above.

---

### `GET /health`

Liveness probe.

**Response `200`**
```json
{ "status": "ok" }
```

## No-Fly Zones

Routes are currently checked against a hardcoded list of bounding boxes in [`app/services/no_fly_zone_service.py`](app/services/no_fly_zone_service.py):

| Zone | Area |
|---|---|
| Changi Airport Exclusion Zone | 1.34–1.37 N, 103.96–104.01 E |
| Paya Lebar Air Base | 1.36–1.38 N, 103.90–103.92 E |
| Tengah Air Base | 1.37–1.39 N, 103.70–103.73 E |
| Seletar Airport Zone | 1.41–1.43 N, 103.86–103.89 E |
| Central Water Catchment Reserve | 1.37–1.40 N, 103.79–103.82 E |

A route is rejected if any sampled point along the straight-line path falls within a zone boundary.

## Feasibility Rules

| Rule | Limit |
|---|---|
| Maximum range | 50 km |
| No-fly zone intersection | Route rejected with zone name in `reason` |

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `user` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `password` | PostgreSQL password |
| `POSTGRES_DB` | `flight_planning` | Database name |
| `DATABASE_URL` | *(constructed from above)* | Full SQLAlchemy connection string |
| `PORT` | `8004` | Port the service listens on |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |

## Testing the Service

Make sure the stack is running before sending any requests:

```bash
docker compose up --build
```

---

### Using Postman

**1. Health check**

| Field | Value |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8004/health` |

Expected `200`: `{"status": "ok"}`

---

**2. Validate a feasible route**

| Field | Value |
|---|---|
| Method | `POST` |
| URL | `http://localhost:8004/routes/validate` |
| Body | raw / JSON (see below) |

```json
{
  "orderId": "order-001",
  "pickup":  { "lat": 1.30, "lon": 103.85 },
  "dropoff": { "lat": 1.32, "lon": 103.87 }
}
```

Expected `201`: `"feasible": true`, `"reason": null`

---

**3. Validate a route that hits a no-fly zone**

Same method/URL as above, different body:

```json
{
  "orderId": "order-002",
  "pickup":  { "lat": 1.30, "lon": 103.85 },
  "dropoff": { "lat": 1.36, "lon": 103.98 }
}
```

Expected `201`: `"feasible": false`, reason mentions `Changi Airport Exclusion Zone`

---

**4. Revalidate an existing order**

| Field | Value |
|---|---|
| Method | `POST` |
| URL | `http://localhost:8004/routes/revalidate` |
| Body | raw / JSON (see below) |

```json
{
  "orderId": "order-001"
}
```

Expected `201`: new validation record using the same coordinates as the original.

---

**5. Get validation history**

| Field | Value |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8004/routes/order-001` |

Expected `200`: array of all validation records for `order-001`, newest first.

---

### Using curl

```bash
# Health check
curl http://localhost:8004/health

# Feasible route
curl -s -X POST http://localhost:8004/routes/validate \
  -H "Content-Type: application/json" \
  -d '{"orderId":"order-001","pickup":{"lat":1.30,"lon":103.85},"dropoff":{"lat":1.32,"lon":103.87}}'

# No-fly zone violation
curl -s -X POST http://localhost:8004/routes/validate \
  -H "Content-Type: application/json" \
  -d '{"orderId":"order-002","pickup":{"lat":1.30,"lon":103.85},"dropoff":{"lat":1.36,"lon":103.98}}'

# Revalidate
curl -s -X POST http://localhost:8004/routes/revalidate \
  -H "Content-Type: application/json" \
  -d '{"orderId":"order-001"}'

# History
curl -s http://localhost:8004/routes/order-001
```

> On Windows PowerShell use `curl.exe` instead of `curl` to avoid the built-in alias.
