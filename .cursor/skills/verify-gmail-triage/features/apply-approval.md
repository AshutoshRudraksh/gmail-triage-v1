# Apply approval

Apply changes Gmail labels only after the owner types `APPLY TRIAGE LABELS` exactly. There is no `--yes` flag.

## Sub-features

- `apply-prompt` asks `Type APPLY TRIAGE LABELS to modify Gmail labels: `.
- `apply-reject` exits 2 and prints `Apply not approved.` when the typed line does not match.
- `apply-no-unattended` exposes no `--yes` option.

## How to get to it (user POV)

- Run `.venv/bin/python -m triage.apply --limit 50` in a terminal.

## Driving it with verify-gmail-triage helpers

Preconditions:

- `helpers/doctor` printed `doctor ok`.
- Scratch env is set. The reject path must not call Gmail.

- **Reject apply.** Run `.cursor/skills/verify-gmail-triage/helpers/drive-cli-gates`. That helper runs `python -m triage.apply --limit 50` with stdin `nope`.
- **Observe the gate.** `evidence/apply-approval/<run_id>/exit_code.txt` is `2`. Combined output contains `Apply not approved.`
- **Proof.** `command.txt` shows `python -m triage.apply --limit 50`. Parser has no `--yes` flag.

## Gotchas

- EOF (empty stdin) is also a reject. Do not treat that as a crash.
- A typed approval against a live mailbox creates labels and is irreversible for those three managed labels only. Default verification does not approve apply.
- Do not drive apply against the owner's `.triage/decisions.jsonl`.
