# File: app/individual.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, abort
from flask_login import login_required, current_user
from models import db, Individual, Analysis, SexType
from datetime import datetime
import os
import uuid
import time

individual_bp = Blueprint("individual", __name__)

# Function removed - we now store original filenames without cleanup

# ===== INDIVIDUAL CRUD ROUTES =====
@individual_bp.route("/individuals")
@login_required
def individual_list():
    """Individual list page - shows all individuals for all users"""
    individuals = Individual.query.filter_by(is_deleted=False).order_by(Individual.created_at.desc()).all()
    return render_template("individual/individuals.html", individuals=individuals, user=current_user)

@individual_bp.route("/individual/add", methods=["GET", "POST"])
@login_required
def individual_add():
    """Add new individual"""
    if request.method == "POST":
        try:
            # Get form data
            identity = request.form.get("identity", "").strip()
            full_name = request.form.get("full_name", "").strip()
            sex = request.form.get("sex", "UNKNOWN")
            age_years = request.form.get("age_years", type=int) or 0
            age_months = request.form.get("age_months", type=int) or 0
            medical_history = request.form.get("medical_history", "").strip()
            diagnosis = request.form.get("diagnosis", "").strip()

            # Validation for required fields
            errors = []
            if not identity:
                errors.append("Identity is required")
            if not full_name:
                errors.append("Full Name is required")
            if age_years == 0 and age_months == 0:
                errors.append("Age is required (years and/or months)")

            # Handle VCF file upload (required)
            vcf_file = request.files.get('vcf_file')
            if not vcf_file or not vcf_file.filename:
                errors.append("VCF file is required")

            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("individual/add.html", user=current_user)

            # At this point, we know vcf_file is not None and has a filename
            assert vcf_file is not None and vcf_file.filename is not None

            # Check for duplicate identity among active individuals
            existing = Individual.query.filter_by(identity=identity, is_deleted=False).first()
            if existing:
                flash(f"Individual with Identity '{identity}' already exists", "error")
                return render_template("individual/add.html", user=current_user)

            # Process VCF file upload
            vcf_upload_dir = "/opt/exomiser/ikdrc/vcf"
            os.makedirs(vcf_upload_dir, exist_ok=True)

            # Create timestamped filename to avoid collisions: timestamp_originalfilename
            timestamp = int(time.time())
            timestamped_filename = f"{timestamp}_{vcf_file.filename}"
            vcf_file_path = os.path.join(vcf_upload_dir, timestamped_filename)

            # Save the file
            vcf_file.save(vcf_file_path)

            individual = Individual(
                identity=identity,
                full_name=full_name,
                sex=SexType(sex),
                age_years=age_years,
                age_months=age_months,
                medical_history=medical_history or None,
                diagnosis=diagnosis or None,
                vcf_filename=vcf_file.filename,
                vcf_file_path=vcf_file_path,
                created_by=current_user.id,
                updated_by=current_user.id
            )

            db.session.add(individual)
            db.session.commit()

            flash(f"Individual '{identity}' created successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating individual: {str(e)}", "error")
            return render_template("individual/add.html", user=current_user)

    return render_template("individual/add.html", user=current_user)

@individual_bp.route("/individual/<int:individual_id>")
@login_required
def individual_view(individual_id):
    """View individual details"""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()
    return render_template("individual/view.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/edit", methods=["GET", "POST"])
