from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

USER_SVC = os.environ.get("USER_SVC", "http://user:8008")
ORDER_SVC = os.environ.get("ORDER_SVC", "http://order:8006")
DOC_SVC = os.environ.get("DOC_SVC", "http://document:8001")
NOTIF_SVC = os.environ.get("NOTIF_SVC", "http://notification:8002")

@app.route("/submit", methods=["POST"])
def submit_claim():
    try:
        user_id = request.form.get("user_id")
        order_id = request.form.get("order_id")
        description = request.form.get("description", "No description provided")
        evidence_file = request.files.get("file")

        if not all([user_id, order_id, evidence_file]):
            return jsonify({"error": "Missing user_id, order_id, or evidence file"}), 400

        user_resp = requests.get(f"{USER_SVC}/{user_id}")
        if user_resp.status_code != 200:
            return jsonify({"error": "Invalid user identity"}), 401
        user_info = user_resp.json()

        order_resp = requests.get(f"{ORDER_SVC}/orders/{order_id}")
        if order_resp.status_code != 200:
            return jsonify({"error": "Order not found"}), 404
        
        order_data = order_resp.json()

        doc_files = {'file': (evidence_file.filename, evidence_file.stream, evidence_file.content_type)}
        doc_data = {'order_id': order_id}
        doc_resp = requests.post(f"{DOC_SVC}/upload", files=doc_files, data=doc_data)
        
        if doc_resp.status_code != 201:
            return jsonify({"error": "Failed to store evidence via Document Service"}), 500
        
        stored_evidence_path = doc_resp.json().get("file_path")

        import random
        claim_approved = random.choice([True, False])

        status_msg = "APPROVED" if claim_approved else "REJECTED"

        if claim_approved:
            requests.patch(
                f"{ORDER_SVC}/orders/{order_id}/status",
                json={"status": "REFUNDED"},
                timeout=5
            )

        return jsonify({
            "status": "success",
            "claim_result": status_msg,
            "evidence_recorded": stored_evidence_path
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8102)
