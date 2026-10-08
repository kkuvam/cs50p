# File: app/analysis.py
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from safe_log import log_error
from models import Analysis, GenomeAssembly, Individual, TaskStatus, db
from werkzeug.utils import secure_filename

analysis_bp = Blueprint("analysis", __name__)

# Exomiser reports are untrusted HTML: sandbox them into an opaque origin (no allow-same-origin)
REPORT_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads"
    ),
    "X-Content-Type-Options": "nosniff",
}

RESULTS_BASE = "/opt/exomiser/ikdrc/results"


def report_file(analysis):
    """Return the stored report path if it exists inside RESULTS_BASE, else None.

    Never searches the results folder: only the path stored for this analysis counts."""
    path = analysis.output_html
    if not path:
        return None
    real = os.path.realpath(path)
    base = os.path.realpath(RESULTS_BASE)
    if os.path.commonpath([base, real]) != base or real == base or not os.path.isfile(real):
        return None
    return real


# File-based log storage — shared across all Gunicorn workers via the persistent volume
_LOG_DIR = "/opt/logs"


def _log_path(analysis_id):
    return os.path.join(_LOG_DIR, f"analysis_{analysis_id}.log")


def _append_log(analysis_id, line):
    os.makedirs(_LOG_DIR, exist_ok=True)
    with open(_log_path(analysis_id), "a") as f:
        f.write(line + "\n")


def _read_log(analysis_id):
    path = _log_path(analysis_id)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return [l.rstrip("\n") for l in f if l.strip()]


def _delete_log(analysis_id):
    path = _log_path(analysis_id)
    if os.path.exists(path):
        os.remove(path)


def _pid_path(analysis_id):
    """Run file: {"token", "worker" (pid of the app worker owning the run), "java"}."""
    return os.path.join(_LOG_DIR, f"analysis_{analysis_id}.pid")


def _write_run_file(analysis_id, data):
    os.makedirs(_LOG_DIR, exist_ok=True)
    tmp = _pid_path(analysis_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _pid_path(analysis_id))


