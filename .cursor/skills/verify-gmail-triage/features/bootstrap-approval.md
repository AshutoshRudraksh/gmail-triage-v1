# Bootstrap approval

Bootstrap rebuilds the Gmail history checkpoint only after the owner types `BOOTSTRAP` exactly.

## Sub-features

- `bootstrap-prompt` asks `Type BOOTSTRAP to approve rebuilding the Gmail checkpoint: `.
- `bootstrap-reject` exits 2 and prints `Bootstrap not approved.` when the typed line is not `BOOTSTRAP`.
- `bootstrap-flag` is reached only with `--bootstrap`.

## How to get to it (user POV)

- Run `.venv/bin/python -m triage.dry_run --bootstrap --limit 50` in a terminal.

## Driving it with verify-gmail-triage helpers

Preconditions:

- `helpers/doctor` printed `doctor ok`.
- Scratch `TRIAGE_ENV_FILE` and `TRIAGE_STATE_DIR` are set so the command cannot touch `.triage/`.

- **Reject bootstrap.** Run `.cursor/skills/verify-gmail-triage/helpers/drive-cli-gates`. That helper runs `python -m triage.dry_run --bootstrap --limit 50` with stdin `nope`.
- **Observe the gate.** `evidence/bootstrap-approval/<run_id>/exit_code.txt` is `2`. Combined stdout/stderr contains `Bootstrap not approved.`
- **Proof.** `command.txt` shows `python -m triage.dry_run --bootstrap --limit 50`. `stdin.txt` is `nope`.

## Gotchas

- The check is exact. `bootstrap` and `BOOTSTRAP ` with a trailing space both fail.
- Approval is checked before Gmail authentication, so a reject drive must not open a browser.
- A successful bootstrap against a live mailbox is out of default verification. Report it skipped unless the owner explicitly asked for a live smoke test.
