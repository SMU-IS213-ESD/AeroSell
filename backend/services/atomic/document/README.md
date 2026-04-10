## Document Service

The Document Service stores uploaded evidence files and their metadata for an order.
It runs on port `8001` and uses `DATABASE_URL` for its database connection.

### Contents

- `docker-compose.yml` — defines the `web` and `db` services.
- `Dockerfile` — build instructions for the APIFlask application.
- `app/run.py` — API entry point with upload and lookup endpoints.
- `app/models.py` — document metadata model.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check DB connectivity:

```bash
curl -i http://localhost:8001/db-check
```

3. Upload a document:

```bash
curl -F "file=@evidence.pdf" -F "order_id=123" http://localhost:8001/upload
```

4. List documents for an order:

```bash
curl http://localhost:8001/documents/123
```

### Configuration

- The application reads the database URL from the `DATABASE_URL` environment variable.
- Uploaded files are saved under `app/uploads`.

### Notes

- The service is used for insurance claim evidence and order attachment uploads.
- See `app/run.py` for the `/upload`, `/documents/<order_id>`, and `/db-check` implementations.