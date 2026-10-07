# File: app/individual.py
import gzip
import os
import secrets
import time
import zlib
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from safe_log import log_error
from sqlalchemy.exc import IntegrityError
from models import Analysis, Individual, SexType, db
from werkzeug.utils import secure_filename

individual_bp = Blueprint("individual", __name__)

VCF_UPLOAD_DIR = "/opt/exomiser/ikdrc/vcf"
ALLOWED_VCF_EXTENSIONS = (".vcf", ".vcf.gz")
VCF_MAGIC = b"##fileformat=VCF"


def check_vcf_content(vcf_file, is_gz):
    """Raise ValueError unless the stream looks like a VCF. Reads only the first bytes
    (a gzip header plus a small decompressed prefix), then rewinds the stream."""
    stream = vcf_file.stream
    stream.seek(0)
    try:
        if is_gz:
            # BGZF is gzip with extra header fields; gzip.GzipFile reads both
            with gzip.GzipFile(fileobj=stream, mode="rb") as gz:
                head = gz.read(len(VCF_MAGIC))
        else:
            head = stream.read(len(VCF_MAGIC))
    except (OSError, EOFError, zlib.error):
        raise ValueError("File is not a valid VCF") from None
    finally:
        stream.seek(0)
    if head != VCF_MAGIC:
        raise ValueError("File is not a valid VCF")


def is_identity_conflict(exc):
    """True if an IntegrityError is the unique-identity index. Checked server-side only;
    the DB message is never logged or shown."""
    return "uq_individuals_identity_active" in str(exc.orig)


def delete_new_vcf(path):
    """Remove a VCF saved by this request after a later failure."""
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def save_vcf_upload(vcf_file):
    """Sanitize and save an uploaded VCF. Returns (stored_path, display_name).

    Raises ValueError with a user-facing message if the filename or content is invalid.
    """
    display_name = secure_filename(vcf_file.filename or "")
    if not display_name:
        raise ValueError("Invalid VCF filename")
    if not display_name.lower().endswith(ALLOWED_VCF_EXTENSIONS):
        raise ValueError("VCF file must have a .vcf or .vcf.gz extension")

    check_vcf_content(vcf_file, display_name.lower().endswith(".gz"))

    os.makedirs(VCF_UPLOAD_DIR, exist_ok=True)
    # Timestamp and random suffix avoid collisions: <timestamp>_<8 hex>_<sanitized filename>
    stored_path = os.path.join(
        VCF_UPLOAD_DIR, f"{int(time.time())}_{secrets.token_hex(4)}_{display_name}"
    )
    try:
        vcf_file.save(stored_path)
    except BaseException:
        delete_new_vcf(stored_path)
        raise
    return stored_path, display_name

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
        vcf_file_path = None
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
            try:
                vcf_file_path, vcf_display_name = save_vcf_upload(vcf_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("individual/add.html", user=current_user)

            individual = Individual(
                identity=identity,
                full_name=full_name,
                sex=SexType(sex),
                age_years=age_years,
                age_months=age_months,
                medical_history=medical_history or None,
                diagnosis=diagnosis or None,
                vcf_filename=vcf_display_name,
                vcf_file_path=vcf_file_path,
                created_by=current_user.id,
                updated_by=current_user.id
            )

            db.session.add(individual)
            try:
                db.session.commit()
            except IntegrityError as ie:
                db.session.rollback()
                delete_new_vcf(vcf_file_path)
                if is_identity_conflict(ie):  # lost a race with another request
                    flash("Individual with this identity already exists", "error")
                    return render_template("individual/add.html", user=current_user)
                raise

            flash(f"Individual '{identity}' created successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            delete_new_vcf(vcf_file_path)
            log_error(current_app.logger, "Failed to create individual", e)
            flash("Error creating individual. Please try again or contact an admin.", "error")
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
        new_vcf_path = None
        try:
            # Read and validate everything before touching the ORM object or saving a file
            identity = request.form.get("identity", "").strip()
            full_name = request.form.get("full_name", "").strip() or None
            sex = SexType(request.form.get("sex", "UNKNOWN"))
            age_years = request.form.get("age_years", type=int) or 0
            age_months = request.form.get("age_months", type=int) or 0
            medical_history = request.form.get("medical_history", "").strip() or None
            diagnosis = request.form.get("diagnosis", "").strip() or None
            vcf_file = request.files.get("vcf_file")
            has_new_vcf = bool(vcf_file and vcf_file.filename)

            if not identity:
                flash("Identity is required", "error")
                return render_template(
                    "individual/edit.html", individual=individual, user=current_user
                )

            if not full_name:
                flash("Full Name is required", "error")
                return render_template(
                    "individual/edit.html", individual=individual, user=current_user
                )

            existing = (
                Individual.query.filter_by(identity=identity, is_deleted=False)
                .filter(Individual.id != individual_id)
                .first()
            )
            if existing:
                flash("Another individual with this identity already exists", "error")
                return render_template(
                    "individual/edit.html", individual=individual, user=current_user
                )

            new_vcf_name = None
            if has_new_vcf:
                try:
                    new_vcf_path, new_vcf_name = save_vcf_upload(vcf_file)
                except ValueError as e:
                    flash(str(e), "error")
                    return render_template("individual/edit.html", individual=individual, user=current_user)

            # All checks passed: apply changes
            individual.identity = identity
            individual.full_name = full_name
            individual.sex = sex
            individual.age_years = age_years
            individual.age_months = age_months
            individual.medical_history = medical_history
            individual.diagnosis = diagnosis
            if new_vcf_path:
                # the old file stays on disk (retention decision)
                individual.vcf_file_path = new_vcf_path
                individual.vcf_filename = new_vcf_name
            individual.updated_by = current_user.id

            try:
                db.session.commit()
            except IntegrityError as ie:
                db.session.rollback()
                delete_new_vcf(new_vcf_path)
                if is_identity_conflict(ie):
                    flash("Individual with this identity already exists", "error")
                    return render_template(
                        "individual/edit.html", individual=individual, user=current_user
                    )
                raise

            flash(f"Individual '{individual.identity}' updated successfully", "success")
            return redirect(url_for("individual.individual_list"))

        except Exception as e:
            db.session.rollback()
            delete_new_vcf(new_vcf_path)
            log_error(current_app.logger, "Failed to update individual", e)
            flash("Error updating individual. Please try again or contact an admin.", "error")
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
            log_error(current_app.logger, "Failed to delete individual", e)
            flash("Error deleting individual. Please try again or contact an admin.", "error")
            return render_template("individual/delete.html", individual=individual, user=current_user)

    return render_template("individual/delete.html", individual=individual, user=current_user)


@individual_bp.route("/api/individual/<int:individual_id>/clinical-history")
@login_required
def get_individual_clinical_history(individual_id):
    """Return diagnosis and medical_history for the AutoHPO modal."""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()
    return jsonify({
        "diagnosis": individual.diagnosis or "",
        "medical_history": individual.medical_history or "",
    })


@individual_bp.route("/api/individual/<int:individual_id>/vcf-info")
@login_required
def get_individual_vcf_info(individual_id):
    """API endpoint to get individual's VCF filename for analysis form"""
    individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first_or_404()
    return {
        "vcf_filename": individual.vcf_filename,
        "identity": individual.identity,
        "has_vcf_file": bool(individual.vcf_file_path and os.path.exists(individual.vcf_file_path)) if individual.vcf_file_path else False
    }
