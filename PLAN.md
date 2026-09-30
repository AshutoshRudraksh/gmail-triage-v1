# Gmail Triage v1 plan

## Goal

Each manually started nightly dry run classifies new inbox events and renders a local
digest. A separately approved apply run adds reversible labels. v1 makes no
irreversible Gmail change.

## v1 scope

v1 includes Gmail history intake, retryable Jev classification, deterministic policy,
the local digest, and three exact managed labels:

- `Triage/NeedsAction`
- `Triage/PromoNoise`
- `Triage/SecurityReview`

v1 excludes delete, trash, archive, reply, send, forward, mark-as-read, automatic
label application, scheduler infrastructure, and digest delivery. The owner starts
both dry-run and apply commands manually. Every apply run requires fresh approval.

## Persistence model

Local state lives under `.triage/` and is excluded from source control.

- `.triage/checkpoint.json` records consumed Gmail history.
- `.triage/decisions.jsonl` records pending classification jobs, attempts, and
  completed decisions.
- `.triage/apply_attempts.jsonl` records every apply attempt and supplies the
  derived `pending`, `applied`, `no_delta`, or `superseded` application state.

The history checkpoint, classification state, and application state are independent.
Dry run may advance the checkpoint after it durably records all work from a history
record. A Jev timeout or network failure leaves a retryable pending job, so later
history work can continue. Apply consumes completed pending decisions, makes no Jev
calls, and leaves Gmail failures pending for a later retry. When one message has
multiple pending decisions, apply supersedes older decisions and reconciles only the
newest outcome.

The classification key is `(message_id, message_added_history_id,
classifier_version)`. A message outside `INBOX` is permanently handled for that
event. A later inbox re-addition has a new history ID and can be classified.

## Policy precedence

`triage/policy.py` evaluates inclusive thresholds in this order:

1. `scam_risk >= 4` selects only `Triage/SecurityReview` and adds the entry to the
   digest.
2. Otherwise, `needs_action >= 0.85` or `is_urgent >= 0.85` selects only
   `Triage/NeedsAction` and adds the entry to the digest.
3. Otherwise, `is_promo_noise >= 0.90` selects only `Triage/PromoNoise`.
4. Otherwise, `ReviewQueue` selects no label and adds the entry to the digest.

Apply idempotently creates missing exact managed labels after approval. It reconciles
only those three labels and never mutates another Gmail label.

## Commands

- `python -m pytest`
- `ruff check . && ruff format --check .`
- `python -m triage.dry_run --limit 50`
- `python -m triage.apply --limit 50`

Dry run uses exactly `https://www.googleapis.com/auth/gmail.readonly` and allows only
`users.getProfile`, `users.history.list`, `users.labels.list`,
`users.messages.list`, and `users.messages.get`. Apply uses exactly
`https://www.googleapis.com/auth/gmail.modify` and allows only
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

## Open risks

- Gmail can expire a history checkpoint. Recovery requires an explicitly approved
  bootstrap.
- One history record can exceed `--limit`. The run queues the full record and then
  stops so it cannot skip part of the record.
- Ambiguous valid results enter `ReviewQueue`. Transport and response failures remain
  pending classification work instead of becoming decisions.