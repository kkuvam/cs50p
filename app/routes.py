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

@routes_bp.route("/docs")
@login_required
def docs():
    """Documentation page - user guides and system documentation"""
    return render_template("docs/index.html", user=current_user)

@routes_bp.route("/docs/getting-started")
@login_required
def docs_getting_started():
    """Getting Started documentation - complete guide for new users"""
    return render_template("docs/getting_started.html", user=current_user)

@routes_bp.route("/docs/manual")
@login_required
def docs_manual():
    """User Manual documentation - comprehensive feature guide"""
    return render_template("docs/manual.html", user=current_user)

@routes_bp.route("/docs/troubleshooting")
@login_required
def docs_troubleshooting():
    """Troubleshooting documentation - common issues and solutions"""
    return render_template("docs/troubleshooting.html", user=current_user)

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

@routes_bp.route("/admin/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@login_required
@admin_required
def admin_reset_password(user_id):
    """Reset user password"""
    user_to_reset = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            # Get form data
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")
            notify_user = bool(request.form.get("notify_user"))

            # Validation
            if not password:
                flash("Password is required", "error")
                return render_template("admin/reset_password.html", user_to_reset=user_to_reset)

            if password != confirm_password:
                flash("Passwords do not match", "error")
                return render_template("admin/reset_password.html", user_to_reset=user_to_reset)

            if len(password) < 6:
                flash("Password must be at least 6 characters long", "error")
                return render_template("admin/reset_password.html", user_to_reset=user_to_reset)

            # Update password
            user_to_reset.set_password(password)
            db.session.commit()

            # Log the action
            action_by = "yourself" if user_to_reset.id == current_user.id else f"admin {current_user.email}"
            flash(f"Password has been reset successfully for {user_to_reset.email} by {action_by}", "success")

            # TODO: Implement email notification if notify_user is True and email system is configured
            if notify_user:
                flash("Note: Email notification feature is not yet implemented", "info")

            return redirect(url_for("routes.admin_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error resetting password: {str(e)}", "error")
            return render_template("admin/reset_password.html", user_to_reset=user_to_reset)

    return render_template("admin/reset_password.html", user_to_reset=user_to_reset)

@routes_bp.route("/admin/users/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_user():
    """Add a new user"""
    if request.method == "POST":
        try:
            # Get form data
            email = request.form.get("email", "").strip()
            full_name = request.form.get("full_name", "").strip()
            is_active = bool(request.form.get("is_active"))
            is_admin = bool(request.form.get("is_admin"))

            # Validation
            if not email:
                flash("Email is required", "error")
                return render_template("admin/add_user.html")

            # Check if email already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("A user with this email already exists", "error")
                return render_template("admin/add_user.html")

            # Create new user with temporary password
            new_user = User()
            new_user.email = email
            new_user.full_name = full_name if full_name else None
            new_user.is_active = is_active
            new_user.is_admin = is_admin
            # Set a temporary password that needs to be reset
            new_user.set_password("temp_password_must_reset")

            db.session.add(new_user)
            db.session.commit()

            flash(f"User {email} has been created successfully. Use 'Reset Password' to set their initial password.", "success")
            return redirect(url_for("routes.admin_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating user: {str(e)}", "error")
            return render_template("admin/add_user.html")

    return render_template("admin/add_user.html")

@routes_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    """Edit an existing user"""
    user_to_edit = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            # Get form data
            email = request.form.get("email", "").strip()
            full_name = request.form.get("full_name", "").strip()
            is_active = bool(request.form.get("is_active"))
            is_admin = bool(request.form.get("is_admin"))

            # Validation
            if not email:
                flash("Email is required", "error")
                return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

            # Check if email already exists (but not for the current user)
            existing_user = User.query.filter(User.email == email, User.id != user_id).first()
            if existing_user:
                flash("A user with this email already exists", "error")
                return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

            # Update user data
            user_to_edit.email = email
            user_to_edit.full_name = full_name if full_name else None

            # Only allow changing admin/active status if not the current user
            if user_to_edit.id != current_user.id:
                user_to_edit.is_active = is_active
                user_to_edit.is_admin = is_admin

            db.session.commit()

            flash(f"User {email} has been updated successfully", "success")
            return redirect(url_for("routes.admin_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating user: {str(e)}", "error")
            return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

    return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

@routes_bp.route("/admin/users/<int:user_id>/delete", methods=["GET", "POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Delete a user"""
    user_to_delete = User.query.get_or_404(user_id)

    # Prevent deleting yourself
    if user_to_delete.id == current_user.id:
        flash("You cannot delete your own account", "error")
        return redirect(url_for("routes.admin_users"))

    if request.method == "POST":
        try:
            # Verify confirmation
            confirmation = request.form.get("confirmation", "").strip()
            if confirmation != "DELETE":
                flash("Invalid confirmation. Please type 'DELETE' to confirm.", "error")
                return render_template("admin/delete_user.html", user_to_delete=user_to_delete)

            email = user_to_delete.email
            db.session.delete(user_to_delete)
            db.session.commit()

            flash(f"User {email} has been deleted successfully", "success")
            return redirect(url_for("routes.admin_users"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting user: {str(e)}", "error")
            return render_template("admin/delete_user.html", user_to_delete=user_to_delete)

    return render_template("admin/delete_user.html", user_to_delete=user_to_delete)


# ===== API ROUTES =====
@routes_bp.route("/api/search/analyses")
@login_required
def api_search_analyses():
    """Search API for analyses - returns JSON data for Select2"""
    from models import Analysis, Individual, TaskStatus

    # Get search term from query parameter
    search_term = request.args.get('q', '').strip()

    # Build query for analyses that the user can access
    query = db.session.query(Analysis).join(Individual)

    # Filter by search term if provided
    if search_term:
        query = query.filter(
            db.or_(
                Analysis.name.ilike(f'%{search_term}%'),
                Analysis.description.ilike(f'%{search_term}%'),
                Individual.identity.ilike(f'%{search_term}%')
            )
        )

    # Only show completed analyses with results
    query = query.filter(
        Analysis.status == TaskStatus.COMPLETED,
        Analysis.output_html.isnot(None)
    )

    # Order by most recent first
    query = query.order_by(Analysis.completed_at.desc())

    # Limit results for performance
    analyses = query.limit(50).all()

    # Format for Select2
    results = []
    for analysis in analyses:
        results.append({
            'id': analysis.id,
            'text': f"{analysis.name} - {analysis.individual.identity} ({analysis.completed_at.strftime('%Y-%m-%d')})",
            'name': analysis.name,
            'individual_id': analysis.individual.identity,
            'completed_at': analysis.completed_at.strftime('%Y-%m-%d %H:%M'),
            'status': analysis.status.value
        })

    return jsonify({
        'results': results,
        'pagination': {'more': False}
    })
