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
| Database | PostgreSQL 17 (`exomiser` on the p-mini host); SQLite remains the local dev default. Via SQLAlchemy |
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

SQLite at `/opt/instance/app.db` is the dev default; the directory is created automatically when running locally.

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
├── instance/                   # Dev SQLite DB location (mounted at /opt/instance)
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
- Deactivated or deleted users are logged out on their next request (`load_user` returns `None`)
- `users_history` no longer stores password hashes: the column remains but the triggers write `NULL`

### Individual
Represents a patient/sample. Key fields:
- `identity` — unique patient ID (e.g. `P0001`), used as Exomiser sample name; unique among non-deleted individuals (partial unique index `uq_individuals_identity_active`)
- `hpo_terms` — JSON array of `{"id": "HP:0001250", "label": "Seizures"}` objects
- `vcf_filename` — original upload filename (for display/download)
- `vcf_file_path` — server path: `/opt/exomiser/ikdrc/vcf/<timestamp>_<8 hex>_<filename>`
- `phenopacket_yaml` — auto-generated GA4GH Phenopacket v1.0 YAML (regenerated on save)

### Analysis
Represents one Exomiser run. Key fields:
- `individual_id` — FK to Individual
- `vcf_filename` — VCF filename passed to Exomiser (auto-populated from individual)
- `genome_assembly` — `hg19` or `hg38` (hg38 is hidden in the UI and new hg38 selections are rejected until hg38 data is installed; existing hg38 rows can still be saved)
- `analysis_mode` — `PASS_ONLY` or `FULL`
- `status` — `PENDING` → `RUNNING` → `COMPLETED` / `FAILED` / `CANCELLED`
- `output_html` — full path to Exomiser HTML report
- `log` — captured stdout/stderr from the Exomiser process

---

## Analysis Execution Flow

1. User creates an **Individual** record, uploads a VCF file.
2. User creates an **Analysis** record, selects the individual, confirms VCF filename and genome assembly.
3. User navigates to `/analysis/<id>/run` and clicks **Run**.
4. Flask atomically claims the run (conditional update to `RUNNING`), writes the run file `/opt/logs/analysis_<id>.pid` (token, owning worker pid and start time, Java pid) and spawns a **daemon thread** (`run_exomiser_analysis`).
5. The thread:
   a. Generates a Phenopacket YAML from the individual record → saves to `/opt/exomiser/ikdrc/phenopacket/analysis_<id>.yml`
   b. Invokes: `java -Xmx4g -jar /opt/exomiser/exomiser-cli-14.1.0.jar --analysis /opt/exomiser/analysis.yml --sample <phenopacket_file>`
   c. Captures stdout/stderr line-by-line into the shared log file `/opt/logs/analysis_<id>.log`. Java runs in its own process group; it is killed after `EXOMISER_TIMEOUT_HOURS` (run FAILED) or on Cancel.
   d. Exomiser is started with `--output-directory <results>/<analysis_id>_<secure_filename(name).lower()>/` (`analysis_<id>/` if the name sanitizes to empty; path containment checked) and `--output-filename <secure_filename(identity)>-exomiser`, which override `analysis.yml`, so the HTML and VCF paths are exact. On exit 0 the thread stores `<identity>-exomiser.html` as `analysis.output_html` (and the `.vcf.gz`/`.vcf` as `output_vcf`); both count only if written at or after the run start (minus 2 s), so an older report in a re-used folder never counts; exit 0 without that HTML is FAILED, never COMPLETED. Nothing scans the results folder. Report routes serve only `analysis.output_html`, and only if it exists inside `/opt/exomiser/ikdrc/results`; otherwise "Report file not found for this analysis".
   e. Updates `analysis.status` and saves `analysis.log` to DB.
6. The run page polls `/analysis/<id>/status` and `/analysis/<id>/output` every few seconds for live updates.
7. Completed report served at `/analysis/<id>/html` (raw HTML) or `/analysis/<id>/report` (send_file).

**Important constraints:**
- Exomiser data directory must be mounted at `/opt/exomiser/data` (dev default in `docker-compose.yml`: `/Volumes/Extreme/Exomiser/data`; on p-mini it is `/Volumes/Exomiser/Data` via the override)
- Exomiser CLI JAR is at `/opt/exomiser/exomiser-cli-14.1.0.jar` (downloaded at image build time)
- No job queue — analyses run in background threads; a worker or container restart kills in-progress jobs; the stale-run reaper then marks them FAILED (or CANCELLED for runs from before run files existed). Gunicorn runs without `--max-requests` so workers are not recycled mid-run

