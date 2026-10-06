---
name: ruff-lint
description: Lint and format the changed Python files with Ruff, apply safe fixes, and report what remains.
---
# Ruff lint

Run from the repo root. Use `uvx ruff` (there is no Ruff config; pass the options below).

1. If the step changed no Python files, report "nothing to lint" and stop.
2. Format only the changed files: `uvx ruff format --line-length 100 <files>`
3. `uvx ruff check --line-length 100 --fix <files>` (safe fixes only; never pass `--unsafe-fixes`).
4. Run `uvx ruff check --line-length 100 <files>` again and capture the remaining issues.
5. For remaining issues that are purely stylistic and obvious, fix them by hand. Anything that would change behavior: leave it and report it.
6. Report: files changed by format/fix, remaining issues (file:line, rule, message), and anything you deliberately left for the coder.

Lint only the files in the current step; the existing code has never been run through Ruff, and a repo-wide cleanup is its own step, not drive-by noise. If ruff cannot run, report that rather than installing anything.
