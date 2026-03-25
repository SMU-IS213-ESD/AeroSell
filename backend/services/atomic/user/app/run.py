from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from flask import request, abort

app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

_created_tables = False


@app.route("/db-check", methods=["GET"])
def db_check():
	"""Return JSON true if a simple DB query succeeds, otherwise false.

	Response body is a bare boolean JSON value (true/false) and status
	code is 200 on success, 500 on failure.
	"""
	try:
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		return jsonify(ok), (200 if ok else 500)
	except Exception:
		app.logger.exception("Database connectivity check failed")
		return jsonify(False), 500


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


@app.route("/users", methods=["POST"])
def create_user():
	data = request.get_json(force=True, silent=True)
	if not data:
		return jsonify({"error": "missing JSON body"}), 400
	name = data.get("name")
	email = data.get("email")
	password = data.get("password")
	role = data.get("role", "customer")
	gender = data.get("gender")
	phone = data.get("phone")
	if not name or not email or not password:
		return jsonify({"error": "name, email and password are required"}), 400

	user = User(name=name, email=email, role=role, gender=gender, phone=phone)
	user.set_password(password)
	try:
		db.session.add(user)
		db.session.commit()
	except IntegrityError:
		db.session.rollback()
		return jsonify({"error": "email already exists"}), 409
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed creating user")
		return jsonify({"error": "internal error"}), 500
	return jsonify({"success": True, "message": "Account created successfully"}), 201


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		return jsonify({"error": "not found"}), 404
	out = user.to_dict()
	out.pop("password_hash", None)
	return jsonify(out), 200


@app.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		return jsonify({"error": "not found"}), 405
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
		return jsonify({"error": "email already exists"}), 409
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed updating user")
		return jsonify({"error": "internal error"}), 500
	out = user.to_dict()
	out.pop("password_hash", None)
	return jsonify(out), 200


@app.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id: int):
	user = User.query.get(user_id)
	if not user:
		return jsonify({"error": "not found"}), 404
	try:
		db.session.delete(user)
		db.session.commit()
	except Exception:
		db.session.rollback()
		app.logger.exception("Failed deleting user")
		return jsonify({"error": "internal error"}), 500
	return jsonify({"deleted": True}), 200


@app.route("/validate", methods=["POST"])
def validate_user():
	data = request.get_json(force=True, silent=True)
	if not data:
		return jsonify({"error": "missing JSON body"}), 400
	email = data.get("email")
	password = data.get("password")
	if not email or not password:
		return jsonify({"error": "email and password are required"}), 400

	user = User.query.filter_by(email=email).first()
	if not user:
		return jsonify({"error": "invalid credentials"}), 401

	if not user.check_password(password):
		return jsonify({"error": "invalid credentials"}), 401

	out = user.to_dict()
	out.pop("password_hash", None)
	return jsonify(out), 200


if __name__ == "__main__":
	app.run(host="0.0.0.0", port=8008)