---

## User Registration Flow

New users register via `/register` — accounts are created with `is_active=False` and the user is told the account is pending admin approval. Login refuses inactive users with a "not active" message. An admin must log in to `/admin/users` and activate the account before the user can log in.

No admin is seeded. Create the first admin with `docker compose exec web python create_admin.py` (prompts for email and password), or non-interactively with `ADMIN_EMAIL` / `ADMIN_PASSWORD` set (`docker compose exec -e ADMIN_EMAIL=... -e ADMIN_PASSWORD=... web python create_admin.py`). The password must be at least 12 characters.

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
| `EXOMISER_TIMEOUT_HOURS` | `2` | Max hours for one Exomiser run before it is killed and marked FAILED |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker count |
| `GUNICORN_THREADS` | `4` | Threads per worker |
| `EXOMISER_VERSION` | `14.1.0` | Exomiser CLI version (build arg) |

---

## Key External Paths (inside container)

| Path | Purpose |
|------|---------|
| `/opt/app` | Flask application code (mounted from `./app`) |
| `/opt/instance/app.db` | SQLite database, dev only. In production the DB is PostgreSQL via `DATABASE_URL` |
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
- Gunicorn runs multiple workers; live output and run state live in files under `/opt/logs` and the database, so any worker can serve the polling requests.
- No email notification system is implemented (admin password reset has a TODO stub).
- VCF files are never automatically cleaned up; manual management required.
- The AutoHPO embedding model (`all-MiniLM-L6-v2`) is baked into the image at build time under `HF_HOME=/opt/hf`, and the app runs with `HF_HUB_OFFLINE=1`; a different `HPO_EMBEDDING_MODEL` is not available offline and falls back to keyword search with a warning.
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
- Database: ORM only, no string-formatted SQL; respect `is_deleted` soft deletes. `db.create_all()` never alters existing tables, so a column change needs an explicit upgrade step and matching `*_history` table/trigger updates. History triggers exist in two places, `app.sql` (SQLite) and `scripts/pg/history.sql` (PostgreSQL), and a column change must update both; escalate before changing the schema of the production `exomiser` database.
- Background jobs: the Exomiser thread runs inside its own `app.app_context()` and always ends in a terminal status (`COMPLETED`/`FAILED`/`CANCELLED`).
- Access model: all active users are one trusted lab team and may view and edit every individual and analysis; this is intended, not a finding.
- AutoHPO's LLM endpoint (`OPENAI_BASE_URL`) is always an on-site model; never point it at an external service. `app/autohpo.py` enforces this: it refuses (503) unless `OPENAI_BASE_URL` is http(s) and resolves only to loopback, private, link-local, CGNAT (100.64.0.0/10) or IPv6 ULA addresses.
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
p-mini was migrated on 2026-10-06 (SQLite backups kept in `~/Sites/backup`). Steps for any other host:

1. `docker compose stop web`, then `docker compose build` (the image needs psycopg). `scripts/` is mounted at `/opt/scripts`.
2. `docker compose run --rm -e TARGET_DATABASE_URL='postgresql+psycopg://exomiser:<password>@host.docker.internal:5432/exomiser' web python /opt/scripts/migrate_sqlite_to_pg.py --sqlite /opt/instance/app.db`
3. The script opens SQLite read-only in one snapshot, refuses (exit 2) a target whose `public` schema has any table, view, sequence or type, and fails on any column mismatch. It copies in one transaction, then creates the history triggers (after the copy, so no duplicate history rows), resets sequences, and checks row counts, per-table checksums of raw vs converted values, ORM read-back, sequences and a trigger smoke test. Output is `MIGRATION OK` or `MIGRATION FAILED`; it never prints row contents.
4. On success set `DATABASE_URL=postgresql+psycopg://exomiser:<password>@host.docker.internal:5432/exomiser` in `.env` and `docker compose up -d`.

