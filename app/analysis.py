# File: app/analysis.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required, current_user
from models import db, Individual, Analysis, TaskStatus, GenomeAssembly
import os
import subprocess
import threading
import time
from datetime import datetime

analysis_bp = Blueprint("analysis", __name__)

# Global dictionary to store real-time output for analyses
analysis_outputs = {}

# ===== ANALYSIS CRUD ROUTES =====
@analysis_bp.route("/analyses")
@login_required
def analysis_list():
    """Analysis list page - shows all analyses for all users"""
    analyses = Analysis.query.order_by(Analysis.created_at.desc()).all()
    return render_template("analysis/analyses.html", analyses=analyses, user=current_user)

@analysis_bp.route("/analysis/add", methods=["GET", "POST"])
@login_required
def analysis_add():
    """Add new analysis"""
    # Get available individuals for dropdown
    individuals = Individual.query.order_by(Individual.identity).all()

    if request.method == "POST":
        try:
            # Get form data
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            individual_id = request.form.get("individual_id", type=int)
            vcf_filename = request.form.get("vcf_filename", "").strip()
            genome_assembly = request.form.get("genome_assembly", "hg19")
            analysis_mode = request.form.get("analysis_mode", "FULL")
            frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Use lowercase genome assembly directly as enum
            genome_assembly_enum = GenomeAssembly(genome_assembly)

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
            # Create new analysis
            analysis = Analysis(
                name=name,
                description=description,
                individual_id=individual_id,
                vcf_filename=vcf_filename,
                genome_assembly=genome_assembly_enum,
                analysis_mode=analysis_mode,
                frequency_threshold=frequency_threshold,
                pathogenicity_threshold=pathogenicity_threshold,
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
    analysis = Analysis.query.get_or_404(analysis_id)
    individuals = Individual.query.order_by(Individual.identity).all()

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
            # Use lowercase genome assembly directly as enum
            genome_assembly = request.form.get("genome_assembly", "hg19")
            analysis.genome_assembly = GenomeAssembly(genome_assembly)
            analysis.analysis_mode = request.form.get("analysis_mode", "FULL")
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
    analysis = Analysis.query.get_or_404(analysis_id)

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

@analysis_bp.route("/analysis/<int:analysis_id>/run", methods=["GET", "POST"])
@login_required
def analysis_run(analysis_id):
    """Run analysis and show execution status"""
    analysis = Analysis.query.get_or_404(analysis_id)

    if request.method == "POST":
        # Start the analysis job
        if analysis.status in [TaskStatus.PENDING, TaskStatus.FAILED]:
            try:
                # Update status to running
                analysis.status = TaskStatus.RUNNING
                analysis.started_at = datetime.utcnow()
                analysis.error_message = None
                db.session.commit()

                # Start background job
                thread = threading.Thread(target=run_exomiser_analysis, args=(analysis_id,))
                thread.daemon = True
                thread.start()

                flash("Analysis started successfully", "success")
                return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

            except Exception as e:
                db.session.rollback()
                flash(f"Error starting analysis: {str(e)}", "error")
                return render_template("analysis/run.html", analysis=analysis, user=current_user)
        else:
            flash("Analysis is already running or completed", "warning")

    return render_template("analysis/run.html", analysis=analysis, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/results")
@login_required
def analysis_results(analysis_id):
    """Redirect to raw HTML results"""
    analysis = Analysis.query.get_or_404(analysis_id)

    if analysis.status != TaskStatus.COMPLETED:
        flash("Analysis not completed yet", "warning")
        return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

    # Redirect directly to the HTML content (no layout)
    return redirect(url_for("analysis.analysis_html", analysis_id=analysis_id))

@analysis_bp.route("/analysis/<int:analysis_id>/rerun", methods=["POST"])
@login_required
def analysis_rerun(analysis_id):
    """Rerun an existing analysis with the same parameters"""
    analysis = Analysis.query.get_or_404(analysis_id)

    try:
        # Reset analysis status and clear previous results
        analysis.status = TaskStatus.PENDING
        analysis.started_at = None
        analysis.completed_at = None
        analysis.error_message = None
        analysis.output_html = None
        analysis.updated_by = current_user.id

        db.session.commit()

        # Start the analysis in background
        thread = threading.Thread(target=run_exomiser_analysis, args=(analysis_id,))
        thread.daemon = True
        thread.start()

        return jsonify({"success": True, "message": "Analysis restarted successfully"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@analysis_bp.route("/analysis/<int:analysis_id>/output")
@login_required
def analysis_output(analysis_id):
    """Get current analysis output for polling"""
    if analysis_id in analysis_outputs:
        return jsonify({
            "success": True,
            "output": analysis_outputs[analysis_id],
            "line_count": len(analysis_outputs[analysis_id])
        })
    else:
        return jsonify({
            "success": True,
            "output": [],
            "line_count": 0
        })

@analysis_bp.route("/analysis/<int:analysis_id>/download")
@login_required
def analysis_download(analysis_id):
    """Download analysis results file"""
    analysis = Analysis.query.get_or_404(analysis_id)

    if analysis.status != TaskStatus.COMPLETED:
        flash("Analysis not completed yet", "warning")
        return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

    # Find the results file
    results_dir = "/opt/exomiser/ikdrc/results"
    results_file = None

    # First check if we have the path stored in the database
    if analysis.output_html and os.path.exists(analysis.output_html):
        results_file = analysis.output_html
    else:
        # Look for HTML results file using individual identity or analysis ID
        if os.path.exists(results_dir):
            for filename in os.listdir(results_dir):
                if filename.endswith(".html"):
                    # Check if filename contains individual identity or analysis ID
                    if (analysis.individual.identity in filename or
                        str(analysis_id) in filename or
                        filename.startswith(analysis.individual.identity)):
                        results_file = os.path.join(results_dir, filename)
                        break

    if not results_file or not os.path.exists(results_file):
        flash("Results file not found", "error")
        return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

    # Create download filename based on VCF filename format
    # Use the individual's VCF filename as base and replace .vcf with .html
    if analysis.individual.vcf_filename:
        base_name = os.path.splitext(analysis.individual.vcf_filename)[0]
        download_filename = f"{base_name}_analysis.html"
    else:
        download_filename = f"analysis_{analysis_id}_results.html"

    return send_file(results_file, as_attachment=True,
                    download_name=download_filename)

def run_exomiser_analysis(analysis_id):
    """Background function to run Exomiser analysis with simple output storage"""
    from main import app  # Import here to avoid circular imports

    try:
        with app.app_context():  # Need app context for database operations
            analysis = Analysis.query.get(analysis_id)
            if not analysis:
                return

            # Initialize output storage for this analysis
            analysis_outputs[analysis_id] = []

            # Update status to running
            analysis.status = TaskStatus.RUNNING
            analysis.started_at = datetime.utcnow()
            db.session.commit()

            analysis_outputs[analysis_id].append("Starting Exomiser analysis...")

            # Generate phenopacket YAML for the individual
            individual = analysis.individual
            phenopacket_content = individual.generate_phenopacket_yaml(
                creator="Exomiser Web Interface",
                genome_assembly=analysis.genome_assembly.value,
                vcf_filename=analysis.vcf_filename
            )

            # Save phenopacket to file in /opt/exomiser/ikdrc/phenopacket/
            phenopacket_dir = "/opt/exomiser/ikdrc/phenopacket"
            os.makedirs(phenopacket_dir, exist_ok=True)
            phenopacket_file = os.path.join(phenopacket_dir, f"analysis_{analysis_id}.yml")

            with open(phenopacket_file, 'w') as f:
                f.write(phenopacket_content)

            # Store the phenopacket path in the database for future reference
            analysis.phenopacket_path = phenopacket_file
            db.session.commit()

            analysis_outputs[analysis_id].append(f"Generated phenopacket: {phenopacket_file}")

            # Prepare Exomiser command following the instructions:
            cmd = [
                "java", "-Xmx4g", "-jar", "/opt/exomiser/exomiser-cli-14.1.0.jar",
                "--analysis", "/opt/exomiser/analysis.yml",
                "--sample", phenopacket_file
            ]

            analysis_outputs[analysis_id].append(f"Running command: {' '.join(cmd)}")

            # Start subprocess with real-time output capture
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                universal_newlines=True,
                bufsize=1,  # Line buffered
                cwd="/opt/exomiser"
            )

            # Capture output line by line
            while True:
                if process.stdout:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        line = output.strip()
                        if line:  # Only store non-empty lines
                            analysis_outputs[analysis_id].append(line)
                else:
                    # If no stdout, just wait for process to complete
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)

            # Wait for process to complete
            return_code = process.poll()

            # Update analysis status based on return code
            if return_code == 0:
                analysis.status = TaskStatus.COMPLETED
                analysis.completed_at = datetime.utcnow()
                analysis.error_message = None

                analysis_outputs[analysis_id].append("Analysis completed successfully!")

                # Set results directory path
                analysis.results_directory = "/opt/exomiser/ikdrc/results"

                # Try to find and set the output HTML file
                results_dir = "/opt/exomiser/ikdrc/results"
                if os.path.exists(results_dir):
                    for filename in os.listdir(results_dir):
                        if filename.endswith(".html") and individual.identity in filename:
                            analysis.output_html = os.path.join(results_dir, filename)
                            analysis_outputs[analysis_id].append(f"Results saved to: {filename}")
                            break
            else:
                analysis.status = TaskStatus.FAILED
                analysis.error_message = f"Exomiser process failed with return code {return_code}"
                analysis_outputs[analysis_id].append(f"Analysis failed with return code: {return_code}")

            db.session.commit()

            # Keep output in memory for a while after completion (30 minutes)
            def cleanup_output():
                time.sleep(1800)  # 30 minutes
                if analysis_id in analysis_outputs:
                    del analysis_outputs[analysis_id]

            cleanup_thread = threading.Thread(target=cleanup_output)
            cleanup_thread.daemon = True
            cleanup_thread.start()

    except Exception as e:
        with app.app_context():
            analysis = Analysis.query.get(analysis_id)
            if analysis:
                analysis.status = TaskStatus.FAILED
                analysis.error_message = f"Error running analysis: {str(e)}"
                db.session.commit()

                # Store error in output if storage exists
                if analysis_id in analysis_outputs:
                    analysis_outputs[analysis_id].append(f"Error: {str(e)}")
                    analysis_outputs[analysis_id].append("Analysis failed due to error")

@analysis_bp.route("/analysis/<int:analysis_id>/view")
@login_required
def analysis_view(analysis_id):
    """Redirect old view route to new run route"""
    return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

@analysis_bp.route("/analysis/<int:analysis_id>/html")
@login_required
def analysis_html(analysis_id):
    """Serve the raw HTML content directly"""
    analysis = Analysis.query.get_or_404(analysis_id)

    if analysis.status != TaskStatus.COMPLETED:
        return "<html><body><h2>Analysis not completed yet</h2></body></html>", 200

    # Find the results file
    results_dir = "/opt/exomiser/ikdrc/results"
    results_file = None

    # First check if we have the path stored in the database
    if analysis.output_html and os.path.exists(analysis.output_html):
        results_file = analysis.output_html
    else:
        # Look for HTML results file using individual identity or analysis ID
        if os.path.exists(results_dir):
            for filename in os.listdir(results_dir):
                if filename.endswith(".html"):
                    # Check if filename contains individual identity or analysis ID
                    if (analysis.individual.identity in filename or
                        str(analysis_id) in filename or
                        filename.startswith(analysis.individual.identity)):
                        results_file = os.path.join(results_dir, filename)
                        break

    if not results_file or not os.path.exists(results_file):
        return "<html><body><h2>Results file not found</h2></body></html>", 404

    # Read and return the HTML file content
    with open(results_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}

@analysis_bp.route("/results")
@login_required
def results():
    """Results page - shows analysis results and status"""
    analyses = Analysis.query.order_by(Analysis.updated_at.desc()).all()
    return render_template("analysis/results.html", analyses=analyses, user=current_user)
