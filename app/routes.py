# File: app/routes.py
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from analysis import REPORT_HEADERS
from safe_log import log_error
from models import db, User, Analysis, Individual, TaskStatus
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import func
import os
import psutil

routes_bp = Blueprint("routes", __name__)

# Prime psutil so the first non-blocking cpu_percent() call is meaningful
psutil.cpu_percent(interval=None)

def get_system_metrics():
    """Get system monitoring metrics (CPU, Memory, Storage).

    Each group is None when it could not be read."""
    metrics = {'cpu': None, 'memory': None, 'storage': None}
    logger = current_app.logger

    try:
        # Non-blocking: CPU usage since the previous call
        cpu_usage = round(psutil.cpu_percent(interval=None), 1)
        cpu_cores = psutil.cpu_count(logical=True)
        metrics['cpu'] = {
            'usage': cpu_usage,
            'cores': cpu_cores,
            # Approximation: 25% on 4 cores is ~1 core equivalent busy
            'cores_used': round((cpu_usage / 100) * cpu_cores, 1),
        }
    except (OSError, TypeError) as e:
        logger.warning("CPU metrics unavailable (%s)", type(e).__name__)

    try:
        memory = psutil.virtual_memory()
        metrics['memory'] = {
            'usage': round(memory.percent, 1),
            'total': round(memory.total / (1024**3), 1),  # GB
            'used': round(memory.used / (1024**3), 1),    # GB
        }
    except OSError as e:
        logger.warning("Memory metrics unavailable (%s)", type(e).__name__)

    try:
        disk = psutil.disk_usage('/')
        metrics['storage'] = {
            'usage': round((disk.used / disk.total) * 100, 1),
            'total': round(disk.total / (1024**3), 1),  # GB
            'used': round(disk.used / (1024**3), 1),    # GB
        }
    except (OSError, ZeroDivisionError) as e:
        logger.warning("Storage metrics unavailable (%s)", type(e).__name__)

    return metrics

