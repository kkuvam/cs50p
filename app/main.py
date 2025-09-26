# File: app/main.py
import os
import click
from flask import Flask
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from models import db, User, Patient, Task
from auth import auth_bp
from routes import routes_bp

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

# CLI command to create admin user
@app.cli.command()
@click.option('--email', prompt=True, help='Admin email address')
@click.option('--password', prompt=True, hide_input=True, help='Admin password')
@click.option('--name', prompt=True, help='Full name')
def create_admin(email, password, name):
    """Create an admin user."""

    # Ensure tables exist
    db.create_all()

    # Check if admin already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        click.echo(f"User with email {email} already exists!")
        return

    # Create new admin user
    admin_user = User(
        email=email,
        password_hash=generate_password_hash(password),
        full_name=name,
        is_active=True,
        is_admin=True
    )

    db.session.add(admin_user)
    db.session.commit()

    click.echo(f"Admin user {email} created successfully!")

if __name__ == "__main__":
    # Create tables when running directly
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=8000, debug=(os.environ.get("FLASK_ENV") != "production"))
