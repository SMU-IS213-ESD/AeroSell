## Backend services

Overview
-
This folder contains the backend microservices for the Smart Drone Delivery
platform (atomic and composite services). Services are run via Docker Compose
for local development; individual services are in `services/atomic` and
`services/composite`.

Prerequisites
-
- Docker & Docker Compose
- (Optional) Python 3.10+ for local script inspection

Configuration
-
- Each service reads configuration from environment variables. Common vars:
	- `DATABASE_URL` — SQLAlchemy-compatible DB URL (Postgres)
	- Service-specific env vars are documented in each service folder.

Run (development)
-
Start all backend services defined in `docker-compose.yml`:
```bash
docker compose up -d --build
```

Start a single service (example: user):
```bash
docker compose up -d --build user
```

Health & testing
-
- Many atomic services expose a lightweight DB health endpoint, e.g. `GET /db-check`.
- Use `docker compose logs <service>` to inspect startup errors.

Database schema
-
- Services may create tables automatically in development. For schema changes
	in persistent environments use a migration tool (Alembic) or run explicit
	`ALTER TABLE` statements. See each service README for migration notes.

Where to look
-
- Service source: `services/atomic/<service>/app/run.py`
- Service README files: `services/atomic/<service>/README.md`