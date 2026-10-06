---
name: commit
description: Create a local git commit in this repo's message style from the current changes. Never pushes.
---
# Commit

1. `git status` and `git diff` (staged and unstaged) to see what changed.
2. Refuse to commit and report back if:
   - any `.env`, credentials, keys, or large binaries are in the change
   - any patient data is in the change: VCF files, `ikdrc/` contents, `instance/` or `*.db` files, real names or identities in fixtures
   - the current branch is `main` and the change is feature work (ask the director to branch first)
3. Stage only files that belong to this step (`git add <paths>`; avoid `git add -A` unless every change belongs).
4. Write the message in the repo's existing style (see `git log --oneline -10`):
   - summary: imperative verb, capitalized, no type prefix, ≤ 72 chars (e.g. `Fix cancel button for stuck analyses`)
   - body (optional): short `- ` bullets on why, not what
   - end with the attribution lines the session tells you to include, if any
5. `git commit`. Never use `--amend`, `--no-verify`, or push.
6. Report the commit hash and message.
