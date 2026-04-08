## Template of Microservices

A Docker Compose template for our microservices. It includes a Postgres 15 service, and the Python `web` service communicates with the database using SQLAlchemy.

### Contents

- `docker-compose.yml` — defines `web` and `db` (Postgres 15) services.
- `Dockerfile` — build instructions for the `web` image.
- `app/run.py` — minimal Flask app with a `/db-check` health endpoint that verifies DB communication via SQLAlchemy.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check DB connectivity:

```bash
curl -i http://localhost:8000/db-check
```

Expect HTTP 200 and a JSON `true` when the Postgres service is ready.

### Configuration

- The application reads the database URL from the `DATABASE_URL` environment variable (set for the `web` service in `docker-compose.yml`). Example value:

```
postgresql://user:password@db:5432/postgres
```

### Notes

- See `app/run.py` for the SQLAlchemy usage and the `/db-check` implementation.