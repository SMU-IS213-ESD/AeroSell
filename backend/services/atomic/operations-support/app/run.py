
from apiflask import APIFlask, Schema, abort
from apiflask.fields import Integer, String, Float, Boolean, DateTime
from flask import request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os

app = APIFlask(__name__)
db_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# --- Schemas ---
class SupportStaffOut(Schema):
	id = Integer()
	name = String()
	email = String()
	is_available = Boolean()

class AssignmentOut(Schema):
	id = Integer()
	staff_id = Integer()
	drone_id = Integer()
	longitude = Float()
	latitude = Float()
	timestamp = DateTime()
	status = String()
	staff = SupportStaffOut()


# --- Models ---
class SupportStaff(db.Model):
	__tablename__ = 'support_staff'
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String(100), nullable=False)
	email = db.Column(db.String(100), nullable=False, unique=True)
	is_available = db.Column(db.Boolean, default=True, nullable=False)


	def json(self):
		return {
			'id': self.id,
			'name': self.name,
			'email': self.email,
			'is_available': self.is_available
		}


# Assignment model
import datetime as dt
class Assignment(db.Model):
	__tablename__ = 'assignments'
	id = db.Column(db.Integer, primary_key=True)
	staff_id = db.Column(db.Integer, db.ForeignKey('support_staff.id'), nullable=False)
	drone_id = db.Column(db.Integer, nullable=False)
	longitude = db.Column(db.Float, nullable=False)
	latitude = db.Column(db.Float, nullable=False)
	timestamp = db.Column(db.DateTime, default=dt.datetime.now(dt.UTC), nullable=False)
	status = db.Column(db.String(20), default="pending", nullable=False)  # 'pending' or 'done'

	staff = db.relationship('SupportStaff', backref='assignments')

	def json(self):
		return {
			'id': self.id,
			'staff_id': self.staff_id,
			'drone_id': self.drone_id,
			'longitude': self.longitude,
			'latitude': self.latitude,
			'timestamp': self.timestamp.isoformat(),
			'status': self.status,
			'staff': self.staff.json() if self.staff else None
		}



# --- Assignment Endpoint ---
@app.post("/operations-support/assign")
@app.output(AssignmentOut)
@app.doc(tags=["Assignment"])
def assign_support():
	"""Assign a support staff to a broken drone."""
	data = request.get_json(silent=True)
	required_fields = ["drone_id", "longitude", "latitude"]
	if not data or not all(field in data for field in required_fields):
		abort(400, "Missing required fields")

	staff = SupportStaff.query.filter_by(is_available=True).first()
	if not staff:
		abort(503, "No available support staff")

	staff.is_available = False
	assignment = Assignment(
		staff_id=staff.id,
		drone_id=data["drone_id"],
		longitude=data["longitude"],
		latitude=data["latitude"],
		status="pending"
	)
	db.session.add(assignment)
	db.session.commit()
	return assignment


# --- Update Assignment Status Endpoint ---
@app.post("/operations-support/assignment/<int:assignment_id>/complete")
@app.output(AssignmentOut)
@app.doc(tags=["Assignment"])
def complete_assignment(assignment_id):
	"""Mark an assignment as done and make the staff available again."""
	assignment = Assignment.query.get(assignment_id)
	if not assignment:
		abort(404, "Assignment not found")
	if assignment.status == "done":
		return assignment
	assignment.status = "done"
	if assignment.staff:
		assignment.staff.is_available = True
	db.session.commit()
	return assignment


# --- Basic CRUD Endpoints for Assignment ---

# Create a new assignment (manual, not auto-assign)
@app.post("/operations-support/assignment")
@app.output(AssignmentOut, status_code=201)
@app.doc(tags=["Assignment"])
def create_assignment():
	data = request.get_json(silent=True)
	required_fields = ["staff_id", "drone_id", "longitude", "latitude"]
	if not data or not all(field in data for field in required_fields):
		abort(400, "Missing required fields")
	staff = SupportStaff.query.get(data["staff_id"])
	if not staff:
		abort(404, "Staff not found")
	assignment = Assignment(
		staff_id=data["staff_id"],
		drone_id=data["drone_id"],
		longitude=data["longitude"],
		latitude=data["latitude"],
		status=data.get("status", "pending")
	)
	db.session.add(assignment)
	db.session.commit()
	return assignment


# Get all assignments
from typing import List
@app.get("/operations-support/assignment")
@app.output(List[AssignmentOut])
@app.doc(tags=["Assignment"])
def get_assignments():
	assignments = Assignment.query.all()
	return assignments


