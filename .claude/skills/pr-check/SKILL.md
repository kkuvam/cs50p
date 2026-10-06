---
name: pr-check
description: Pre-PR readiness checks for a feature branch (Ruff, compile check, tests if any, app smoke test, diff review for secrets/patient data, PR size) and a drafted PR title and body.
---
# PR check

1. Confirm the branch is not `main`, is based on the current `origin/main` (`git fetch origin && git merge-base --is-ancestor origin/main HEAD`), and has commits ahead (`git log origin/main..HEAD --oneline`).
2. Size: `git diff --stat origin/main...HEAD`. Flag the PR as TOO BIG if it exceeds ~400 changed lines excluding vendored files (`app/static/vendors/`, `app/static/css/style.css`), and suggest a split.
3. Run checks from the repo root and record pass/fail:
   - `uvx ruff format --check --line-length 100` and `uvx ruff check --line-length 100` on the Python files changed in the branch
   - `uv run --with-requirements requirements.txt python -m py_compile <changed .py files>`
   - `pytest -q` via `uv run --with-requirements requirements.txt --with pytest pytest -q`, only if a `tests/` directory exists; otherwise note "no test suite"
   - smoke test if Docker is running: `docker compose up -d --build`, then `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/` must return 302; skip with a note if Docker is not running
4. Review `git diff origin/main...HEAD` for:
   - secrets, tokens, `.env` contents, hard-coded credentials or API keys
   - patient data: VCFs, `ikdrc/`, `instance/`, `*.db`, real names or identities
   - leftover debug code (`print(`, `breakpoint()`, `console.log`), TODOs added in this branch
   - routes without `@login_required`; admin routes without an `is_admin` check
   - `subprocess` with `shell=True`; file paths from unsanitized input; raw SQL with string formatting
   - model column changes without an upgrade step and `*_history` updates in `app.sql`
   - CLAUDE.md out of date with the change (routes, models, env vars)
5. Draft the PR:
   - **Title**: repo commit style (imperative, no type prefix), <= 72 chars
   - **Body**: Summary (bullets), Changes, How to test, Notes/risks
6. Report: a checklist with pass/fail per check, issues found (file:line), and the PR draft. State clearly whether the branch is READY or NOT READY.

Never push, create, or merge the PR.
