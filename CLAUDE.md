# CLAUDE.md — Exomiser Web Application

## Project Overview

**Exomiser App** is a Flask-based web interface for running [Exomiser](https://github.com/exomiser/Exomiser) genomic variant interpretation on VCF files. It is designed for clinical/research use — lab staff upload a patient VCF file, annotate the patient with HPO (Human Phenotype Ontology) phenotype terms, then trigger an Exomiser analysis job. Results are presented as an HTML report in the browser.

The project was originally a CS50P final project and is being actively developed for real-world use at IKDRC (Institute of Kidney Diseases and Research Centre).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask 2.2+, Flask-Login, Flask-SQLAlchemy |
| Database | SQLite (via SQLAlchemy, stored at `/opt/instance/app.db`) |
| Frontend | Jinja2 HTML templates, vanilla JS, Select2 (vendor-bundled) |
| Analysis Engine | Exomiser CLI 14.1.0 (Java, invoked via `subprocess`) |
| Container | Docker (single container: Amazon Corretto 21 base + Python) |
| Production server | Gunicorn (2 workers, 4 threads, port 8000) |

---

## Running the Application

### Docker (primary method)

```bash
docker compose up --build
```

The app is served at `http://localhost:8000` (port configurable via `PORT` env var).

### Local development (without Docker)

```bash
pip install -r requirements.txt
cd app
python main.py   # runs Flask dev server on port 8000
```

The app expects the database directory at `/opt/instance/`. When running locally this is created automatically.

### Current status check

```bash
docker compose ps
curl -o /dev/null -w "%{http_code}" http://localhost:8000/
# Expected: 302 (redirect to /login) — confirms app is healthy
```

---

## Architecture

### Directory Layout

```
cs50p/
├── app/                        # Flask application (mounted into container as /opt/app)
│   ├── main.py                 # App factory — Flask init, db, login manager, blueprint registration
│   ├── models.py               # SQLAlchemy models: User, Individual, Analysis
│   ├── auth.py                 # Blueprint: /login, /register, /logout, /change-password
│   ├── routes.py               # Blueprint: dashboard (/), admin (/admin/*), API (/api/*), report serving
│   ├── individual.py           # Blueprint: /individuals, /individual/<id> CRUD + VCF upload
│   ├── analysis.py             # Blueprint: /analyses, /analysis/<id> CRUD + Exomiser job runner
│   ├── create_admin.py         # One-off script to seed admin user
│   ├── templates/              # Jinja2 templates
│   │   ├── layout.html         # Base layout (navbar, sidebar, flash messages)
│   │   ├── index.html          # Dashboard (stats, charts, recent results)
│   │   ├── login.html / register.html / change_password.html
│   │   ├── individual/         # add, edit, view, delete, individuals list, phenopacket
│   │   ├── analysis/           # add, edit, run, delete, results, analyses list
│   │   ├── admin/              # users list, add/edit/delete user, reset password
│   │   ├── docs/               # Documentation pages
│   │   └── help/               # FAQ and support pages
│   └── static/
│       ├── css/                # App stylesheets
│       ├── js/                 # App JavaScript
│       ├── img/                # Images/icons
│       └── vendors/select2-4.1.0-rc.0/   # Bundled Select2 library
├── compose/
│   ├── Dockerfile              # Amazon Corretto 21 + Python; downloads Exomiser CLI at build time
│   ├── analysis.yml            # Exomiser analysis configuration (passed to CLI with --analysis)
│   └── application.properties  # Exomiser application.properties (data dir config)
├── docker-compose.yml          # Single-service compose file
├── instance/                   # Persistent SQLite DB (mounted at /opt/instance)
├── ikdrc/                      # Persistent data dir (mounted at /opt/exomiser/ikdrc)
│   ├── vcf/                    # Uploaded VCF files (timestamped: <ts>_<original>.vcf)
│   ├── phenopacket/            # Generated phenopacket YAML files (analysis_<id>.yml)
│   └── results/                # Exomiser output HTML and VCF results
├── app.sql                     # Reference SQL schema + seed data (not used at runtime)
├── requirements.txt            # Python dependencies
├── .env / .env.example         # Environment variable configuration
└── monitor_analysis.sh         # Shell script to tail running analysis logs
```

### Blueprints and Route Map

| Blueprint | File | Key Routes |
|-----------|------|-----------|
| `auth` | auth.py | `GET/POST /login`, `GET/POST /register`, `GET /logout`, `GET/POST /change-password` |
| `routes` | routes.py | `GET /` (dashboard), `GET /admin/users`, `GET/POST /admin/users/<id>/*`, `GET /api/search/analyses`, `GET /analysis/<id>/report` |
| `individual` | individual.py | `GET /individuals`, `GET/POST /individual/add`, `GET /individual/<id>`, `GET/POST /individual/<id>/edit`, `GET/POST /individual/<id>/delete`, `GET /individual/<id>/download_vcf`, `GET /api/individual/<id>/vcf-info` |
| `analysis` | analysis.py | `GET /analyses`, `GET/POST /analysis/add`, `GET/POST /analysis/<id>/edit`, `GET/POST /analysis/<id>/delete`, `GET/POST /analysis/<id>/run`, `GET /analysis/<id>/status` (JSON), `GET /analysis/<id>/output` (JSON), `GET /analysis/<id>/results`, `GET /analysis/<id>/html`, `GET /analysis/<id>/download`, `GET /results` |

---

## Data Models

### User
- Email/password auth (Werkzeug PBKDF2 hashing)
- `is_active` — new registrations default to `False`; admin must activate
- `is_admin` — grants access to `/admin/*` routes

### Individual
Represents a patient/sample. Key fields:
- `identity` — unique patient ID (e.g. `P0001`), used as Exomiser sample name
- `hpo_terms` — JSON array of `{"id": "HP:0001250", "label": "Seizures"}` objects
- `vcf_filename` — original upload filename (for display/download)
- `vcf_file_path` — server path: `/opt/exomiser/ikdrc/vcf/<timestamp>_<filename>`
- `phenopacket_yaml` — auto-generated GA4GH Phenopacket v1.0 YAML (regenerated on save)

### Analysis
Represents one Exomiser run. Key fields:
- `individual_id` — FK to Individual
- `vcf_filename` — VCF filename passed to Exomiser (auto-populated from individual)
- `genome_assembly` — `hg19` or `hg38`
- `analysis_mode` — `PASS_ONLY` or `FULL`
- `status` — `PENDING` → `RUNNING` → `COMPLETED` / `FAILED` / `CANCELLED`
- `output_html` — full path to Exomiser HTML report
- `log` — captured stdout/stderr from the Exomiser process

---

## Analysis Execution Flow

1. User creates an **Individual** record, uploads a VCF file.
2. User creates an **Analysis** record, selects the individual, confirms VCF filename and genome assembly.
3. User navigates to `/analysis/<id>/run` and clicks **Run**.
4. Flask sets status = `RUNNING` and spawns a **daemon thread** (`run_exomiser_analysis`).
5. The thread:
   a. Generates a Phenopacket YAML from the individual record → saves to `/opt/exomiser/ikdrc/phenopacket/analysis_<id>.yml`
   b. Invokes: `java -Xmx4g -jar /opt/exomiser/exomiser-cli-14.1.0.jar --analysis /opt/exomiser/analysis.yml --sample <phenopacket_file>`
   c. Captures stdout/stderr line-by-line into `analysis_outputs[analysis_id]` (in-memory dict).
   d. On success (exit code 0): scans `/opt/exomiser/ikdrc/results/` for `<identity>*.html`, renames to `<identity>-exomiser.html`, stores path in `analysis.output_html`.
   e. Updates `analysis.status` and saves `analysis.log` to DB.
6. The run page polls `/analysis/<id>/status` and `/analysis/<id>/output` every few seconds for live updates.
7. Completed report served at `/analysis/<id>/html` (raw HTML) or `/analysis/<id>/report` (send_file).

**Important constraints:**
- Exomiser data directory must be mounted at `/opt/exomiser/data` (volume: `/Volumes/Extreme/Exomiser/data`)
- Exomiser CLI JAR is at `/opt/exomiser/exomiser-cli-14.1.0.jar` (downloaded at image build time)
- No job queue — analyses run in background threads; gunicorn worker restart will lose in-progress jobs

---

## User Registration Flow

New users register via `/register` — accounts are created with `is_active=False`. An admin must log in to `/admin/users` and activate the account before the user can log in.

Default admin credentials (seeded in `app.sql`):
- Email: `admin@exomiser.local`
- Password: `admin123`

---

## Environment Variables

See `.env.example`. Key variables:

| Variable | Default | Notes |
|----------|---------|-------|
| `SECRET_KEY` | `dev-secret-change-in-production` | Change for production |
| `DATABASE_URL` | `sqlite:////opt/instance/app.db` | SQLite path |
| `PORT` | `8000` | Host port for Docker |
| `FLASK_ENV` | `development` | Set to `production` in prod |
| `MAX_MEMORY` | `4g` | JVM max heap for Exomiser |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker count |
| `GUNICORN_THREADS` | `4` | Threads per worker |
| `EXOMISER_VERSION` | `14.1.0` | Exomiser CLI version (build arg) |

---

## Key External Paths (inside container)

| Path | Purpose |
|------|---------|
| `/opt/app` | Flask application code (mounted from `./app`) |
| `/opt/instance/app.db` | SQLite database (persistent volume) |
| `/opt/exomiser/` | Exomiser CLI installation root |
| `/opt/exomiser/data/` | Exomiser variant databases (large, mounted from external drive) |
| `/opt/exomiser/ikdrc/vcf/` | Uploaded VCF files |
| `/opt/exomiser/ikdrc/phenopacket/` | Generated phenopacket YAMLs |
| `/opt/exomiser/ikdrc/results/` | Exomiser output HTML/VCF results |
| `/opt/exomiser/analysis.yml` | Exomiser analysis configuration |
| `/opt/exomiser/application.properties` | Exomiser data directory config |

---

## Known Issues / Notes

- `app.sql` sample data inserts into a `tasks` table that no longer exists (renamed to `analyses`). The SQL file is reference-only and not run at startup.
- The `docker-compose.yml` `version:` key is obsolete in newer Docker Compose versions (produces a warning; harmless).
- Gunicorn runs multiple workers — `analysis_outputs` (in-memory dict for live log streaming) is not shared across workers. Live output may not work if the polling request hits a different worker than the one running the job.
- No email notification system is implemented (admin password reset has a TODO stub).
- VCF files are never automatically cleaned up; manual management required.
- The healthcheck curls `/` which redirects (302) to `/login` — curl `-f` does not fail on 3xx, so this passes correctly.
