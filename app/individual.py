# File: app/individual.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, abort
from flask_login import login_required, current_user
from models import db, Individual, Task, SexType
from datetime import datetime
import os
import uuid
import re

individual_bp = Blueprint("individual", __name__)

def clean_vcf_filename(original_filename):
    """
    Clean VCF filename by extracting everything before '_v1' and adding .vcf extension
    Example: 'PWES_25387814_SUG_VCF_v1_Non-Filtered_2025-09-23_04-22-30.vcf' -> 'PWES_25387814_SUG_VCF.vcf'
    """
    if not original_filename:
        return original_filename
    
    # Remove file extension first
    name_without_ext = os.path.splitext(original_filename)[0]
    
    # Find everything before '_v1'
    match = re.match(r'^(.+?)_v\d+', name_without_ext)
    if match:
        clean_name = match.group(1)
    else:
        # If no '_v1' pattern found, use the original name without extension
        clean_name = name_without_ext
    
    # Always add .vcf extension
    return f"{clean_name}.vcf"

# ===== INDIVIDUAL CRUD ROUTES =====
@individual_bp.route("/individuals")
@login_required
def individual_list():
    """Individual list page - shows all individuals for all users"""
    individuals = Individual.query.order_by(Individual.created_at.desc()).all()
    return render_template("individual/individuals.html", individuals=individuals, user=current_user)

@individual_bp.route("/individual/add", methods=["GET", "POST"])
@login_required
def individual_add():
    """Add new individual"""
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

            # Validation for required fields
            errors = []
            if not individual_id:
                errors.append("Individual ID is required")
            if not full_name:
                errors.append("Full Name is required")
            if not age_years:
                errors.append("Age is required")
            if not hpo_terms or len(hpo_terms) == 0:
                errors.append("At least one HPO term is required")

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

            # Check for duplicate individual_id across all users
            existing = Individual.query.filter_by(individual_id=individual_id).first()
            if existing:
                flash(f"Individual with Individual ID '{individual_id}' already exists", "error")
                return render_template("individual/add.html", user=current_user)

            # Process VCF file upload
            vcf_upload_dir = "/opt/exomiser/ikdrc/vcf"
            os.makedirs(vcf_upload_dir, exist_ok=True)

            # Generate unique filename
            file_extension = os.path.splitext(vcf_file.filename)[1]
            unique_filename = f"{current_user.id}_{individual_id}_{uuid.uuid4().hex[:8]}{file_extension}"
            vcf_file_path = os.path.join(vcf_upload_dir, unique_filename)

            # Save the file
            vcf_file.save(vcf_file_path)

            # Create individual with all required fields (phenopacket_yaml will be generated next)
            individual = Individual(
                individual_id=individual_id,
                full_name=full_name,
                sex=SexType(sex),
                age_years=age_years,
                medical_history=medical_history or None,
                diagnosis=diagnosis or None,
                hpo_terms=hpo_terms,
                vcf_filename=vcf_file.filename,  # Store original filename
                vcf_file_path=vcf_file_path,
                phenopacket_yaml=None,  # Will be generated next using update_phenopacket_yaml()
                created_by=current_user.id,
                updated_by=current_user.id
            )

            # Generate YAML phenopacket using the individual's method
            individual.update_phenopacket_yaml("Exomiser Web Interface")

            db.session.add(individual)
            db.session.commit()

            flash(f"Individual '{individual_id}' created successfully", "success")
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
    individual = Individual.query.get_or_404(individual_id)
    return render_template("individual/view.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/edit", methods=["GET", "POST"])
