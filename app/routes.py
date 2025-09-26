# File: app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Patient, Task, SexType, TaskStatus, GenomeAssembly, User
from datetime import datetime
from functools import wraps

routes_bp = Blueprint("routes", __name__)

@routes_bp.route("/")
@login_required
def index():
    # Handle both public index and authenticated dashboard
    if current_user.is_authenticated:
        return render_template("index.html", user=current_user)
    else:
        return render_template("index.html")

# ===== PATIENT CRUD ROUTES =====
@routes_bp.route("/patients")
@login_required
def patient_list():
    """Patient list page - shows all patients for current user"""
    patients = Patient.query.filter_by(user_id=current_user.id).order_by(Patient.created_at.desc()).all()
    return render_template("patient/patients.html", patients=patients, user=current_user)

@routes_bp.route("/patient/add", methods=["GET", "POST"])
@login_required
def patient_add():
    """Add new patient"""
    if request.method == "POST":
        try:
            # Get form data
            individual_id = request.form.get("individual_id", "").strip()
            full_name = request.form.get("full_name", "").strip()
            sex = request.form.get("sex", "UNKNOWN")
            age_years = request.form.get("age_years", type=int)
            medical_history = request.form.get("medical_history", "").strip()
            diagnosis = request.form.get("diagnosis", "").strip()

            # Process HPO terms (expecting JSON string or form array)
            hpo_terms = request.form.get("hpo_terms")
            if hpo_terms:
                try:
                    import json
                    hpo_terms = json.loads(hpo_terms) if isinstance(hpo_terms, str) else hpo_terms
                except (json.JSONDecodeError, TypeError):
                    hpo_terms = []
            else:
                hpo_terms = []

            # Validation
            if not individual_id:
                flash("Individual ID is required", "error")
                return render_template("patient/add.html", user=current_user)

            # Check for duplicate individual_id for current user
            existing = Patient.query.filter_by(user_id=current_user.id, individual_id=individual_id).first()
            if existing:
                flash(f"Patient with Individual ID '{individual_id}' already exists", "error")
                return render_template("patient/add.html", user=current_user)

            # Create patient
            patient = Patient(
                individual_id=individual_id,
                full_name=full_name or None,
                sex=SexType(sex),
                age_years=age_years,
                medical_history=medical_history or None,
                diagnosis=diagnosis or None,
                hpo_terms=hpo_terms,
                user_id=current_user.id
            )

            db.session.add(patient)
            db.session.commit()

            flash(f"Patient '{individual_id}' created successfully", "success")
            return redirect(url_for("routes.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating patient: {str(e)}", "error")
            return render_template("patient/add.html", user=current_user)

    return render_template("patient/add.html", user=current_user)

@routes_bp.route("/patient/<int:patient_id>/edit", methods=["GET", "POST"])
@login_required
def patient_edit(patient_id):
    """Edit existing patient"""
    patient = Patient.query.filter_by(id=patient_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        try:
            # Update fields
            patient.individual_id = request.form.get("individual_id", "").strip()
            patient.full_name = request.form.get("full_name", "").strip() or None
            patient.sex = SexType(request.form.get("sex", "UNKNOWN"))
            patient.age_years = request.form.get("age_years", type=int)
            patient.medical_history = request.form.get("medical_history", "").strip() or None
            patient.diagnosis = request.form.get("diagnosis", "").strip() or None

            # Process HPO terms
            hpo_terms = request.form.get("hpo_terms")
            if hpo_terms:
                try:
                    import json
                    patient.hpo_terms = json.loads(hpo_terms) if isinstance(hpo_terms, str) else hpo_terms
                except (json.JSONDecodeError, TypeError):
                    patient.hpo_terms = []
            else:
                patient.hpo_terms = []

            # Validation
            if not patient.individual_id:
                flash("Individual ID is required", "error")
                return render_template("patient/edit.html", patient=patient, user=current_user)

            # Check for duplicate individual_id (excluding current patient)
            existing = Patient.query.filter_by(user_id=current_user.id, individual_id=patient.individual_id).filter(Patient.id != patient_id).first()
            if existing:
                flash(f"Another patient with Individual ID '{patient.individual_id}' already exists", "error")
                return render_template("patient/edit.html", patient=patient, user=current_user)

            db.session.commit()
            flash(f"Patient '{patient.individual_id}' updated successfully", "success")
            return redirect(url_for("routes.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating patient: {str(e)}", "error")
            return render_template("patient/edit.html", patient=patient, user=current_user)

    return render_template("patient/edit.html", patient=patient, user=current_user)

@routes_bp.route("/patient/<int:patient_id>/delete", methods=["GET", "POST"])
@login_required
def patient_delete(patient_id):
    """Delete patient with confirmation"""
    patient = Patient.query.filter_by(id=patient_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        try:
            # Check if patient has associated tasks
            task_count = Task.query.filter_by(patient_id=patient_id).count()
            if task_count > 0:
                flash(f"Cannot delete patient '{patient.individual_id}' - {task_count} analysis task(s) are associated with this patient", "error")
                return render_template("patient/delete.html", patient=patient, user=current_user)

            individual_id = patient.individual_id
            db.session.delete(patient)
            db.session.commit()

            flash(f"Patient '{individual_id}' deleted successfully", "success")
            return redirect(url_for("routes.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting patient: {str(e)}", "error")
            return render_template("patient/delete.html", patient=patient, user=current_user)

    return render_template("patient/delete.html", patient=patient, user=current_user)

# ===== TASK CRUD ROUTES =====
@routes_bp.route("/tasks")
@login_required
def task_list():
    """Analysis tasks page - shows all tasks for current user"""
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()
    return render_template("task/tasks.html", tasks=tasks, user=current_user)

@routes_bp.route("/task/add", methods=["GET", "POST"])
@login_required
def task_add():
    """Add new analysis task"""
    # Get available patients for dropdown
    patients = Patient.query.filter_by(user_id=current_user.id).order_by(Patient.individual_id).all()

    if request.method == "POST":
        try:
            # Get form data
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            patient_id = request.form.get("patient_id", type=int)
            vcf_filename = request.form.get("vcf_filename", "").strip()
            genome_assembly = request.form.get("genome_assembly", "hg19")
            analysis_mode = request.form.get("analysis_mode", "PASS_ONLY")
            frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Validation
            if not name:
                flash("Task name is required", "error")
                return render_template("task/add.html", patients=patients, user=current_user)

            if not patient_id:
                flash("Patient selection is required", "error")
                return render_template("task/add.html", patients=patients, user=current_user)

            if not vcf_filename:
                flash("VCF filename is required", "error")
                return render_template("task/add.html", patients=patients, user=current_user)

            # Verify patient belongs to current user
            patient = Patient.query.filter_by(id=patient_id, user_id=current_user.id).first()
            if not patient:
                flash("Selected patient not found", "error")
                return render_template("task/add.html", patients=patients, user=current_user)

            # Create task
            task = Task(
                name=name,
                description=description or None,
                patient_id=patient_id,
                vcf_filename=vcf_filename,
                genome_assembly=GenomeAssembly(genome_assembly),
                analysis_mode=analysis_mode,
                frequency_threshold=frequency_threshold,
                pathogenicity_threshold=pathogenicity_threshold,
                status=TaskStatus.PENDING,
                user_id=current_user.id
            )

            db.session.add(task)
            db.session.commit()

            flash(f"Analysis task '{name}' created successfully", "success")
            return redirect(url_for("routes.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating task: {str(e)}", "error")
            return render_template("task/add.html", patients=patients, user=current_user)

    return render_template("task/add.html", patients=patients, user=current_user)

@routes_bp.route("/task/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def task_edit(task_id):
    """Edit existing analysis task"""
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    patients = Patient.query.filter_by(user_id=current_user.id).order_by(Patient.individual_id).all()

    if request.method == "POST":
        try:
            # Update fields (only allow editing if task is not running)
            if task.status in [TaskStatus.RUNNING]:
                flash("Cannot edit running task", "error")
                return render_template("task/edit.html", task=task, patients=patients, user=current_user)

            task.name = request.form.get("name", "").strip()
            task.description = request.form.get("description", "").strip() or None
            task.patient_id = request.form.get("patient_id", type=int)
            task.vcf_filename = request.form.get("vcf_filename", "").strip()
            task.genome_assembly = GenomeAssembly(request.form.get("genome_assembly", "hg19"))
            task.analysis_mode = request.form.get("analysis_mode", "PASS_ONLY")
            task.frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            task.pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Validation
            if not task.name:
                flash("Task name is required", "error")
                return render_template("task/edit.html", task=task, patients=patients, user=current_user)

            if not task.patient_id:
                flash("Patient selection is required", "error")
                return render_template("task/edit.html", task=task, patients=patients, user=current_user)

            # Verify patient belongs to current user
            patient = Patient.query.filter_by(id=task.patient_id, user_id=current_user.id).first()
            if not patient:
                flash("Selected patient not found", "error")
                return render_template("task/edit.html", task=task, patients=patients, user=current_user)

            # Reset status to pending if it was failed/cancelled (allow rerun)
            if task.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task.status = TaskStatus.PENDING
                task.error_message = None

            db.session.commit()
            flash(f"Task '{task.name}' updated successfully", "success")
            return redirect(url_for("routes.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating task: {str(e)}", "error")
            return render_template("task/edit.html", task=task, patients=patients, user=current_user)

    return render_template("task/edit.html", task=task, patients=patients, user=current_user)

@routes_bp.route("/task/<int:task_id>/delete", methods=["GET", "POST"])
@login_required
def task_delete(task_id):
    """Delete analysis task with confirmation"""
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        try:
            # Check if task is running
            if task.status == TaskStatus.RUNNING:
                flash("Cannot delete running task", "error")
                return render_template("task/delete.html", task=task, user=current_user)

            task_name = task.name
            db.session.delete(task)
            db.session.commit()

            flash(f"Analysis task '{task_name}' deleted successfully", "success")
            return redirect(url_for("routes.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting task: {str(e)}", "error")
            return render_template("task/delete.html", task=task, user=current_user)

    return render_template("task/delete.html", task=task, user=current_user)

@routes_bp.route("/results")
@login_required
def results():
    """Results page - shows analysis results and status"""
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.updated_at.desc()).all()
    return render_template("task/results.html", tasks=tasks, user=current_user)

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
