## User Microservice

Overview
-
This atomic microservice manages customer accounts for the Smart Drone Delivery
platform. It exposes a small REST API for creating accounts, authenticating
users, and basic CRUD for user profiles. Passwords are stored hashed.

Requirements
-
- Python 3.10+ (container uses python:3-slim)
- `requirements.txt` in this folder lists runtime deps (Flask, Flask-SQLAlchemy,
	psycopg2-binary)

Configuration
-
- `DATABASE_URL` environment variable (Postgres URI) — the service reads this at
	startup and uses SQLAlchemy to connect.

Database
-
Tables are created automatically on first request. If you add/remove model
columns you must update the database schema (recommended: use Alembic migrations
in production). Quick local fix examples are in the source README.

HTTP API
-
- `GET /db-check` — returns `true` when DB reachable.
- `POST /users` — create user
	- Body (required): `name`, `email`, `password`
	- Optional: `role`, `gender`, `phone`
	- Response: `201` with `{"success": true, "message": "Account created successfully"}`
- `POST /validate` — login
	- Body: `email`, `password`
	- Response: `200` with user object (password not included) on success, `401` on failure
- `GET /users/<id>` — fetch user profile (no password returned)
- `PUT /users/<id>` — update profile (accepts `name`, `email`, `password`, `role`, `gender`, `phone`)
- `DELETE /users/<id>` — delete user

Examples
-
Create user (minimal):
```bash
curl -X POST -H "Content-Type: application/json" \
	-d '{"name":"Alice","email":"alice@example.com","password":"s3cret"}' \
	http://localhost:8008/users
```

Login:
```bash
curl -X POST -H "Content-Type: application/json" \
	-d '{"email":"alice@example.com","password":"s3cret"}' \
	http://localhost:8008/validate
```

Notes
-
- Passwords are hashed — the API never returns password hashes.
- For schema changes in development you can either run `db.drop_all()` /
	`db.create_all()` or execute `ALTER TABLE` statements to add missing columns.

Running
-
This service is run in Docker via the repository's `docker-compose.yml`. From
the `backend` folder:
```bash
docker compose up -d --build user
```

Contributing
-
Open a PR with tests and, for schema changes, include a migration or the SQL
required to upgrade existing databases.

File: backend/services/atomic/user/app/run.py