@login_required
def individual_edit(individual_id):
    """Edit existing individual"""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()

    if request.method == "POST":
        try:
            # Update fields
            individual.identity = request.form.get("identity", "").strip()
            individual.full_name = request.form.get("full_name", "").strip() or None
            individual.sex = SexType(request.form.get("sex", "UNKNOWN"))
            individual.age_years = request.form.get("age_years", type=int) or 0
            individual.age_months = request.form.get("age_months", type=int) or 0
            individual.medical_history = request.form.get("medical_history", "").strip() or None
            individual.diagnosis = request.form.get("diagnosis", "").strip() or None

            # Handle VCF file upload (optional)
            vcf_file = request.files.get("vcf_file")
            if vcf_file and vcf_file.filename:
                # Create timestamped filename to avoid collisions: timestamp_originalfilename
                timestamp = int(time.time())
                timestamped_filename = f"{timestamp}_{vcf_file.filename}"

                vcf_dir = "/opt/exomiser/ikdrc/vcf"
                os.makedirs(vcf_dir, exist_ok=True)
                file_path = os.path.join(vcf_dir, timestamped_filename)

                vcf_file.save(file_path)

                # Update individual record with original filename (for display) and timestamped path (for storage)
                individual.vcf_file_path = file_path
                individual.vcf_filename = vcf_file.filename  # Keep original filename for display            # Update audit trail
            individual.updated_by = current_user.id

            # Validation
            if not individual.identity:
                flash("Identity is required", "error")
                return render_template("individual/edit.html", individual=individual, user=current_user)

            # Check for duplicate identity among active individuals (excluding current)
            existing = Individual.query.filter_by(identity=individual.identity, is_deleted=False).filter(Individual.id != individual_id).first()
            if existing:
                flash(f"Another individual with Identity '{individual.identity}' already exists", "error")
                return render_template("individual/edit.html", individual=individual, user=current_user)

            db.session.commit()
            flash(f"Individual '{individual.identity}' updated successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating individual: {str(e)}", "error")
            return render_template("individual/edit.html", individual=individual, user=current_user)

    return render_template("individual/edit.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/delete", methods=["GET", "POST"])
@login_required
def individual_delete(individual_id):
    """Soft-delete individual with confirmation"""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()

    if request.method == "POST":
        try:
            # Check confirmation input
            confirmation = request.form.get("confirmation", "").strip()
            if confirmation != "DELETE":
                flash("Please type 'DELETE' to confirm deletion", "error")
                return render_template("individual/delete.html", individual=individual, user=current_user)

            now = datetime.utcnow()
            identity_val = individual.identity

            # Cascade soft delete to all associated analyses
            Analysis.query.filter_by(individual_id=individual_id, is_deleted=False).update(
                {"is_deleted": True, "deleted_at": now}
            )

            # Soft delete the individual
            individual.is_deleted = True
            individual.deleted_at = now
            db.session.commit()

            flash(f"Individual '{identity_val}' deleted successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting individual: {str(e)}", "error")
            return render_template("individual/delete.html", individual=individual, user=current_user)

    return render_template("individual/delete.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/download_vcf")
@login_required
def download_vcf(individual_id):
    """Download VCF file for an individual"""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()

    # Check if VCF file exists
    if not individual.vcf_file_path or not os.path.exists(individual.vcf_file_path):
        flash("VCF file not found", "error")
        return redirect(url_for('individual.individual_view', individual_id=individual_id))

    try:
        # Use the original filename for download (without timestamp or identity prefix)
        original_filename = individual.vcf_filename or os.path.basename(individual.vcf_file_path)

        return send_file(
            individual.vcf_file_path,
            as_attachment=True,
            download_name=original_filename,
            mimetype='text/plain'
        )
    except Exception as e:
        flash(f"Error downloading file: {str(e)}", "error")
        return redirect(url_for('individual.individual_view', individual_id=individual_id))


@individual_bp.route("/api/individual/<int:individual_id>/vcf-info")
@login_required
def get_individual_vcf_info(individual_id):
    """API endpoint to get individual's VCF filename for analysis form"""
    try:
        individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()
        return {
            "vcf_filename": individual.vcf_filename,
            "identity": individual.identity,
            "has_vcf_file": bool(individual.vcf_file_path and os.path.exists(individual.vcf_file_path)) if individual.vcf_file_path else False
        }
    except Exception as e:
        return {"error": str(e)}, 400
