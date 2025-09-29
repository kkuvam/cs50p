# File: app/patient.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Patient, Task, SexType
import os
import uuid

patient_bp = Blueprint("patient", __name__)

# ===== PATIENT CRUD ROUTES =====
@patient_bp.route("/patients")
@login_required
def patient_list():
    """Patient list page - shows all patients for current user"""
    patients = Patient.query.filter_by(user_id=current_user.id).order_by(Patient.created_at.desc()).all()
    return render_template("patient/patients.html", patients=patients, user=current_user)

@patient_bp.route("/patient/add", methods=["GET", "POST"])
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
                return render_template("patient/add.html", user=current_user)

            # At this point, we know vcf_file is not None and has a filename
            assert vcf_file is not None and vcf_file.filename is not None

            # Check for duplicate individual_id for current user
            existing = Patient.query.filter_by(user_id=current_user.id, individual_id=individual_id).first()
            if existing:
                flash(f"Patient with Individual ID '{individual_id}' already exists", "error")
                return render_template("patient/add.html", user=current_user)

            # Process VCF file upload
            vcf_upload_dir = "/opt/exomiser/ikdrc/vcf"
            os.makedirs(vcf_upload_dir, exist_ok=True)

            # Generate unique filename
            file_extension = os.path.splitext(vcf_file.filename)[1]
            unique_filename = f"{current_user.id}_{individual_id}_{uuid.uuid4().hex[:8]}{file_extension}"
            vcf_file_path = os.path.join(vcf_upload_dir, unique_filename)

            # Save the file
            vcf_file.save(vcf_file_path)

            # Create patient with all required fields (phenopacket_yaml will be generated next)
            patient = Patient(
                individual_id=individual_id,
                full_name=full_name,
                sex=SexType(sex),
                age_years=age_years,
                medical_history=medical_history or None,
                diagnosis=diagnosis or None,
                hpo_terms=hpo_terms,
                vcf_file_path=vcf_file_path,
                phenopacket_yaml=None,  # Will be generated next using update_phenopacket_yaml()
                user_id=current_user.id
            )

            # Generate YAML phenopacket using the patient's method
            patient.update_phenopacket_yaml("Exomiser Web Interface")

            db.session.add(patient)
            db.session.commit()

            flash(f"Patient '{individual_id}' created successfully", "success")
            return redirect(url_for("patient.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating patient: {str(e)}", "error")
            return render_template("patient/add.html", user=current_user)

    return render_template("patient/add.html", user=current_user)

@patient_bp.route("/patient/<int:patient_id>/edit", methods=["GET", "POST"])
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
            return redirect(url_for("patient.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating patient: {str(e)}", "error")
            return render_template("patient/edit.html", patient=patient, user=current_user)

    return render_template("patient/edit.html", patient=patient, user=current_user)

@patient_bp.route("/patient/<int:patient_id>/delete", methods=["GET", "POST"])
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
            return redirect(url_for("patient.patient_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting patient: {str(e)}", "error")
            return render_template("patient/delete.html", patient=patient, user=current_user)

    return render_template("patient/delete.html", patient=patient, user=current_user)

@patient_bp.route("/patient/<int:patient_id>/phenopacket")
@login_required
def patient_phenopacket(patient_id):
    """Get patient phenopacket YAML via AJAX"""
    patient = Patient.query.filter_by(id=patient_id, user_id=current_user.id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    return jsonify({
        "patient_id": patient.id,
        "individual_id": patient.individual_id,
        "phenopacket_yaml": patient.phenopacket_yaml or "No phenopacket generated"
    })

@patient_bp.route("/patient/<int:patient_id>/regenerate-phenopacket", methods=["POST"])
@login_required
def regenerate_patient_phenopacket(patient_id):
    """Regenerate phenopacket YAML for a patient"""
    try:
        patient = Patient.query.filter_by(id=patient_id, user_id=current_user.id).first()
        if not patient:
            return jsonify({"success": False, "error": "Patient not found"}), 404

        # Regenerate the phenopacket YAML using the model method
        patient.update_phenopacket_yaml("Exomiser Web Interface")
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Phenopacket regenerated for patient {patient.individual_id}",
            "patient_id": patient.id,
            "phenopacket_yaml": patient.phenopacket_yaml
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
