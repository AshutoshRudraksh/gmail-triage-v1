# AGENTS.md for gmail-triage

Project instructions for any coding agent working in this repo. Short, evergreen, no secrets.

## What this is
Nightly Gmail triage. A manually started dry run consumes Gmail history, persists
retryable classification work, calls Jev, applies deterministic policy, and renders a
local digest. A separate approved apply run consumes persisted decisions and changes
only three reversible Gmail labels.

## Stack
- Python 3.11+
- Gmail: `google-api-python-client` (official Google client; the
  no-third-party-SDK rule applies to the Jev call path)
- Jev: **stdlib only** (`urllib`) with `POST
  https://ai-gateway.vercel.sh/v1/evaluate`, model `typesafe-ai/jev`
- Secrets: env vars only (`AI_GATEWAY_API_KEY`, Google OAuth token path). Never in code.
  Copy `.env.example` to `.env` and put the Google OAuth JSON under `secrets/`.
  Those files are gitignored. The CLIs load `.env` without overriding a variable
  already present in the process environment.

## Commands
- `python -m pytest`. The full suite must be green before review.
- `ruff check . && ruff format --check .`. These commands check lint and format.
- `python -m triage.dry_run --limit 50`. This is the read-only default mode.
- `python -m triage.apply --limit 50`. This command consumes persisted decisions and
  applies labels. It requires explicit human approval every run.

## Architecture pointers
- `triage/env.py`. Stdlib loader for the local `.env` file at the CLI boundary.
- `triage/gmail_client.py`. Mode-specific Gmail clients and method allowlists.
- `triage/jev_client.py`. Raw HTTPS to the gateway evaluate endpoint, with typed
  questions (`choice`, `score`, and `boolean`) and returned probabilities. It
  normalizes the gateway's zero-based score to the policy's 1 through 5 scale.
- `triage/policy.py`. Deterministic thresholds and the only place that maps
  probabilities to actions.
- `triage/labels.py`. Exact managed-label creation and application, always behind
  the apply command and fresh approval.
- `triage/digest.py`. Morning digest rendering.
- `.triage/checkpoint.json`. Atomically replaced Gmail history checkpoint.
- `.triage/decisions.jsonl`. Pending jobs, classification attempts, and completed
  decisions.
- `.triage/apply_attempts.jsonl`. Every apply attempt and the derived application
  state.

## Managed labels

- `Triage/NeedsAction`
- `Triage/PromoNoise`
- `Triage/SecurityReview`

The project owns only these exact labels. Apply creates missing managed labels
idempotently after approval. It never mutates another label, including another label
under `Triage/`.

## Policy precedence

Evaluate inclusive thresholds in this order:

1. `scam_risk >= 4` selects only `Triage/SecurityReview`.
2. Otherwise, `needs_action >= 0.85` or `is_urgent >= 0.85` selects only
   `Triage/NeedsAction`.
3. Otherwise, `is_promo_noise >= 0.90` selects only `Triage/PromoNoise`.
4. Otherwise, select `ReviewQueue` and no label.

## Conventions
- One Jev call per classification attempt; all questions in a single request.
- Dry run is the default command. Apply is a separate command and never calls Jev.
- Keep history checkpoint state, classification state, and application state
  independent.
- Derive application state from append-only attempts. Supersede older pending
  decisions when a newer decision exists for the same message.
- Use `(message_id, message_added_history_id, classifier_version)` as the
  classification key. A later inbox re-addition has a new key.
- Jev timeout, network, HTTP, and response-validation failures are retryable
  classification attempts, not completed decisions.
- Queue an oversized history record in full, even when that exceeds `--limit`, and
  stop after the record.
- Treat a non-`INBOX` message as permanently handled for that `messageAdded` event.
- Tests first for policy logic. Thresholds are pure functions.
- Persist IDs, hashes, and sanitized outcomes. Never persist message text. There is
  no `--debug-bodies` option.
- Digest entries link to
  `https://mail.google.com/mail/u/0/#all/<thread_id>`.

## Gmail access

Dry run uses exactly `https://www.googleapis.com/auth/gmail.readonly`. It permits
only `users.getProfile`, `users.history.list`, `users.labels.list`,
`users.messages.list`, and `users.messages.get`.

Apply uses exactly `https://www.googleapis.com/auth/gmail.modify`. It permits only
`users.getProfile`, `users.labels.list`, `users.labels.create`,
`users.messages.get`, and `users.messages.modify`.

## Milestones

- **S0. Documentation.** Lock the four project documents and `.gitignore`. Write no
  production code.
- **S1. Access and smoke test.** Verify Gmail access and one sanitized Jev request.
  Measure nightly cost and keep it below $0.05.
- **S2. Fixtures.** Test retryable classification, policy, and persistence locally.
- **S3. Dry run.** Consume Gmail history, render the local digest, and prove zero
  Gmail mutations.
- **S4. Calibration.** Review at least 50 completed classifications. Require
  `Triage/PromoNoise` precision of at least 0.90 before apply.
- **S5. Approved apply.** Create missing managed labels and apply persisted
  decisions with fresh approval.
- **S6. Manual operating runbook.** Document the manually started nightly dry run,
  morning digest review, and approved apply. Scheduling and digest delivery remain
  out of v1.

## Prohibitions
- v1: no delete, no archive, no reply, no mark-as-read.
- Never auto-apply labels on a schedule without human approval.
- v1 has no scheduler or digest-delivery infrastructure. The owner starts every run.
- Never commit secrets, tokens, or `.env` files.
- Never let Jev output bypass `policy.py`.
