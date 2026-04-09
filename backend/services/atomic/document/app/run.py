import os
import time
from apiflask import APIFlask, Schema, abort
from apiflask.fields import String, Integer, DateTime
from flask import request, jsonify
from werkzeug.utils import secure_filename
from .models import db, Document

app = APIFlask(
	__name__,
	title="Document Service",
	version="1.0.0"
)

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

@app.get('/db-check')
@app.doc(tags=["Health Check"], summary="Database connectivity check")
def db_check():
	"""Verify database is reachable"""
	try:
		db.session.execute(db.text('SELECT 1'))
		return {"status": "ok"}, 200
	except Exception as e:
		app.logger.exception("DB check failed")
		abort(500, str(e))

@app.post('/upload')
@app.doc(tags=["Documents"], summary="Upload document/evidence")
@app.output(DocumentOut, status_code=201)
def upload_file():
	"""
	Handle insurance claim evidence upload
	Requires: 'file' (MultipartFile) and 'order_id' (Form Data)
	"""
	if 'file' not in request.files or 'order_id' not in request.form:
		abort(400, "Missing file or order_id")
	
	file = request.files['file']
	order_id = request.form['order_id']

	if file.filename == '':
		abort(400, "No file selected")

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

		return {
			"filename": original_filename,
			"order_id": order_id,
			"file_path": save_path
		}

@app.get('/documents/<order_id>')
@app.doc(tags=["Documents"], summary="Get documents for an order")
@app.output(List[DocumentOut])
def get_documents_by_order(order_id):
	"""Fetch all document records associated with a specific order"""
	docs = Document.query.filter_by(order_id=order_id).all()
	return docs

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001)
    app.run(host='0.0.0.0', port=8001)
