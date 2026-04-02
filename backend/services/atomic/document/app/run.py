import os
import time
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from .models import db

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db.init_app(app)

with app.app_context():
    for i in range(5):
        try:
            db.create_all()
            break
        except Exception as e:
            print(f"Database not ready, retrying in 2 seconds... ({i+1}/5)")
            time.sleep(2)

@app.route('/db-check', methods=['GET'])
def db_check():
    """Verify database connectivity"""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify(True), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Handle insurance claim evidence upload
    Requires: 'file' (MultipartFile) and 'order_id' (Form Data)
    """
    if 'file' not in request.files or 'order_id' not in request.form:
        return jsonify({"error": "Missing file or order_id"}), 400
    
    file = request.files['file']
    order_id = request.form['order_id']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if file:
        original_filename = secure_filename(file.filename)
        unique_name = f"{order_id}_{int(time.time())}_{original_filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        
        file.save(save_path)

        new_doc = Document(
            order_id=order_id,
            file_name=original_filename,
            file_path=save_path
        )
        db.session.add(new_doc)
        db.session.commit()

        return jsonify({
            "message": "Upload successful",
            "document": new_doc.to_dict()
        }), 201

@app.route('/documents/<order_id>', methods=['GET'])
def get_documents_by_order(order_id):
    """Fetch all document records associated with a specific order"""
    docs = Document.query.filter_by(order_id=order_id).all()
    return jsonify([d.to_dict() for d in docs]), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
