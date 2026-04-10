## Operations Support Service

The Operations Support Service manages staff records and assignment workflows.
It runs on port `8005` and uses `DATABASE_URL`.

### Contents

- `docker-compose.yml` — local service definition.
- `Dockerfile` — build instructions for the APIFlask app.
- `app/run.py` — staff, assignment, and health endpoints.
- `requirements.txt` — Python dependencies.

### Quickstart

1. Build and start the stack:

```bash
docker compose up --build
```

2. Check DB connectivity:

```bash
curl -i http://localhost:8005/db-check
```

### Key Endpoints

- `POST /operations-support/assign`
- `POST /operations-support/assignment`
- `GET /operations-support/assignment`
- `GET /operations-support/assignment/<int:assignment_id>`
- `PUT /operations-support/assignment/<int:assignment_id>`
- `DELETE /operations-support/assignment/<int:assignment_id>`
- `POST /operations-support/staff`
- `GET /operations-support/staff`
- `GET /operations-support/staff/available`
- `GET /operations-support/staff/<int:staff_id>`
- `PUT /operations-support/staff/<int:staff_id>`
- `DELETE /operations-support/staff/<int:staff_id>`

### Notes

- The service is used to assign staff to drone anomalies and other operational tasks.