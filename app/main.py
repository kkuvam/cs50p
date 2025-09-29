# File: app/main.py
import os
from flask import Flask
from flask_login import LoginManager
from models import db, User, Patient, Task
from auth import auth_bp
from routes import routes_bp
from patient import patient_bp
from task import task_bp

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key"),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:////opt/instance/app.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
)

# ensure db directory exists
os.makedirs("/opt/instance", exist_ok=True)

# init db
db.init_app(app)

# login manager
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(routes_bp)
app.register_blueprint(patient_bp)
app.register_blueprint(task_bp)


if __name__ == "__main__":
    # Create tables when running directly
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=8000, debug=(os.environ.get("FLASK_ENV") != "production"))
