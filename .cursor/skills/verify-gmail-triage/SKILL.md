---
name: verify-gmail-triage
description: Verify the gmail-triage CLI on its real commands (dry-run digest, bootstrap and apply approval gates, env-file loading). Use when proving user-visible CLI behavior, not when only running pytest.
---

# Verify gmail-triage

Primary surface is the terminal CLI. There is no web UI, TUI, or long-lived server.

User commands:

```bash
.venv/bin/python -m triage.dry_run --limit 50
.venv/bin/python -m triage.dry_run --bootstrap --limit 50
.venv/bin/python -m triage.apply --limit 50
```

Isolation is mandatory. Never drive the owner's `.triage/` directory or the owner's `.env` / `secrets/token.json`. A live Gmail dry run uses OAuth, calls Jev, and advances history. Default verification stays on isolated scratch state and, for digest proof, stubs Gmail and Jev at their client constructors.

Repo root is four parents above `helpers/` (`Path(__file__).resolve().parents[4]`).

## Launch

This CLI is short-lived. Launch means install deps once, then start each drive in its own scratch directory.

```bash
.venv/bin/python -c "import triage"
```

Ready when that import exits 0. There is no port and no prompt to wait for.

Teardown is `helpers/cleanup`. It deletes `runs/` only.

## Doctor

Run this first whenever anything looks off:

```bash
.cursor/skills/verify-gmail-triage/helpers/doctor
```

The script fails unless all of these are true:

- `.venv/bin/python` exists and reports Python 3.11 or newer
- `import triage`, `triage.dry_run`, and `triage.apply` succeed
- `.env.example` exists and contains no `vck_`, `sk-`, or `AIza` secret prefixes
- helper scripts are executable

Doctor does not start Gmail OAuth and does not read `.env`.

## Drive

Harness is subprocess plus isolated env, via the helpers below. Stable handles are the prompt strings and stdout lines, not coordinates.

| Handle | Where |
| --- | --- |
| `Type BOOTSTRAP to approve rebuilding the Gmail checkpoint: ` | `python -m triage.dry_run --bootstrap` stdin |
| `Type APPLY TRIAGE LABELS to modify Gmail labels: ` | `python -m triage.apply` stdin |
| `Bootstrap not approved.` | stderr, exit 2 |
| `Apply not approved.` | stderr, exit 2 |
| `AI_GATEWAY_API_KEY is required` | stderr, exit 2 |
| `Gmail Triage Digest` | stdout and `$TRIAGE_STATE_DIR/digest.txt` |
| `https://mail.google.com/mail/u/0/#all/<thread_id>` | digest entries |

Read `features/README.md` and drive from the matching feature file. Mapped features are:

- [Dry-run digest](features/dry-run-digest.md)
- [Bootstrap approval](features/bootstrap-approval.md)
- [Apply approval](features/apply-approval.md)
- [Env file](features/env-file.md)
- [Gmail method allowlist](features/gmail-allowlist.md)

```bash
.cursor/skills/verify-gmail-triage/helpers/drive-dry-run
.cursor/skills/verify-gmail-triage/helpers/drive-cli-gates
```

`drive-cli-gates` invokes the real `python -m triage.*` modules with scratch env. `drive-dry-run` calls `triage.dry_run.main(["--limit", "50"])` after replacing only `client_from_environment` and `JevClient`. That is the production Gmail/Jev boundary. It still uses the CLI argument parser, env loader, checkpoint, decision log, and digest writer.

## Evidence

Proof lives in `.cursor/skills/verify-gmail-triage/evidence/<feature>/<run_id>/` and must survive cleanup.

Required artifacts for a passing drive:

- `command.txt` with the exact command or helper invocation
- `stdout.txt` and `stderr.txt`
- `exit_code.txt`
- For digest drives, a copy of `digest.txt` and `gmail_calls.json`
- For gate drives, the prompt text visible in stdout or stderr

Proof standards:

- Exercise the user command path (`python -m triage.dry_run` / `python -m triage.apply` or `dry_run.main` / `apply.main` with the same argv)
- Capture the action (argv, stdin) and the resulting files, not only the exit code
- Observe skipped mutations. A dry-run digest drive must record zero `users.messages.modify`, `users.labels.create`, send, trash, and history-consuming apply methods
- Do not treat pytest as the user path. Pytest may run as a doctor supplement, not as digest proof
- Never point `TRIAGE_STATE_DIR` at `.triage` during verification

## Cleanup

```bash
.cursor/skills/verify-gmail-triage/helpers/cleanup
```

Deletes `.cursor/skills/verify-gmail-triage/runs/` created by this skill. Does not delete `evidence/`. Does not kill processes by name. Does not touch `.triage/`, `.env`, or `secrets/`.

## Helpers

All helpers are executable and must be run from any cwd. They locate the repo themselves.

```bash
.cursor/skills/verify-gmail-triage/helpers/doctor
.cursor/skills/verify-gmail-triage/helpers/drive-dry-run
.cursor/skills/verify-gmail-triage/helpers/drive-cli-gates
.cursor/skills/verify-gmail-triage/helpers/cleanup
```
