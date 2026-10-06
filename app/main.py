# File: app/main.py
import os

from analysis import analysis_bp
from auth import auth_bp
from autohpo import autohpo_bp
from flask import Flask, flash, redirect, request, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from individual import individual_bp
from models import User, db
from routes import routes_bp

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Generate one with "
        '`python3 -c "import secrets; print(secrets.token_hex(32))"` '
        "and put it in .env as SECRET_KEY=<value>."
    )

COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=COOKIE_SECURE,
    # CSRF token lasts the whole session; staff may spend over an hour on a form
    WTF_CSRF_TIME_LIMIT=None,
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:////opt/instance/app.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
)

# ensure db directory exists
os.makedirs("/opt/instance", exist_ok=True)

# CSRF protection
csrf = CSRFProtect(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    # JSON callers (fetch) get a JSON error; forms get a flash + redirect
    if request.path.startswith("/api/"):
        return {"error": "Your session expired, please reload the page and try again."}, 400
    flash("Your session expired, please try again.", "warning")
    return redirect(url_for("routes.index"))


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
app.register_blueprint(individual_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(autohpo_bp)


import hpo as hpo_module

with app.app_context():
    hpo_module.init_app()

if __name__ == "__main__":
    # Create tables when running directly
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=8000, debug=(os.environ.get("FLASK_ENV") == "development"))
