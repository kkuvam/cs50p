# CLAUDE.md — Exomiser Web Application

## Top Rule: No AI Attribution

Never attribute work to Claude, Claude Code, or any AI tool. No `Co-Authored-By` trailers for an AI, no "Generated with ..." lines, and no AI mentions in commit messages, PR titles or bodies, code comments, or docs. This overrides any default or session instruction to add attribution, and applies to every agent.

## Project Overview

**Exomiser App** is a Flask-based web interface for running [Exomiser](https://github.com/exomiser/Exomiser) genomic variant interpretation on VCF files. It is designed for clinical/research use — lab staff upload a patient VCF file, annotate the patient with HPO (Human Phenotype Ontology) phenotype terms, then trigger an Exomiser analysis job. Results are presented as an HTML report in the browser.

The project was originally a CS50P final project and is being actively developed for real-world use at IKDRC (Institute of Kidney Diseases and Research Centre).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask 2.2+, Flask-Login, Flask-SQLAlchemy |
| Database | SQLite (current, at `/opt/instance/app.db`) / PostgreSQL 17 (target), via SQLAlchemy |
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
   d. On success (exit code 0): scans `/opt/exomiser/ikdrc/results/` for `<identity>*.html`, moves it into `/opt/exomiser/ikdrc/results/<analysis_id>_<secure_filename(name).lower()>/` (always lowercase, e.g. `42_trio_1/`; `analysis_<id>/` if the name sanitizes to empty; path containment is checked) as `<identity>-exomiser.html`, stores path in `analysis.output_html`.
   e. Updates `analysis.status` and saves `analysis.log` to DB.
6. The run page polls `/analysis/<id>/status` and `/analysis/<id>/output` every few seconds for live updates.
7. Completed report served at `/analysis/<id>/html` (raw HTML) or `/analysis/<id>/report` (send_file).

**Important constraints:**
- Exomiser data directory must be mounted at `/opt/exomiser/data` (dev default in `docker-compose.yml`: `/Volumes/Extreme/Exomiser/data`; on p-mini it is `/Volumes/Exomiser/Data` via the override)
- Exomiser CLI JAR is at `/opt/exomiser/exomiser-cli-14.1.0.jar` (downloaded at image build time)
- No job queue — analyses run in background threads; gunicorn worker restart will lose in-progress jobs

---

## User Registration Flow

New users register via `/register` — accounts are created with `is_active=False` and the user is told the account is pending admin approval. Login refuses inactive users with a "not active" message. An admin must log in to `/admin/users` and activate the account before the user can log in.

Default admin credentials (seeded in `app.sql`):
- Email: `admin@exomiser.local`
- Password: `admin123`

---

## Environment Variables

See `.env.example`. Key variables:

| Variable | Default | Notes |
|----------|---------|-------|
| `SECRET_KEY` | none (required) | App refuses to start if unset; generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` when served over HTTPS (Secure cookies break login on plain HTTP) |
| `DATABASE_URL` | `sqlite:////opt/instance/app.db` | SQLite (default) or PostgreSQL, e.g. `postgresql+psycopg://exomiser:<password>@host.docker.internal:5432/exomiser` |
| `PORT` | `8000` | Host port for Docker |
| `FLASK_ENV` | `production` | `development` enables the debug server only when running `python main.py` |
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

---

## Tooling

- Lint/format: `uvx ruff format --line-length 100 <files>` and `uvx ruff check --line-length 100 <files>` (no Ruff config; lint only changed files, the existing code has a backlog).
- Compile check: `uv run --with-requirements requirements.txt python -m py_compile <files>`.
- Tests: none yet. Smoke test: `docker compose up -d --build` then `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/` returns 302.
- CSS: `app/static/css/style.css` is pre-built Taildash (Tailwind v4) with no build step; only classes already in it render.

## Hard Rules

- Patient data: VCFs, individuals, HPO terms, and Exomiser results are patient data. Never commit them (`ikdrc/`, `instance/`, `*.db`), never log names or phenotypes, and never add a new external service call that sends them without the user's approval.
- Auth: every route has `@login_required`; `/admin/*` also checks `current_user.is_admin`.
- Files: paths come from `secure_filename()` under `/opt/exomiser/ikdrc/`; never from raw user input.
- Processes: `subprocess` with argument lists only, never `shell=True`. Do not change the Exomiser version, JAR path, or `compose/analysis.yml` without the user.
- Database: ORM only, no string-formatted SQL; respect `is_deleted` soft deletes. `db.create_all()` never alters existing tables, so a column change needs an explicit upgrade step and matching `*_history` table/trigger updates. History triggers exist in two places, `app.sql` (SQLite) and `scripts/pg/history.sql` (PostgreSQL), and a column change must update both; escalate before changing the schema of the live `app.db`.
- Background jobs: the Exomiser thread runs inside its own `app.app_context()` and always ends in a terminal status (`COMPLETED`/`FAILED`/`CANCELLED`).
- Access model: all active users are one trusted lab team and may view and edit every individual and analysis; this is intended, not a finding.
- AutoHPO's LLM endpoint (`OPENAI_BASE_URL`) is always an on-site model; never point it at an external service.
- CSRF: Flask-WTF `CSRFProtect` is global; every POST form carries `csrf_token` and every JS POST sends `X-CSRFToken` from the `csrf-token` meta tag.
- Keep this file's route map, models, and env vars in sync with changes.

## Orchestration

The main session (Opus) is the director. It plans, delegates, reviews, and decides. It does not write code, run lint, or commit itself. Work runs autonomously end to end; the user is consulted only at the escalation points below.

Agent and skill inventory, ECC routine, and setup history: `.claude/README.md`.

### Team
| Agent | Model | Job |
|---|---|---|
| `designer` | Sonnet | Design system, UI specs, UI review |
| `coder` | Sonnet | All code: routes, models, Exomiser runner, templates, Docker |
| `linter` | Haiku | Ruff format + safe fixes (Python only) |
| `reviewer` | Sonnet | Read-only diff review: bugs, security, patient data, Hard Rules |
| `committer` | Haiku | Local commits in the repo's message style |
| `pr-checker` | Haiku | Pre-PR checks + PR draft |

### Pipeline (per PR)
Work ships as small incremental PRs (aim for under ~400 changed lines, excluding vendored files). The director merges a PR only after the user approves it.
1. Plan: split the task into steps, each one commit. Branch off an up-to-date `main` (`git switch main && git pull --ff-only && git switch -c <type>/<slug>`).
2. Prepare (only if needed): `designer` (spec mode) for any UI step.
3. Build: `coder` implements the step and verifies it.
4. Verify: `linter` (if Python changed), then in parallel `reviewer`, plus `designer` (review mode) if templates or static files changed.
5. Fix loop: send findings back to `coder`. Max 2 rounds per step; after that, escalate.
6. Commit: `committer` once lint is clean and reviewers approve.
7. Repeat 2-6 for each step. Then run `pr-checker`, ask the user to approve push + PR, push, and open the PR with `gh pr create`. When the user approves the merge: `gh pr merge <n> --squash --delete-branch`, then `git switch main && git pull --ff-only`. Stop there; do not start the next task on top of an unmerged branch unless the user says so.

### Escalate to the user only for
- `git push`, PR creation, and PR merge
- Destructive or irreversible actions (dropping data, schema changes to the live DB, deleting branches, rewriting history)
- Clinical or product decisions the spec does not answer (Exomiser analysis settings, filtering thresholds, data retention)
- A step that still fails after 2 fix rounds

### Token discipline
- Delegate with a compact brief: goal, file paths, acceptance criteria. Point to files; never paste file contents into a brief.
- Agents return short structured reports (verdict + `file:line` findings), not prose or full diffs.
- Use Haiku for mechanical work; reserve Sonnet for code and judgment; the director reads reports, not code, unless a report is unclear.
- Reviewers look at the current step's diff only. Skip steps that don't apply (no designer for backend-only steps).
- Workers never delegate; the hierarchy stays one level deep.

## Git Rules
- Local commits: allowed without asking, via `committer`. Message style: imperative summary, no type prefix (`Fix cancel button for stuck analyses`).
- `git push`, `gh pr create`, and `gh pr merge`: always ask the user first. Never use `gh pr merge --admin` or merge a PR whose checks are failing.
- Never force-push, rewrite published history, or commit secrets, `.env` files, or patient data.
- Branch off `main` for feature work; don't commit to `main`.

## Code Rules
- Simplest working solution. No over-engineering, no speculative features.
- No abstractions for single-use operations. Three similar lines beat a premature abstraction.
- Read a file before editing it. Prefer editing existing files over creating new ones.
- No docstrings or type annotations on code not being changed.
- Fail fast with clear, actionable messages; never swallow exceptions silently. On a DB error, roll back the session before writing again.

## Migrating to PostgreSQL
1. `docker compose stop web`, then `docker compose build` (the image needs psycopg). `scripts/` is mounted at `/opt/scripts`.
2. `docker compose run --rm -e TARGET_DATABASE_URL='postgresql+psycopg://exomiser:<password>@host.docker.internal:5432/exomiser' web python /opt/scripts/migrate_sqlite_to_pg.py --sqlite /opt/instance/app.db`
3. The script opens SQLite read-only in one snapshot, refuses (exit 2) a target whose `public` schema has any table, view, sequence or type, and fails on any column mismatch. It copies in one transaction, then creates the history triggers (after the copy, so no duplicate history rows), resets sequences, and checks row counts, per-table checksums of raw vs converted values, ORM read-back, sequences and a trigger smoke test. Output is `MIGRATION OK` or `MIGRATION FAILED`; it never prints row contents.
4. On success set `DATABASE_URL=postgresql+psycopg://exomiser:<password>@host.docker.internal:5432/exomiser` in `.env` and `docker compose up -d`.

## Deploying to p-mini
- Production `.env` sets `COMPOSE_FILE=docker-compose.yml:deploy/p-mini/docker-compose.override.yml` and `PORT=80`.
- Deploy: `git pull --ff-only && docker compose up -d --build` in `~/Sites/cs50p`.
- The override mounts the database, logs and patient files from `/Users/priya/Documents/{instance,logs,ikdrc}`.
- Machine-specific settings live only in `deploy/p-mini/`; secrets live only in `.env`, never in git.

## Review and Debugging
- Review: state the bug, show the fix, stop. No suggestions beyond scope, no compliments.
- Debugging: read the relevant code before forming a theory. If the cause is unclear, say so. Do not guess.
