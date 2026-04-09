from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, DateTime
from flask import request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from typing import List

# Schemas for API documentation
class UserOut(Schema):
	id = Integer()
	name = String()
	email = String()
	role = String()
	gender = String()
	phone = String()
	created_at = DateTime()

app = APIFlask(
	__name__,
	title="User Service",
	version="1.0.0"
)

db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

_created_tables = False


@app.get("/db-check")
@app.doc(tags=["Health Check"], summary="Database connectivity check")
def db_check():
	"""Verify database is reachable"""
	try:
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		if not ok:
			abort(500, "Database unreachable")
		return {"status": "ok"}
	except Exception:
		app.logger.exception("Database connectivity check failed")
		abort(500, "Database error")


class User(db.Model):
	__tablename__ = "users"
	id = db.Column(db.Integer, primary_key=True)
	role = db.Column(db.String(64), nullable=True)
	password_hash = db.Column(db.String(256), nullable=False)
	email = db.Column(db.String(256), unique=True, nullable=False)
	name = db.Column(db.String(128), nullable=False)
	gender = db.Column(db.String(32), nullable=True)
	phone = db.Column(db.String(32), nullable=True)
	created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

	def to_dict(self):
		return {
			"id": self.id,
			"name": self.name,
			"email": self.email,
			"role": self.role,
			"gender": self.gender,
			"phone": self.phone,
			"created_at": self.created_at.isoformat(),
		}


	def set_password(self, password: str):
		self.password_hash = generate_password_hash(password)

	def check_password(self, password: str) -> bool:
		return check_password_hash(self.password_hash, password)


@app.before_request
def ensure_tables():
	"""Create DB tables before the server starts. Safe to call repeatedly."""
	global _created_tables
	if _created_tables:
		return
	try:
		db.create_all()
		_created_tables = True
	except Exception:
		app.logger.exception("Failed creating database tables")


@app.post("/register")
@app.doc(tags=["Authentication"], summary="Register new user")
@app.output(UserOut, status_code=201)
def create_user():
	data = request.get_json(force=True, silent=True)
	if not data:
		abort(400, "missing JSON body")
	name = data.get("name")
	email = data.get("email")
	password = data.get("password")
	role = data.get("role", "customer")
	gender = data.get("gender")
	phone = data.get("phone")
	if not name or not email or not password:
		abort(400, "name, email and password are required")

	user = User(name=name, email=email, role=role, gender=gender, phone=phone)
	user.set_password(password)
	try:
		db.session.add(user)
		db.session.commit()
	except IntegrityError:
		db.session.rollback()
		abort(409, "email already exists")
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed creating user")
		abort(500, "internal error")
	return user


@app.get("/<int:user_id>")
@app.doc(tags=["Users"], summary="Get user by ID")
@app.output(UserOut)
def get_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		abort(404, "not found")
	return user


@app.put("/<int:user_id>")
@app.doc(tags=["Users"], summary="Update user")
@app.output(UserOut)
def update_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		abort(404, "not found")
	data = request.get_json(force=True, silent=True) or {}
	name = data.get("name")
	email = data.get("email")
	password = data.get("password")
	role = data.get("role")
	gender = data.get("gender")
	phone = data.get("phone")
	if name:
		user.name = name
	if email:
		user.email = email
	if role is not None:
		user.role = role
	if gender is not None:
		user.gender = gender
	if phone is not None:
		user.phone = phone
	if password:
		user.set_password(password)
	try:
		db.session.commit()
	except IntegrityError:
		db.session.rollback()
		abort(409, "email already exists")
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed updating user")
		abort(500, "internal error")
	return user


@app.delete("/<int:user_id>")
@app.doc(tags=["Users"], summary="Delete user")
def delete_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		abort(404, "not found")
	try:
		db.session.delete(user)
		db.session.commit()
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed deleting user")
		abort(500, "internal error")
	return "", 204


@app.post("/login")
@app.doc(tags=["Authentication"], summary="Login user")
@app.output(UserOut)
def validate_user():
	data = request.get_json(force=True, silent=True)
	if not data:
		abort(400, "missing JSON body")
	email = data.get("email")
	password = data.get("password")
	if not email or not password:
		abort(400, "email and password are required")

	user = User.query.filter_by(email=email).first()
	if not user:
		abort(401, "invalid credentials")

	if not user.check_password(password):
		abort(401, "invalid credentials")

	return user


if __name__ == "__main__":
	app.run(host="0.0.0.0", port=8008)

