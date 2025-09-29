# File: app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, User
from datetime import datetime
from functools import wraps

routes_bp = Blueprint("routes", __name__)

# ===== GENERAL ROUTES =====
@routes_bp.route("/")
@login_required
def index():
    # Handle both public index and authenticated dashboard
    if current_user.is_authenticated:
        return render_template("index.html", user=current_user)
    else:
        return render_template("index.html")

# ===== HELP AND INFORMATION ROUTES =====
@routes_bp.route("/help/faq")
@login_required
def help_faq():
    """FAQ page - frequently asked questions"""
    return render_template("help/faq.html", user=current_user)

@routes_bp.route("/help/support")
@login_required
def help_support():
    """Support page - contact and support information"""
    return render_template("help/support.html", user=current_user)

@routes_bp.route("/help/logs")
@login_required
def help_logs():
    """Logs page - system and analysis logs"""
    return render_template("help/logs.html", user=current_user)

@routes_bp.route("/privacy")
def privacy():
    """Privacy Policy page"""
    return render_template("privacy.html")

@routes_bp.route("/terms")
def terms():
    """Terms of Service page"""
    return render_template("terms.html")

# ===== ADMIN DECORATOR =====
def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("routes.index"))
        return f(*args, **kwargs)
    return decorated_function

# ===== ADMIN ROUTES =====
@routes_bp.route("/admin/users")
@login_required
@admin_required
def admin_users():
    """Admin user management page"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, user=current_user)

@routes_bp.route("/admin/users/<int:user_id>/toggle-status", methods=["POST"])
@login_required
@admin_required
def toggle_user_status(user_id):
    """Toggle user active status via AJAX"""
    try:
        user = User.query.get_or_404(user_id)

        # Don't allow deactivating yourself
        if user.id == current_user.id:
            return jsonify({"success": False, "message": "Cannot modify your own account"})

        data = request.get_json()
        action = data.get("action")

        if action == "active":
            user.is_active = True
            message = f"User {user.email} has been activated"
        elif action == "inactive":
            user.is_active = False
            message = f"User {user.email} has been deactivated"
        else:
            return jsonify({"success": False, "message": "Invalid action"})

        db.session.commit()

        return jsonify({
            "success": True,
            "message": message,
            "user_id": user_id,
            "is_active": user.is_active
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})

@routes_bp.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def toggle_admin_status(user_id):
    """Toggle user admin status via AJAX"""
    try:
        user = User.query.get_or_404(user_id)

        # Don't allow removing admin from yourself
        if user.id == current_user.id:
            return jsonify({"success": False, "message": "Cannot modify your own admin status"})

        data = request.get_json()
        action = data.get("action")

        if action == "admin":
            user.is_admin = True
            message = f"Admin privileges granted to {user.email}"
        elif action == "user":
            user.is_admin = False
            message = f"Admin privileges removed from {user.email}"
        else:
            return jsonify({"success": False, "message": "Invalid action"})

        db.session.commit()

        return jsonify({
            "success": True,
            "message": message,
            "user_id": user_id,
            "is_admin": user.is_admin
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})
