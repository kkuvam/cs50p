# File: app/task.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Patient, Task, TaskStatus, GenomeAssembly

task_bp = Blueprint("task", __name__)

# ===== TASK CRUD ROUTES =====
@task_bp.route("/tasks")
@login_required
def task_list():
    """Analysis tasks page - shows all tasks for current user"""
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()
    return render_template("task/tasks.html", tasks=tasks, user=current_user)

@task_bp.route("/task/add", methods=["GET", "POST"])
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
            return redirect(url_for("task.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating task: {str(e)}", "error")
            return render_template("task/add.html", patients=patients, user=current_user)

    return render_template("task/add.html", patients=patients, user=current_user)

@task_bp.route("/task/<int:task_id>/edit", methods=["GET", "POST"])
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
            return redirect(url_for("task.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating task: {str(e)}", "error")
            return render_template("task/edit.html", task=task, patients=patients, user=current_user)

    return render_template("task/edit.html", task=task, patients=patients, user=current_user)

@task_bp.route("/task/<int:task_id>/delete", methods=["GET", "POST"])
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
            return redirect(url_for("task.task_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting task: {str(e)}", "error")
            return render_template("task/delete.html", task=task, user=current_user)

    return render_template("task/delete.html", task=task, user=current_user)

@task_bp.route("/results")
@login_required
def results():
    """Results page - shows analysis results and status"""
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.updated_at.desc()).all()
    return render_template("task/results.html", tasks=tasks, user=current_user)
