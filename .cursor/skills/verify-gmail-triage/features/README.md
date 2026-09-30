# gmail-triage verification map

This directory is the maintained source for verifying the user-facing CLI of gmail-triage. Read this index before driving, then use the matching feature file.

## Baseline preconditions

- Work from the repo root that contains `pyproject.toml`, or let helpers resolve it.
- Use `.venv/bin/python`.
- Run `.cursor/skills/verify-gmail-triage/helpers/doctor` and require `doctor ok`.
- Set `TRIAGE_STATE_DIR` and `TRIAGE_ENV_FILE` to a disposable `runs/<run_id>/` tree. Never use `.triage/` or the owner's `.env`.
- Do not open a Google OAuth browser during default verification.
- Do not run two live Gmail drives against the same mailbox token and `.triage/` directory.

## Driving conventions

- Start every recipe from doctor-ok unless the feature lists extra preconditions.
- Treat prompt strings and flags as literal.
- Gate features use `python -m triage.dry_run` and `python -m triage.apply` with piped stdin.
- Digest proof uses `helpers/drive-dry-run`, which calls `triage.dry_run.main(["--limit", "50"])` with Gmail and Jev stubbed at the client constructors.
- Restore nothing in the owner's mailbox. Scratch state is deleted by `helpers/cleanup`. Keep `evidence/`.

## Proof and skip reporting

- Capture argv, stdin, stdout, stderr, and exit code.
- Digest proof also copies `digest.txt` and the Gmail method list.
- A skipped live-Gmail path is not verified by the isolated digest drive. Report it skipped.
- Do not report pytest as proof of a CLI feature.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with verify-gmail-triage helpers`
4. `Gotchas`

## Features

- [Dry-run digest](./dry-run-digest.md) covers the morning digest from a dry-run command.
- [Bootstrap approval](./bootstrap-approval.md) covers the exact `BOOTSTRAP` gate.
- [Apply approval](./apply-approval.md) covers the exact `APPLY TRIAGE LABELS` gate.
- [Env file](./env-file.md) covers missing `AI_GATEWAY_API_KEY`.
- [Gmail method allowlist](./gmail-allowlist.md) covers zero mutating Gmail methods on dry run.
