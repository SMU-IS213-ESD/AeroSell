from apiflask import APIFlask, Schema, abort
from apiflask.fields import String, Boolean
from flask import request
import requests
import os

app = APIFlask(
    __name__,
    title="Insurance Claim Service",
    version="1.0.0"
)

USER_SVC = os.environ.get("USER_SVC", "http://user:8008")
ORDER_SVC = os.environ.get("ORDER_SVC", "http://order:8006")
DOC_SVC = os.environ.get("DOC_SVC", "http://document:8001")
NOTIF_SVC = os.environ.get("NOTIF_SVC", "http://notification:8002")

class ClaimOut(Schema):
    claim_id = String()
    user_id = String()
    order_id = String()
    status = String()
    message = String()

@app.post("/submit")
@app.doc(tags=["Claims"], summary="Submit insurance claim")
def submit_claim():
    try:
        user_id = request.form.get("user_id")
        order_id = request.form.get("order_id")
        description = request.form.get("description", "No description provided")
        evidence_file = request.files.get("file")

        if not all([user_id, order_id, evidence_file]):
            abort(400, "Missing user_id, order_id, or evidence file")

        user_resp = requests.get(f"{USER_SVC}/{user_id}")
        if user_resp.status_code != 200:
            abort(401, "Invalid user identity")
        user_info = user_resp.json()

        order_resp = requests.get(f"{ORDER_SVC}/orders/{order_id}")
        if order_resp.status_code != 200:
            abort(404, "Order not found")
        
        order_data = order_resp.json()

        doc_files = {'file': (evidence_file.filename, evidence_file.stream, evidence_file.content_type)}
        doc_data = {'order_id': order_id}
        doc_resp = requests.post(f"{DOC_SVC}/upload", files=doc_files, data=doc_data)
        
        if doc_resp.status_code != 201:
            abort(500, "Failed to store evidence via Document Service")
        
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

        return {
            "status": "success",
            "claim_result": status_msg,
            "evidence_recorded": stored_evidence_path
        }

    except Exception as e:
        abort(500, str(e))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8102)
