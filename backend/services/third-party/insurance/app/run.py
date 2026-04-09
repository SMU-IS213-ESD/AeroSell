import os
import random
import requests
from flask import Flask, request, jsonify
from werkzeug.datastructures import FileStorage

app = Flask(__name__)

# Kong base URL for document service
DOCUMENT_SERVICE_URL = os.environ.get("DOCUMENT_SERVICE_URL", "http://localhost:8880/document")


def generate_insurance_id():
    """Generate a random 8-digit insurance ID"""
    return "".join([str(random.randint(0, 9)) for _ in range(8)])


def upload_file_to_document_service(file: FileStorage, order_id: str) -> dict:
    """Upload file to document service and return the response"""
    try:
        # Prepare multipart form data
        files = {'file': (file.filename, file.stream, file.content_type)}
        data = {'order_id': order_id}

        response = requests.post(
            f"{DOCUMENT_SERVICE_URL}/upload",
            files=files,
            data=data,
            timeout=30
        )

        if response.status_code == 201:
            return {"success": True, "data": response.json()}
        else:
            return {"success": False, "error": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.route("/buy", methods=["GET"])
def buy_insurance():
    """
    Generate and return a new insurance ID
    Returns: {"insurance_id": "12345678"}
    """
    insurance_id = generate_insurance_id()
    return jsonify({"insurance_id": insurance_id}), 200


@app.route("/claim", methods=["POST"])
def submit_claim():
    """
    Submit an insurance claim with file upload

    Required form fields:
    - insurance_id: The insurance policy ID
    - customer_name: Name of the customer
    - claim_type: Type of claim (e.g., "damage", "loss")
    - claim_reason: Reason for the claim
    - claim_amount: Amount being claimed
    - file: Image file as multipart/form-data

    Returns:
    - {"claim": "Accepted"} if all fields are present and file uploaded successfully
    - {"claim": "Rejected", "reason": "..."} if any validation fails
    """
    # Check if all required fields are present
    required_fields = ['insurance_id', 'customer_name', 'claim_type', 'claim_reason', 'claim_amount']

    # Check for missing fields
    missing_fields = []
    for field in required_fields:
        if field not in request.form or not request.form[field]:
            missing_fields.append(field)

    if missing_fields:
        return jsonify({
            "claim": "Rejected",
            "reason": f"Missing required fields: {', '.join(missing_fields)}"
        }), 400

    # Check if file is present
    if 'file' not in request.files:
        return jsonify({
            "claim": "Rejected",
            "reason": "Missing required field: file"
        }), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "claim": "Rejected",
            "reason": "No file selected"
        }), 400

    # Extract form data
    insurance_id = request.form['insurance_id']
    customer_name = request.form['customer_name']
    claim_type = request.form['claim_type']
    claim_reason = request.form['claim_reason']
    claim_amount = request.form['claim_amount']

    # Upload file to document service
    # Use insurance_id as order_id for document service
    upload_result = upload_file_to_document_service(file, insurance_id)

    if not upload_result["success"]:
        return jsonify({
            "claim": "Rejected",
            "reason": f"File upload failed: {upload_result.get('error', 'Unknown error')}"
        }), 400

    # If we reach here, all validations passed and file uploaded successfully
    return jsonify({"claim": "Accepted"}), 201


@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8500)