## Schema upgrades
`db.create_all()` does not alter existing databases, so schema changes ship as idempotent scripts in `scripts/pg/`. To apply `upgrade_20261007.sql` on p-mini (unique active identity index, users history trigger without password hashes, blanks old `users_history.password_hash`), as `priya` in `~/Sites/cs50p`:
```bash
pg_dump -Fc exomiser -f ~/Sites/backup/pre-upgrade-$(date +%Y%m%d-%H%M%S).dump   # 1. fresh dump
psql -d exomiser -v ON_ERROR_STOP=1 -f scripts/pg/upgrade_20261007.sql           # 2. one transaction; safe to re-run
```
The index step fails (and nothing is applied) if two non-deleted individuals share an identity; resolve those first.
Dumps and backups taken before `upgrade_20261007.sql` still contain the old `users_history.password_hash` values; treat them as sensitive until they are pruned. `scripts/migrate_sqlite_to_pg.py` writes `NULL` for that column.

## Backups (p-mini)
- Nightly at 02:30 by the LaunchAgent `deploy/p-mini/com.ikdrc.exomiser.pgbackup.plist`, which runs `scripts/pg_backup.sh` as `priya` over the local Unix socket (no password in any file). Install once:
  ```bash
  mkdir -p ~/Sites/backup/pg
  cp ~/Sites/cs50p/deploy/p-mini/com.ikdrc.exomiser.pgbackup.plist ~/Library/LaunchAgents/
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ikdrc.exomiser.pgbackup.plist
  launchctl kickstart -k gui/$(id -u)/com.ikdrc.exomiser.pgbackup   # run now
  ```
- Dumps (`exomiser-YYYYmmdd-HHMMSS.dump` plus `.sha256`) and `backup.log` live in `~/Sites/backup/pg`. Retention is 14 days (`RETENTION_DAYS`); only `exomiser-*.dump(.sha256)` files are pruned and the newest dump is never deleted.
- Each run verifies the dump: `pg_restore --list` has entries, a restore into a temporary database (dropped afterwards) has the same row counts as the live DB for the 6 tables, and 9 non-internal triggers exist. Any mismatch exits non-zero and keeps the dump.
- `OFFSITE_DIR` (optional env var, add it to the plist `EnvironmentVariables`) copies each dump and checksum to another folder or drive and verifies it. If it is set but missing (drive not mounted) the run exits non-zero after the local backup succeeded.
- Restore (DESTRUCTIVE: replaces the live database; only with the user's go-ahead):
  ```bash
  ( cd ~/Sites/backup/pg && shasum -a 256 -c <dump>.sha256 )   # 1. verify the chosen dump
  ( cd ~/Sites/cs50p && docker compose stop web )              # 2. stop the app
  pg_dump -Fc exomiser -f ~/Sites/backup/pre-restore-$(date +%Y%m%d-%H%M%S).dump   # 3. fresh dump of the current DB
  psql -d postgres -Atc "SELECT count(*) FROM pg_stat_activity WHERE datname='exomiser'"   # 4. must be 0
  dropdb exomiser
  createdb -O exomiser exomiser
  pg_restore -d exomiser --no-owner --role=exomiser --exit-on-error --single-transaction <dump>
  ( cd ~/Sites/cs50p && docker compose up -d )                 # then check row counts
  ```
- Not covered: VCFs, phenopackets and results in `~/Documents/ikdrc` are not part of this backup.
- Dumps are unencrypted patient data. Any `OFFSITE_DIR` media must be trusted or encrypted.
- The job is a LaunchAgent, so it only runs while `priya` is logged in, the same as Docker Desktop and the brew services. A missed night is visible as a stale `backup.log`.

## Deploying to p-mini
- Production `.env` sets `COMPOSE_FILE=docker-compose.yml:deploy/p-mini/docker-compose.override.yml` and `PORT=80`.
- Deploy: `git pull --ff-only && docker compose up -d --build` in `~/Sites/cs50p`.
- The override mounts the database, logs and patient files from `/Users/priya/Documents/{instance,logs,ikdrc}`.
- Machine-specific settings live only in `deploy/p-mini/`; secrets live only in `.env`, never in git.

## Review and Debugging
- Review: state the bug, show the fix, stop. No suggestions beyond scope, no compliments.
- Debugging: read the relevant code before forming a theory. If the cause is unclear, say so. Do not guess.