def _read_run_file(analysis_id):
    try:
        with open(_pid_path(analysis_id)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _remove_run_file(analysis_id, token=None):
    """Remove the run file; if token is given, only when it still belongs to that run."""
    if token is not None:
        run = _read_run_file(analysis_id)
        if run is None or run.get("token") != token:
            return
    try:
        os.remove(_pid_path(analysis_id))
    except OSError:
        pass


def _is_exomiser_pid(pid):
    """True if pid is a live process whose command line is the Exomiser CLI (guards PID reuse)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"exomiser-cli" in f.read()
    except OSError:
        return False


def _proc_start(pid):
    """Process start time in clock ticks since boot (field 22 of /proc/<pid>/stat), or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _worker_alive(pid, start=None):
    """True if pid is the same worker process that started the run (pids repeat after a restart)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.path.exists("/proc/self/stat"):
        current = _proc_start(pid)
        return current is not None and (start is None or current == start)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _force_kill(pgid):
    # If the group leader still exists it must be Exomiser (PID reuse guard); if it is gone,
    # surviving group members (java children) are still killed
    if os.path.exists(f"/proc/{pgid}") and not _is_exomiser_pid(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _terminate_group(pgid):
    """SIGTERM the process group, then SIGKILL it 30 s later if Exomiser is still there."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return False
    t = threading.Timer(30, _force_kill, args=(pgid,))
    t.daemon = True
    t.start()
    return True


def _kill_run(analysis_id):
    """Stop the Exomiser process group of a run. Returns True if a signal was sent."""
    run = _read_run_file(analysis_id)
    java = run.get("java") if run else None
    if not isinstance(java, int) or not _is_exomiser_pid(java):
        return False
    return _terminate_group(java)


def _is_running(analysis_id):
    status = db.session.query(Analysis.status).filter(Analysis.id == analysis_id).scalar()
    return status == TaskStatus.RUNNING


def _stop_process(process):
    """Make sure the Exomiser child is gone and reaped (SIGTERM, then SIGKILL after 30 s)."""
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()


def _reap_stale_runs():
    """Fail RUNNING analyses whose owning app worker is gone (e.g. after a restart)."""
    try:
        now = datetime.utcnow()
        max_age = timedelta(hours=_timeout_hours(), minutes=15)
        for a in Analysis.query.filter_by(status=TaskStatus.RUNNING, is_deleted=False).all():
            run = _read_run_file(a.id)
            if run is None:
                if a.started_at is not None and a.started_at >= now - timedelta(minutes=10):
                    continue
                status = TaskStatus.CANCELLED
                msg = "Interrupted before this version tracked runs"
            elif not _worker_alive(run.get("worker"), run.get("worker_start")):
                status = TaskStatus.FAILED
                msg = "Interrupted: the app restarted during the run"
            elif a.started_at is not None and a.started_at < now - max_age:
                status = TaskStatus.FAILED
                msg = "Interrupted: exceeded the maximum run time"
            else:
                continue
            updated = Analysis.query.filter(
                Analysis.id == a.id, Analysis.status == TaskStatus.RUNNING
            ).update(
                {
                    Analysis.status: status,
                    Analysis.error_message: msg,
                    Analysis.completed_at: now,
                },
                synchronize_session=False,
            )
            if updated and run is not None:
                java = run.get("java")
                if isinstance(java, int) and _is_exomiser_pid(java):
                    _terminate_group(java)
                _remove_run_file(a.id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log_error(current_app.logger, "Failed to reap stale analyses", e)

# ===== ANALYSIS CRUD ROUTES =====
@analysis_bp.route("/analyses")
@login_required
def analysis_list():
    """Analysis list page - shows all analyses for all users"""
    _reap_stale_runs()
    analyses = Analysis.query.filter_by(is_deleted=False).order_by(Analysis.created_at.desc()).all()
    return render_template("analysis/analyses.html", analyses=analyses, user=current_user)

@analysis_bp.route("/analysis/add", methods=["GET", "POST"])
@login_required
def analysis_add():
    """Add new analysis"""
    # Get available individuals for dropdown
    individuals = Individual.query.filter_by(is_deleted=False).order_by(Individual.identity).all()

    if request.method == "POST":
        try:
            import json as _json

            # Get form data
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            individual_id = request.form.get("individual_id", type=int)
            genome_assembly = request.form.get("genome_assembly", "hg19")
            if genome_assembly != "hg19":
                flash("Only hg19 is available on this server", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)
            analysis_mode = request.form.get("analysis_mode", "FULL")
            frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Parse HPO terms from hidden JSON field
            hpo_terms_raw = request.form.get("hpo_terms", "")
            try:
                hpo_terms = _json.loads(hpo_terms_raw) if hpo_terms_raw else []
            except (_json.JSONDecodeError, TypeError):
                hpo_terms = []

            genome_assembly_enum = GenomeAssembly(genome_assembly)

            # Validation
            if not name:
                flash("Analysis name is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            if not individual_id:
                flash("Individual selection is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            if not hpo_terms:
                flash("At least one HPO term is required", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            # Verify individual exists
            individual = Individual.query.filter_by(id=individual_id, is_deleted=False).first()
            if not individual:
                flash("Selected individual not found", "error")
                return render_template("analysis/add.html", individuals=individuals, user=current_user)

            analysis = Analysis(
                name=name,
                description=description,
                individual_id=individual_id,
                genome_assembly=genome_assembly_enum,
                analysis_mode=analysis_mode,
                frequency_threshold=frequency_threshold,
                pathogenicity_threshold=pathogenicity_threshold,
                hpo_terms=hpo_terms,
                created_by=current_user.id,
                updated_by=current_user.id
            )

            db.session.add(analysis)
            db.session.commit()

            flash(f"Analysis '{name}' created successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            log_error(current_app.logger, "Failed to create analysis", e)
            flash("Error creating analysis. Please try again or contact an admin.", "error")
            return render_template("analysis/add.html", individuals=individuals, user=current_user)

    return render_template("analysis/add.html", individuals=individuals, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/edit", methods=["GET", "POST"])
@login_required
def analysis_edit(analysis_id):
    """Edit existing analysis"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()
    individuals = Individual.query.filter_by(is_deleted=False).order_by(Individual.identity).all()

    if request.method == "POST":
        try:
            import json as _json

            # Update fields (only allow editing if analysis is not running)
            if analysis.status in [TaskStatus.RUNNING]:
                flash("Cannot edit running analysis", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

            genome_assembly = request.form.get("genome_assembly", "hg19")
            if genome_assembly != "hg19" and genome_assembly != analysis.genome_assembly.value:
                flash("Only hg19 is available on this server", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

            analysis.name = request.form.get("name", "").strip()
            analysis.description = request.form.get("description", "").strip() or None
            analysis.individual_id = request.form.get("individual_id", type=int)
            analysis.genome_assembly = GenomeAssembly(genome_assembly)
            analysis.analysis_mode = request.form.get("analysis_mode", "FULL")
            analysis.frequency_threshold = request.form.get("frequency_threshold", type=float) or 1.0
            analysis.pathogenicity_threshold = request.form.get("pathogenicity_threshold", type=float) or 0.5

            # Update HPO terms
            hpo_terms_raw = request.form.get("hpo_terms", "")
            try:
                analysis.hpo_terms = _json.loads(hpo_terms_raw) if hpo_terms_raw else []
            except (_json.JSONDecodeError, TypeError):
                analysis.hpo_terms = []

            # Update audit trail
            analysis.updated_by = current_user.id

            # Validation
            if not analysis.name:
                flash("Analysis name is required", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

            if not analysis.individual_id:
                flash("Individual selection is required", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

            # Verify individual exists
            individual = Individual.query.filter_by(id=analysis.individual_id, is_deleted=False).first()
            if not individual:
                flash("Selected individual not found", "error")
                return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

            # Reset status to pending if it was failed/cancelled (allow restart via edit)
            if analysis.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                analysis.status = TaskStatus.PENDING
                analysis.error_message = None

            db.session.commit()
            flash(f"Analysis '{analysis.name}' updated successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            log_error(current_app.logger, "Failed to update analysis", e)
            flash("Error updating analysis. Please try again or contact an admin.", "error")
            return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

    return render_template("analysis/edit.html", analysis=analysis, individuals=individuals, user=current_user, now=datetime.utcnow())

@analysis_bp.route("/analysis/<int:analysis_id>/cancel", methods=["POST"])
@login_required
def analysis_cancel(analysis_id):
    """Cancel a RUNNING analysis and stop its Exomiser process."""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if analysis.status != TaskStatus.RUNNING:
        flash("Only running analyses can be cancelled.", "warning")
        return redirect(url_for("analysis.analysis_edit", analysis_id=analysis_id))

    analysis.status = TaskStatus.CANCELLED
    analysis.completed_at = datetime.utcnow()
    analysis.error_message = "Cancelled by user"
    analysis.updated_by = current_user.id
    db.session.commit()

    if _kill_run(analysis_id):
        flash("Analysis cancelled and the Exomiser process was stopped.", "success")
    else:
        flash("Analysis cancelled. No running Exomiser process was found to stop.", "success")
    return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

@analysis_bp.route("/analysis/<int:analysis_id>/delete", methods=["GET", "POST"])
@login_required
def analysis_delete(analysis_id):
    """Soft-delete analysis with confirmation"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if request.method == "POST":
        try:
            # Check if analysis is running
            if analysis.status == TaskStatus.RUNNING:
                flash("Cannot delete running analysis", "error")
                return render_template("analysis/delete.html", analysis=analysis, user=current_user)

            analysis_name = analysis.name
            analysis.is_deleted = True
            analysis.deleted_at = datetime.utcnow()
            db.session.commit()

            flash(f"Analysis '{analysis_name}' deleted successfully", "success")
            return redirect(url_for("analysis.analysis_list"))

        except Exception as e:
            db.session.rollback()
            log_error(current_app.logger, "Failed to delete analysis", e)
            flash("Error deleting analysis. Please try again or contact an admin.", "error")
            return render_template("analysis/delete.html", analysis=analysis, user=current_user)

    return render_template("analysis/delete.html", analysis=analysis, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/run", methods=["GET", "POST"])
@login_required
def analysis_run(analysis_id):
    """Run analysis and show execution status"""
    if request.method == "GET":
        _reap_stale_runs()
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if request.method == "POST":
        # Start the analysis job
        try:
            # Claim the run atomically so concurrent requests cannot start it twice
            claimed = Analysis.query.filter(
                Analysis.id == analysis_id,
                Analysis.is_deleted == False,  # noqa: E712
                Analysis.status.in_([TaskStatus.PENDING, TaskStatus.FAILED]),
            ).update(
                {
                    Analysis.status: TaskStatus.RUNNING,
                    Analysis.started_at: datetime.utcnow(),
                    Analysis.completed_at: None,
                    Analysis.error_message: None,
                },
                synchronize_session=False,
            )
            db.session.commit()
            if claimed != 1:
                flash("Analysis is already running or completed", "warning")
                return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

            # Run file (overwrites any stale one) tells the reaper which worker owns the run
            token = uuid.uuid4().hex
            _write_run_file(
                analysis_id,
                {
                    "token": token,
                    "worker": os.getpid(),
                    "worker_start": _proc_start(os.getpid()),
                    "java": None,
                },
            )

            # Start background job
            thread = threading.Thread(target=run_exomiser_analysis, args=(analysis_id, token))
            thread.daemon = True
            thread.start()

            flash("Analysis started successfully", "success")
            return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

        except Exception as e:
            db.session.rollback()
            log_error(current_app.logger, "Failed to start analysis", e)
            try:
                # The claim may already be committed; do not leave the row RUNNING
                Analysis.query.filter(
                    Analysis.id == analysis_id, Analysis.status == TaskStatus.RUNNING
                ).update(
                    {
                        Analysis.status: TaskStatus.FAILED,
                        Analysis.error_message: "Could not start the analysis",
                        Analysis.completed_at: datetime.utcnow(),
                    },
                    synchronize_session=False,
                )
                db.session.commit()
            except Exception as e2:
                db.session.rollback()
                log_error(current_app.logger, "Failed to reset analysis after start error", e2)
            flash("Error starting analysis. Please try again or contact an admin.", "error")
            return render_template("analysis/run.html", analysis=analysis, user=current_user)

    return render_template("analysis/run.html", analysis=analysis, user=current_user)

@analysis_bp.route("/analysis/<int:analysis_id>/results")
@login_required
def analysis_results(analysis_id):
    """Redirect to raw HTML results"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if analysis.status != TaskStatus.COMPLETED:
        flash("Analysis not completed yet", "warning")
        return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

    # Redirect directly to the HTML content (no layout)
    return redirect(url_for("analysis.analysis_html", analysis_id=analysis_id))

@analysis_bp.route("/analysis/<int:analysis_id>/output")
@login_required
def analysis_output(analysis_id):
    """Get current analysis output for polling"""
    Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()
    lines = _read_log(analysis_id)
    return jsonify({
        "success": True,
        "output": lines,
        "line_count": len(lines)
    })

@analysis_bp.route("/analysis/<int:analysis_id>/status")
@login_required
def analysis_status(analysis_id):
    """Get current analysis status for polling"""
    _reap_stale_runs()
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()
    return jsonify({
        "success": True,
        "status": analysis.status.value,
        "started_at": analysis.started_at.isoformat() if analysis.started_at else None,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        "error_message": analysis.error_message
    })

@analysis_bp.route("/analysis/<int:analysis_id>/download")
@login_required
def analysis_download(analysis_id):
    """Download analysis results file"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if analysis.status != TaskStatus.COMPLETED:
        flash("Analysis not completed yet", "warning")
        return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

    results_file = report_file(analysis)
    if not results_file:
        flash("Report file not found for this analysis", "error")
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

def _results_output_dir(results_base, analysis_id, analysis_name):
    """Return the per-analysis results folder, guaranteed to be inside results_base.

    Folder name is "<id>_<sanitized lowercase name>" (or "analysis_<id>" if the name
    sanitizes to nothing). Raises ValueError if the resolved path escapes
    results_base.
    """
    safe_name = secure_filename(analysis_name or "").lower()
    folder_name = f"{analysis_id}_{safe_name}" if safe_name else f"analysis_{analysis_id}"
    output_dir = os.path.join(results_base, folder_name)
    base_real = os.path.realpath(results_base)
    out_real = os.path.realpath(output_dir)
    if os.path.commonpath([base_real, out_real]) != base_real or out_real == base_real:
        raise ValueError(f"Results folder '{folder_name}' resolves outside the results directory")
    return output_dir

def _timeout_hours():
    try:
        return float(os.environ.get("EXOMISER_TIMEOUT_HOURS", "2"))
    except ValueError:
        return 2.0


def run_exomiser_analysis(analysis_id, token):
    """Background function to run Exomiser analysis with simple output storage.

    The route has already claimed the run (status RUNNING) and written the run file."""
    from main import app  # Import here to avoid circular imports

    process = None
    timer = None
    try:
        with app.app_context():  # Need app context for database operations
            analysis = Analysis.query.get(analysis_id)
            if not analysis:
                return

            individual = analysis.individual
            analysis_name = analysis.name
            # Clear any previous log file and stale results for this analysis
            _delete_log(analysis_id)
            analysis.log = None
            analysis.output_html = None
            analysis.output_vcf = None
            db.session.commit()

            _append_log(analysis_id, "Starting Exomiser analysis...")

            # Generate phenopacket YAML from the analysis (HPO terms now live here)
            phenopacket_content = analysis.generate_phenopacket_yaml(
                creator="Exomiser Web Interface"
            )

            # Save phenopacket to file in /opt/exomiser/ikdrc/phenopacket/
            phenopacket_dir = "/opt/exomiser/ikdrc/phenopacket"
            os.makedirs(phenopacket_dir, exist_ok=True)
            phenopacket_file = os.path.join(phenopacket_dir, f"analysis_{analysis_id}.yml")

            with open(phenopacket_file, 'w') as f:
                f.write(phenopacket_content)

            _append_log(analysis_id, f"Generated phenopacket: {phenopacket_file}")

            # Exomiser writes to a known per-run folder and filename (CLI flags override
            # outputDirectory in analysis.yml), so no scanning for reports is needed
            results_base = RESULTS_BASE
            output_dir = _results_output_dir(results_base, analysis_id, analysis_name)
            os.makedirs(output_dir, exist_ok=True)
            out_name = f"{secure_filename(individual.identity or '') or 'sample'}-exomiser"
            started_ts = time.time()  # only outputs written after this count

            # Prepare Exomiser command following the instructions:
            cmd = [
                "java", "-Xmx4g", "-jar", "/opt/exomiser/exomiser-cli-14.1.0.jar",
                "--analysis", "/opt/exomiser/analysis.yml",
                "--sample", phenopacket_file,
                "--output-directory", output_dir,
                "--output-filename", out_name,
            ]

            _append_log(analysis_id, f"Running command: {' '.join(cmd)}")

            # A cancel may have landed before we got here
            if not _is_running(analysis_id):
                _append_log(analysis_id, "Run was cancelled before Exomiser started")
                return

            # Start subprocess in its own session so the whole process group can be signalled
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                universal_newlines=True,
                bufsize=1,  # Line buffered
                cwd="/opt/exomiser",
                start_new_session=True,
            )
            run = _read_run_file(analysis_id)
            if run is not None and run.get("token") == token:
                run["java"] = process.pid
                _write_run_file(analysis_id, run)
            # A cancel between the check above and the pid write could not see the process
            if not _is_running(analysis_id):
                _terminate_group(process.pid)

            # Kill the run if it exceeds the timeout
            timeout_hours = _timeout_hours()
            timed_out = threading.Event()

            def on_timeout():
                timed_out.set()
                _terminate_group(process.pid)

            timer = threading.Timer(timeout_hours * 3600, on_timeout)
            timer.daemon = True
            timer.start()

            # Capture output line by line
            while True:
                if process.stdout:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        line = output.strip()
                        if line:  # Only store non-empty lines
                            _append_log(analysis_id, line)
                else:
                    # If no stdout, just wait for process to complete
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)

            # Wait for process to complete
            return_code = process.wait()
            timer.cancel()

            output_html = None
            output_vcf = None
            error_message = None

            if timed_out.is_set():
                new_status = TaskStatus.FAILED
                error_message = f"Timed out after {timeout_hours:g} h"
                _append_log(analysis_id, f"Timed out after {timeout_hours:g} h; Exomiser was stopped")
            elif return_code == 0:
                html_path = os.path.join(output_dir, out_name + ".html")
                if os.path.isfile(html_path) and os.path.getmtime(html_path) >= started_ts - 2:
                    output_html = html_path
                    _append_log(analysis_id, f"HTML saved to: {html_path}")
                    for vcf_name in (out_name + ".vcf.gz", out_name + ".vcf"):
                        vcf_path = os.path.join(output_dir, vcf_name)
                        if (
                            os.path.isfile(vcf_path)
                            and os.path.getmtime(vcf_path) >= started_ts - 2
                        ):
                            output_vcf = vcf_path
                            _append_log(analysis_id, f"VCF saved to: {vcf_path}")
                            break
                    else:
                        _append_log(analysis_id, "No VCF output found in results folder")

                if output_html and os.path.isfile(output_html):
                    new_status = TaskStatus.COMPLETED
                    _append_log(analysis_id, "Analysis completed successfully!")
                else:
                    output_html = None
                    new_status = TaskStatus.FAILED
                    error_message = "Exomiser finished but produced no HTML report"
                    _append_log(analysis_id, error_message)
            else:
                new_status = TaskStatus.FAILED
                error_message = f"Exomiser process failed with return code {return_code}"
                _append_log(analysis_id, f"Analysis failed with return code: {return_code}")

            # Conditional write: never overwrite a CANCELLED (or reaped) status
            updated = Analysis.query.filter(
                Analysis.id == analysis_id, Analysis.status == TaskStatus.RUNNING
            ).update(
                {
                    Analysis.status: new_status,
                    Analysis.error_message: error_message,
                    Analysis.output_html: output_html,
                    Analysis.output_vcf: output_vcf,
                    Analysis.completed_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
            if not updated:
                _append_log(analysis_id, "Status was changed during the run; result not applied")
            # Store complete log in database for debugging
            Analysis.query.filter(Analysis.id == analysis_id).update(
                {Analysis.log: "\n".join(_read_log(analysis_id))}, synchronize_session=False
            )
            db.session.commit()

            # Delete the temp log file after 30 minutes (results are now in the DB)
            def cleanup_output():
                time.sleep(1800)  # 30 minutes
                _delete_log(analysis_id)

            cleanup_thread = threading.Thread(target=cleanup_output)
            cleanup_thread.daemon = True
            cleanup_thread.start()

    except Exception as e:
        _stop_process(process)
        with app.app_context():
            db.session.rollback()
            log_error(app.logger, f"Analysis {analysis_id} failed", e)
            _append_log(analysis_id, f"Error: {type(e).__name__}")
            failed = Analysis.query.filter(
                Analysis.id == analysis_id, Analysis.status == TaskStatus.RUNNING
            ).update(
                {
                    Analysis.status: TaskStatus.FAILED,
                    Analysis.error_message: f"Error running analysis: {type(e).__name__}",
                    Analysis.completed_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
            if failed:
                _append_log(analysis_id, "Analysis failed due to error")
            Analysis.query.filter(Analysis.id == analysis_id).update(
                {Analysis.log: "\n".join(_read_log(analysis_id))}, synchronize_session=False
            )
            db.session.commit()
    finally:
        if timer is not None:
            timer.cancel()
        _stop_process(process)
        _remove_run_file(analysis_id, token)

@analysis_bp.route("/analysis/<int:analysis_id>/view")
@login_required
def analysis_view(analysis_id):
    """Redirect old view route to new run route"""
    return redirect(url_for("analysis.analysis_run", analysis_id=analysis_id))

@analysis_bp.route("/analysis/<int:analysis_id>/html")
@login_required
def analysis_html(analysis_id):
    """Serve the raw HTML content directly"""
    analysis = Analysis.query.filter_by(id=analysis_id, is_deleted=False).first_or_404()

    if analysis.status != TaskStatus.COMPLETED:
        return "<html><body><h2>Analysis not completed yet</h2></body></html>", 200

    results_file = report_file(analysis)
    if not results_file:
        return "<html><body><h2>Report file not found for this analysis</h2></body></html>", 404

    # Read and return the HTML file content
    with open(results_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    return html_content, 200, {
        'Content-Type': 'text/html; charset=utf-8',
        **REPORT_HEADERS,
    }

@analysis_bp.route("/results")
@login_required
def results():
    """Results page - shows analysis results and status"""
    analyses = Analysis.query.filter_by(is_deleted=False).order_by(Analysis.updated_at.desc()).all()
    return render_template("analysis/results.html", analyses=analyses, user=current_user)