# Get a single assignment by ID
@app.get("/operations-support/assignment/<int:assignment_id>")
@app.output(AssignmentOut)
@app.doc(tags=["Assignment"])
def get_assignment(assignment_id):
	assignment = Assignment.query.get(assignment_id)
	if not assignment:
		abort(404, "Assignment not found")
	return assignment


# Update an assignment by ID
@app.put("/operations-support/assignment/<int:assignment_id>")
@app.output(AssignmentOut)
@app.doc(tags=["Assignment"])
def update_assignment(assignment_id):
	assignment = Assignment.query.get(assignment_id)
	if not assignment:
		abort(404, "Assignment not found")
	data = request.get_json(silent=True)
	for field in ["staff_id", "drone_id", "longitude", "latitude", "status"]:
		if field in data:
			setattr(assignment, field, data[field])
	db.session.commit()
	return assignment


# Delete an assignment by ID
@app.delete("/operations-support/assignment/<int:assignment_id>")
@app.doc(tags=["Assignment"])
def delete_assignment(assignment_id):
	assignment = Assignment.query.get(assignment_id)
	if not assignment:
		abort(404, "Assignment not found")
	db.session.delete(assignment)
	db.session.commit()
	return {"message": "Assignment deleted"}



# --- Basic CRUD Endpoints for SupportStaff ---

# Create a new staff member
@app.post("/operations-support/staff")
@app.output(SupportStaffOut, status_code=201)
@app.doc(tags=["SupportStaff"])
def create_staff():
	data = request.get_json(silent=True)
	if not data or "name" not in data or "email" not in data:
		abort(400, "Missing required fields: name, email")
	staff = SupportStaff(name=data["name"], email=data["email"], is_available=data.get("is_available", True))
	db.session.add(staff)
	db.session.commit()
	return staff


# Get all staff
@app.get("/operations-support/staff")
@app.output(List[SupportStaffOut])
@app.doc(tags=["SupportStaff"])
def get_staff():
	staff_list = SupportStaff.query.all()
	return staff_list


# Get a single staff member by ID
@app.get("/operations-support/staff/<int:staff_id>")
@app.output(SupportStaffOut)
@app.doc(tags=["SupportStaff"])
def get_staff_by_id(staff_id):
	staff = SupportStaff.query.get(staff_id)
	if not staff:
		abort(404, "Staff not found")
	return staff

@app.put("/operations-support/staff/<int:staff_id>")
@app.output(SupportStaffOut)
@app.doc(tags=["SupportStaff"])
def update_staff(staff_id):
	staff = SupportStaff.query.get(staff_id)
	if not staff:
		return jsonify({"error": "Staff not found"}), 404
	data = request.get_json(silent=True)
	for field in ["name", "email", "is_available"]:
		if field in data:
			setattr(staff, field, data[field])
	db.session.commit()
	return jsonify({"staff": staff.json()}), 200

# Delete a staff member by ID
@app.route("/operations-support/staff/<int:staff_id>", methods=["DELETE"])
def delete_staff(staff_id):
	staff = SupportStaff.query.get(staff_id)
	if not staff:
		return jsonify({"error": "Staff not found"}), 404
	db.session.delete(staff)
	db.session.commit()
	return jsonify({"message": "Staff deleted"}), 200

# Get only available staff
@app.route("/operations-support/staff/available", methods=["GET"])
def get_available_staff():
	staff_list = SupportStaff.query.filter_by(is_available=True).all()
	return jsonify([s.json() for s in staff_list]), 200

@app.route("/db-check", methods=["GET"])
def db_check():
	"""Return JSON true if a simple DB query succeeds, otherwise false.

	Response body is a bare boolean JSON value (true/false) and status
	code is 200 on success, 500 on failure.
	"""
	try:
		# Lightweight check: run a simple SELECT 1
		result = db.session.execute(text("SELECT 1")).scalar()
		ok = bool(result)
		return jsonify(ok), (200 if ok else 500)
	except Exception:
		app.logger.exception("Database connectivity check failed")
		return jsonify(False), 500


if __name__ == "__main__":
	# Optional: create tables if not exist (for dev/demo)
	with app.app_context():
		# Create tables
		db.create_all()
		# Insert initial support staff if table is empty
		if SupportStaff.query.count() == 0:
			staff_list = [
				SupportStaff(name="Alice", email="alice@operations-support.com"),
				SupportStaff(name="Bob", email="bob@operations-support.com"),
				SupportStaff(name="Charlie", email="charlie@operations-support.com"),
			]
			db.session.add_all(staff_list)
			db.session.commit()
	app.run(host="0.0.0.0", port=8005)

