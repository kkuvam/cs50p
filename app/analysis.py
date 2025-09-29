# File: app/analysis.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Individual, Task, TaskStatus, GenomeAssembly

analysis_bp = Blueprint("analysis", __name__)

# ===== ANALYSIS CRUD ROUTES =====
@analysis_bp.route("/analyses")
@login_required
def analysis_list():
    """Analysis list page - shows all analyses for all users"""
    analyses = Task.query.order_by(Task.created_at.desc()).all()
    return render_template("analysis/analyses.html", analyses=analyses, user=current_user)

@analysis_bp.route("/analysis/add", methods=["GET", "POST"])
@login_required
def analysis_add():
    """Add new analysis"""
    # Get available individuals for dropdown
    individuals = Individual.query.order_by(Individual.individual_id).all()

    if request.method == "POST":
        try:
            # Get form data
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            individual_id = request.form.get("individual_id", type=int)
            vcf_filename = request.form.get("vcf_filename", "").strip()
            genome_assembly = request.form.get("genome_assembly", "hg19")
            analysis_mode = request.form.get("analysis_mode", "PASS_ONLY")
            frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Map lowercase genome assembly to enum
            genome_assembly_enum = GenomeAssembly.HG19 if genome_assembly == "hg19" else GenomeAssembly.HG38

            # Validation
            if not name:
                flash("Analysis name is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            if not individual_id:
                flash("Individual selection is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            if not vcf_filename:
                flash("VCF filename is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            # Verify individual exists
            individual = Individual.query.get(individual_id)
            if not individual:
                flash("Selected individual not found", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            # Create analysis (using Task model for now)
            analysis = Task(
                name=name,
                description=description or None,
                individual_id=individual_id,
                vcf_filename=vcf_filename,
                genome_assembly=genome_assembly_enum,
                analysis_mode=analysis_mode,
                frequency_threshold=frequency_threshold,
                pathogenicity_threshold=pathogenicity_threshold,
                status=TaskStatus.PENDING,
                created_by=current_user.id,
                updated_by=current_user.id
            )

            db.session.add(analysis)
            db.session.commit()

            flash(f"Analysis '{name}' created successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating analysis: {str(e)}", "error")
            return render_template("analysis/add.html", individuals=individuals, user=current_user)

    return render_template("analysis/add.html", individuals=individuals, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/edit", methods=["GET", "POST"])
@login_required
def analysis_edit(analysis_id):
    """Edit existing analysis"""
    analysis = Task.query.get_or_404(analysis_id)
    individuals = Individual.query.order_by(Individual.individual_id).all()

    if request.method == "POST":
        try:
            # Update fields (only allow editing if analysis is not running)
            if analysis.status in [TaskStatus.RUNNING]:
                flash("Cannot edit running analysis", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

            analysis.name = request.form.get("name", "").strip()
            analysis.description = request.form.get("description", "").strip() or None
            analysis.individual_id = request.form.get("individual_id", type=int)
            analysis.vcf_filename = request.form.get("vcf_filename", "").strip()
            # Map lowercase genome assembly to enum
            genome_assembly = request.form.get("genome_assembly", "hg19")
            analysis.genome_assembly = GenomeAssembly.HG19 if genome_assembly == "hg19" else GenomeAssembly.HG38
            analysis.analysis_mode = request.form.get("analysis_mode", "PASS_ONLY")
            analysis.frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            analysis.pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Update audit trail
            analysis.updated_by = current_user.id

            # Validation
            if not analysis.name:
                flash("Analysis name is required", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

            if not analysis.individual_id:
                flash("Individual selection is required", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

            # Verify individual exists
            individual = Individual.query.get(analysis.individual_id)
            if not individual:
                flash("Selected individual not found", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

            # Reset status to pending if it was failed/cancelled (allow rerun)
            if analysis.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                analysis.status = TaskStatus.PENDING
                analysis.error_message = None

            db.session.commit()
            flash(f"Analysis '{analysis.name}' updated successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating analysis: {str(e)}", "error")
            return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

    return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/delete", methods=["GET", "POST"])
@login_required
def analysis_delete(analysis_id):
    """Delete analysis with confirmation"""
    analysis = Task.query.get_or_404(analysis_id)

    if request.method == "POST":
        try:
            # Check if analysis is running
            if analysis.status == TaskStatus.RUNNING:
                flash("Cannot delete running analysis", "error")
                return render_template("analysis/delete.html", analysis=analysis, user=current_user)

            analysis_name = analysis.name
            db.session.delete(analysis)
            db.session.commit()

            flash(f"Analysis '{analysis_name}' deleted successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting analysis: {str(e)}", "error")
            return render_template("analysis/delete.html", analysis=analysis, user=current_user)

    return render_template("analysis/delete.html", analysis=analysis, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/view")
@login_required
def analysis_view(analysis_id):
    """View analysis details and results"""
    analysis = Task.query.get_or_404(analysis_id)
    return render_template("analysis/view.html", analysis=analysis, user=current_user)

@analysis_bp.route("/results")
@login_required
def results():
    """Results page - shows analysis results and status"""
    analyses = Task.query.order_by(Task.updated_at.desc()).all()
    return render_template("analysis/results.html", analyses=analyses, user=current_user)