# ===== GENERAL ROUTES =====
@routes_bp.route("/")
@login_required
def index():
    # Handle both public index and authenticated dashboard
    if current_user.is_authenticated:
        # Get dashboard statistics
        total_analyses = Analysis.query.filter_by(is_deleted=False).count()
        total_individuals = Individual.query.filter_by(is_deleted=False).count()

        # Success/Failure statistics
        successful_analyses = Analysis.query.filter_by(status=TaskStatus.COMPLETED, is_deleted=False).count()
        failed_analyses = Analysis.query.filter_by(status=TaskStatus.FAILED, is_deleted=False).count()
        pending_analyses = Analysis.query.filter_by(status=TaskStatus.PENDING, is_deleted=False).count()
        running_analyses = Analysis.query.filter_by(status=TaskStatus.RUNNING, is_deleted=False).count()
        cancelled_analyses = Analysis.query.filter_by(status=TaskStatus.CANCELLED, is_deleted=False).count()

        # Calculate success rate
        if total_analyses > 0:
            success_rate = round((successful_analyses / total_analyses) * 100, 1)
        else:
            success_rate = 0.0

        # Calculate mean runtime for completed analyses
        completed_analyses = Analysis.query.filter(
            Analysis.status == TaskStatus.COMPLETED,
            Analysis.is_deleted == False,
            Analysis.started_at.isnot(None),
            Analysis.completed_at.isnot(None)
        ).all()

        if completed_analyses:
            total_duration_seconds = sum(
                (analysis.completed_at - analysis.started_at).total_seconds()
                for analysis in completed_analyses
            )
            mean_runtime_seconds = total_duration_seconds / len(completed_analyses)

            # Convert to readable format (hours, minutes, seconds)
            hours = int(mean_runtime_seconds // 3600)
            minutes = int((mean_runtime_seconds % 3600) // 60)
            seconds = int(mean_runtime_seconds % 60)

            if hours > 0:
                mean_runtime = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                mean_runtime = f"{minutes}m {seconds}s"
            else:
                mean_runtime = f"{seconds}s"
        else:
            mean_runtime = "N/A"

        # Get recent successful analyses for the results table
        recent_analyses = Analysis.query.join(Individual).filter(
            Analysis.status == TaskStatus.COMPLETED,
            Analysis.is_deleted == False,
            Individual.is_deleted == False,
            Analysis.output_html.isnot(None)
        ).order_by(Analysis.completed_at.desc()).limit(5).all()

        # Calculate phenotype distribution for the chart (HPO terms now live on Analysis)
        phenotype_distribution = {}
        all_analyses = Analysis.query.filter_by(is_deleted=False).all()

        for analysis in all_analyses:
            if analysis.hpo_terms and isinstance(analysis.hpo_terms, list):
                for term in analysis.hpo_terms:
                    if isinstance(term, dict) and "label" in term:
                        label = term["label"]
                        phenotype_distribution[label] = phenotype_distribution.get(label, 0) + 1

        # Sort by frequency and get top 10
        sorted_phenotypes = sorted(phenotype_distribution.items(), key=lambda x: x[1], reverse=True)[:10]
        phenotype_labels = [item[0] for item in sorted_phenotypes] if sorted_phenotypes else ["No phenotypes found"]
        phenotype_counts = [item[1] for item in sorted_phenotypes] if sorted_phenotypes else [0]

        # Get system monitoring metrics
        system_metrics = get_system_metrics()

        return render_template("index.html",
                             user=current_user,
                             total_analyses=total_analyses,
                             total_individuals=total_individuals,
                             successful_analyses=successful_analyses,
                             failed_analyses=failed_analyses,
                             pending_analyses=pending_analyses,
                             running_analyses=running_analyses,
                             cancelled_analyses=cancelled_analyses,
                             success_rate=success_rate,
                             mean_runtime=mean_runtime,
                             recent_analyses=recent_analyses,
                             phenotype_labels=phenotype_labels,
                             phenotype_counts=phenotype_counts,
                             system_metrics=system_metrics)
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
    users = User.query.filter_by(is_deleted=False).order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, user=current_user)

@routes_bp.route("/admin/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@login_required
@admin_required
def admin_reset_password(user_id):
    """Reset user password"""
    user_to_reset = User.query.filter_by(id=user_id, is_deleted=False).first_or_404()

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
            log_error(current_app.logger, "Failed to reset password", e)
            flash("Error resetting password. Please try again or contact an admin.", "error")
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
            existing_user = User.query.filter_by(email=email, is_deleted=False).first()
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
            log_error(current_app.logger, "Failed to create user", e)
            flash("Error creating user. Please try again or contact an admin.", "error")
            return render_template("admin/add_user.html")

    return render_template("admin/add_user.html")

@routes_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    """Edit an existing user"""
    user_to_edit = User.query.filter_by(id=user_id, is_deleted=False).first_or_404()

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
            existing_user = User.query.filter(User.email == email, User.id != user_id, User.is_deleted == False).first()
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
            log_error(current_app.logger, "Failed to update user", e)
            flash("Error updating user. Please try again or contact an admin.", "error")
            return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

    return render_template("admin/edit_user.html", user_to_edit=user_to_edit)

@routes_bp.route("/admin/users/<int:user_id>/delete", methods=["GET", "POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Delete a user"""
    user_to_delete = User.query.filter_by(id=user_id, is_deleted=False).first_or_404()

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
            user_to_delete.is_deleted = True
            user_to_delete.deleted_at = datetime.utcnow()
            db.session.commit()

            flash(f"User {email} has been deleted successfully", "success")
            return redirect(url_for("routes.admin_users"))

        except Exception as e:
            db.session.rollback()
            log_error(current_app.logger, "Failed to delete user", e)
            flash("Error deleting user. Please try again or contact an admin.", "error")
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

    # Only show completed, non-deleted analyses with results
    query = query.filter(
        Analysis.status == TaskStatus.COMPLETED,
        Analysis.is_deleted == False,
        Individual.is_deleted == False,
        Analysis.output_html.isnot(None)
    )

    # Order by most recent first
    query = query.order_by(Analysis.completed_at.desc())

    # Limit results for performance
    analyses = query.limit(50).all()

    # Format for Select2
    results = []
    for analysis in analyses:
        # Get individual data safely
        individual = Individual.query.filter_by(id=analysis.individual_id, is_deleted=False).first() if analysis.individual_id else None
        individual_identity = individual.identity if individual else f"Individual {analysis.individual_id}"

        results.append({
            'id': analysis.id,
            'text': f"{analysis.name} - {individual_identity} ({analysis.completed_at.strftime('%Y-%m-%d') if analysis.completed_at else 'N/A'})",
            'name': analysis.name,
            'individual_id': individual_identity,
            'completed_at': analysis.completed_at.strftime('%Y-%m-%d %H:%M') if analysis.completed_at else 'N/A',
            'status': analysis.status.value
        })

    return jsonify({
        'results': results,
        'pagination': {'more': False}
    })

# ===== ANALYSIS REPORT SERVING =====
@routes_bp.route("/analysis/<int:analysis_id>/report")
@login_required
def serve_analysis_report(analysis_id):
    """Serve analysis HTML report files"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    # Check if report exists
    if not analysis.output_html or not os.path.exists(analysis.output_html):
        flash("Analysis report not found.", "error")
        return redirect(url_for('routes.index'))

    try:
        response = send_file(analysis.output_html, as_attachment=False)
        response.headers.update(REPORT_HEADERS)
        return response
    except Exception as e:
        log_error(current_app.logger, "Failed to serve report", e)
        flash("Error serving report. Please try again or contact an admin.", "error")
        return redirect(url_for('routes.index'))