@login_required
def individual_edit(individual_id):
    """Edit existing individual"""
    individual = Individual.query.get_or_404(individual_id)

    if request.method == "POST":
        try:
            # Update fields
            individual.individual_id = request.form.get("individual_id", "").strip()
            individual.full_name = request.form.get("full_name", "").strip() or None
            individual.sex = SexType(request.form.get("sex", "UNKNOWN"))
            individual.age_years = request.form.get("age_years", type=int)
            individual.medical_history = request.form.get("medical_history", "").strip() or None
            individual.diagnosis = request.form.get("diagnosis", "").strip() or None

            # Process HPO terms
            hpo_terms = request.form.get("hpo_terms")
            if hpo_terms:
                try:
                    import json
                    individual.hpo_terms = json.loads(hpo_terms) if isinstance(hpo_terms, str) else hpo_terms
                except (json.JSONDecodeError, TypeError):
                    individual.hpo_terms = []
            else:
                individual.hpo_terms = []

            # Handle VCF file upload (optional)
            vcf_file = request.files.get("vcf_file")
            if vcf_file and vcf_file.filename:
                # Store original filename
                original_filename = vcf_file.filename

                # Generate unique filename
                file_extension = ".vcf.gz" if vcf_file.filename.endswith(".gz") else ".vcf"
                unique_filename = f"{individual.individual_id}_{uuid.uuid4().hex[:8]}{file_extension}"

                # Save file
                vcf_dir = "/opt/exomiser/ikdrc/vcf"
                os.makedirs(vcf_dir, exist_ok=True)
                file_path = os.path.join(vcf_dir, unique_filename)
                vcf_file.save(file_path)

                # Update individual record
                individual.vcf_file_path = file_path
                individual.vcf_filename = original_filename

            # Update audit trail
            individual.updated_by = current_user.id

            # Validation
            if not individual.individual_id:
                flash("Individual ID is required", "error")
                return render_template("individual/edit.html", individual=individual, user=current_user)

            # Check for duplicate individual_id (excluding current individual)
            existing = Individual.query.filter_by(individual_id=individual.individual_id).filter(Individual.id != individual_id).first()
            if existing:
                flash(f"Another individual with Individual ID '{individual.individual_id}' already exists", "error")
                return render_template("individual/edit.html", individual=individual, user=current_user)

            db.session.commit()
            flash(f"Individual '{individual.individual_id}' updated successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating individual: {str(e)}", "error")
            return render_template("individual/edit.html", individual=individual, user=current_user)

    return render_template("individual/edit.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/delete", methods=["GET", "POST"])
@login_required
def individual_delete(individual_id):
    """Delete individual with confirmation"""
    individual = Individual.query.get_or_404(individual_id)

    if request.method == "POST":
        try:
            # Check if individual has associated tasks
            task_count = Task.query.filter_by(individual_id=individual_id).count()
            if task_count > 0:
                flash(f"Cannot delete individual '{individual.individual_id}' - {task_count} analysis task(s) are associated with this individual", "error")
                return render_template("individual/delete.html", individual=individual, user=current_user)

            individual_id_val = individual.individual_id
            db.session.delete(individual)
            db.session.commit()

            flash(f"Individual '{individual_id_val}' deleted successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting individual: {str(e)}", "error")
            return render_template("individual/delete.html", individual=individual, user=current_user)

    return render_template("individual/delete.html", individual=individual, user=current_user)

@individual_bp.route("/individual/<int:individual_id>/analysis", methods=["POST"])
@login_required
def individual_analysis(individual_id):
    """Handle analysis form submission with generated YAML"""
    try:
        individual = Individual.query.get(individual_id)
        if not individual:
            flash("Individual not found", "error")
            return redirect(url_for('individual.individual_list'))

        # Get the generated YAML from the form
        phenopacket_yaml = request.form.get('phenopacket_yaml')

        if not phenopacket_yaml:
            flash("No phenopacket YAML was generated", "error")
            return redirect(url_for('individual.individual_view', individual_id=individual_id))

        # Update the individual with the generated YAML
        individual.phenopacket_yaml = phenopacket_yaml
        individual.last_updater = current_user
        individual.updated_at = datetime.utcnow()

        db.session.commit()

        flash(f"Analysis phenopacket generated successfully for {individual.individual_id}", "success")

        # Redirect to a results page or back to view
        return redirect(url_for('individual.individual_view', individual_id=individual_id))

    except Exception as e:
        db.session.rollback()
        flash(f"Error generating analysis: {str(e)}", "error")
        return redirect(url_for('individual.individual_view', individual_id=individual_id))

@individual_bp.route("/individual/<int:individual_id>/download_vcf")
@login_required
def download_vcf(individual_id):
    """Download VCF file for an individual"""
    individual = Individual.query.get_or_404(individual_id)

    # Check if VCF file exists
    if not individual.vcf_file_path or not os.path.exists(individual.vcf_file_path):
        flash("VCF file not found", "error")
        return redirect(url_for('individual.individual_view', individual_id=individual_id))

    try:
        # Get the original filename from the path
        filename = os.path.basename(individual.vcf_file_path)
        # Create a more user-friendly filename
        download_filename = f"{individual.individual_id}_{filename}"

        return send_file(
            individual.vcf_file_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype='text/plain'
        )
    except Exception as e:
        flash(f"Error downloading file: {str(e)}", "error")
        return redirect(url_for('individual.individual_view', individual_id=individual_id))
