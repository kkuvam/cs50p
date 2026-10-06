# Claude Code setup

Multi-agent setup: the main session (Opus) directs; workers do the work. Pipeline and rules live in `../CLAUDE.md`.

## Agents (`agents/`)
| Agent | Model | Source | Job |
|---|---|---|---|
| coder | Sonnet | project | All code: Flask routes, models, Exomiser runner, templates, Docker |
| designer | Sonnet | project | Design system, UI specs, UI review (Taildash/Tailwind + Alpine) |
| reviewer | Sonnet | project | Read-only diff review: bugs, security, patient data, Hard Rules |
| linter | Haiku | project | Ruff format + safe fixes |
| committer | Haiku | project | Local commits in the repo's message style |
| pr-checker | Haiku | project | Pre-PR checks + PR draft |

To change a model, edit `model:` in the agent's frontmatter (`haiku`, `sonnet`, `opus`, `inherit`, or a full model id).

## Skills (`skills/`)
- Project-owned (5): `commit`, `ruff-lint`, `pr-check`, `design-system`, `ui-review`.
- ECC, auto-loadable (14) and manual-only (17, run with `/name`): listed in `.ecc-manifest`.

## ECC routine
The ECC plugin is disabled for this project (`settings.json` -> `enabledPlugins`). A curated subset is copied in by `~/bin/ecc.sh .`; it never overwrites existing files, so reruns are safe.

Reverse: `claude plugin enable ecc --scope project && xargs rm -rf < .claude/.ecc-manifest && rm .claude/.ecc-manifest`

## History
- 2026-10-06: Ran `ecc.sh` (14 auto + 17 manual skills; dropped its Postgres `database-reviewer` agent). Replicated the agent team from `kkuvam/ai-hackathon` (coder, designer, reviewer, linter, committer, pr-checker; web-researcher left out) and retargeted agents and project skills from FastAPI/Postgres/Expo/UnoCSS to Flask/SQLite/Taildash. Added the director pipeline to `CLAUDE.md`.
