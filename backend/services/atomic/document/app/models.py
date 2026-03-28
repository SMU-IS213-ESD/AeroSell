from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Document(db.Model):
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    upload_time = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "upload_time": self.upload_time.isoformat()
        }
