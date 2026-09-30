# Env file

Dry run refuses to classify until `AI_GATEWAY_API_KEY` is present in the process environment or a loaded `.env` file.

## Sub-features

- `env-missing` exits 2 with `AI_GATEWAY_API_KEY is required` when the key is absent.
- `env-file` is selected with `TRIAGE_ENV_FILE` (default `.env`).
- `env-no-override` leaves an already-set process variable unchanged.

## How to get to it (user POV)

- Run `.venv/bin/python -m triage.dry_run --limit 50` without exporting the key and with an empty env file.

## Driving it with verify-gmail-triage helpers

Preconditions:

- `helpers/doctor` printed `doctor ok`.
- The helper unsets `AI_GATEWAY_API_KEY` for the child process.

- **Run without a key.** Run `.cursor/skills/verify-gmail-triage/helpers/drive-cli-gates`. That helper runs `python -m triage.dry_run --limit 50` with an empty scratch env file.
- **Observe the error.** `evidence/env-file/<run_id>/exit_code.txt` is `2`. Combined output contains `AI_GATEWAY_API_KEY is required`.
- **Proof.** `command.txt` is `python -m triage.dry_run --limit 50`.

## Gotchas

- `.env.example` is not loaded. Only `.env` or `TRIAGE_ENV_FILE`.
- A key in the owner shell overrides `.env`. Isolation must unset it.
- Do not paste real keys into evidence files.
