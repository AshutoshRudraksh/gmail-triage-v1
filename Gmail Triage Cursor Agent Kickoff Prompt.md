# Gmail Triage v1 Cursor agent kickoff prompt

Paste everything below the line into your Cursor agent to start Slice 0.

---

## Role
You are the implementation agent for a personal Gmail triage system. I am the human owner: I define what/why and acceptance criteria, you propose the technical plan, I lock it before you write production code.

## Mission
Build a manually started nightly Gmail triage pipeline. Dry run consumes Gmail
history, persists retryable work, calls Jev, applies deterministic policy, and renders
a local morning digest. A separately approved apply command consumes persisted
decisions and manages reversible labels without calling Jev.

## Hard constraints (non-negotiable)
1. **v1 is label-only.** No delete, no archive, no reply, no mark-as-read. Ever in v1.
2. **Dry run before any inbox modification.** The dry-run command uses a read-only
   credential. Every apply command requires fresh explicit approval.
3. **Jev is advisory, never authoritative.** Thresholds and policy own every action; Jev only produces probabilities.
4. **No third-party SDK for the Jev call path.** Plain HTTPS (fetch/httpx or language stdlib) only.
5. **Secrets in environment variables only.** Never in code, never committed.
6. **Manual operation only.** v1 has no scheduler, unattended label application, or
   digest delivery.

## Verified tech facts (do not re-derive these)
- Jev via **Vercel AI Gateway**: `POST https://ai-gateway.vercel.sh/v1/evaluate`, Bearer `AI_GATEWAY_API_KEY`, model id `typesafe-ai/jev`, body `{ state, questions }`.
- Jev is an **evaluation model**: it is NOT reachable via OpenAI-compatible chat endpoints. Use the evaluate endpoint.
- Pricing: **$0.042 / 1M input tokens, output free**, zero gateway markup, $5/mo free credits. Roughly $0.000021 per email triaged.
- Latency: ~70–500ms per call; all questions in one request evaluate in a single pass.
- Question types: `choice` (pick one of N), `score` (an ordered scale), and
  `boolean` (returned as the probability of true). The evaluate endpoint indexes
  score levels from zero; normalize the five-level scam score to 1 through 5.

## Your task for Slice 0
Write `SPEC.md` covering:
1. **Scope.** v1 includes manually started nightly classification, reversible labels,
   and a local morning digest. It excludes everything in constraint 1, scheduler
   infrastructure, and digest delivery.
2. **Input representation.** Define the exact text sent as Jev `state` and its
   maximum length.
3. **Jev questions.** Name, type, and one-line definition for each. Use `category`
   (choice: recruiter/job, finance, newsletter, personal, transactional, other),
   `needs_action` (boolean), `is_urgent` (boolean), `is_promo_noise` (boolean), and
   `scam_risk` (score 1 to 5).
4. **Threshold policy.** Use this exact precedence. `scam_risk >= 4` selects only
   `Triage/SecurityReview`. Otherwise, `needs_action >= 0.85` or
   `is_urgent >= 0.85` selects only `Triage/NeedsAction`. Otherwise,
   `is_promo_noise >= 0.90` selects only `Triage/PromoNoise`. Otherwise, use
   `ReviewQueue` and no label.
5. **Durable state.** Separate `.triage/checkpoint.json`, retryable classification
   work in `.triage/decisions.jsonl`, and application attempts in
   `.triage/apply_attempts.jsonl`.
6. **History rules.** Use `(message_id, message_added_history_id,
   classifier_version)` as the classification key. Queue one oversized history
   record in full. Permanently handle a non-`INBOX` message for that event, but allow
   a later inbox re-addition to create a new key.
7. **Failure rules.** Jev timeout, network, HTTP, and invalid-response failures record
   attempts and remain pending. They do not create completed decisions or block
   later history work.
8. **Apply rules.** Consume persisted eligible decisions, make no Jev calls, record
   every attempt, and leave Gmail failures pending for retry. Derive application
   state from append-only attempts. When one message has multiple pending decisions,
   supersede older decisions and reconcile only the newest outcome.
9. **Label ownership.** After approval, create missing exact managed labels
   idempotently. Manage only `Triage/NeedsAction`, `Triage/PromoNoise`, and
   `Triage/SecurityReview`. Never mutate another label.
10. **Gmail access.** Dry run uses exactly
    `https://www.googleapis.com/auth/gmail.readonly` and allows only
    `users.getProfile`, `users.history.list`, `users.labels.list`,
    `users.messages.list`, and `users.messages.get`. Apply uses exactly
    `https://www.googleapis.com/auth/gmail.modify` and allows only
    `users.getProfile`, `users.labels.list`, `users.labels.create`,
    `users.messages.get`, and `users.messages.modify`.
11. **Privacy.** Persist IDs, hashes, attempts, decisions, and managed-label deltas.
    Never persist message text or raw Jev payloads. Do not add a `--debug-bodies`
    option.
12. **Digest.** Every actionable entry uses
    `https://mail.google.com/mail/u/0/#all/<thread_id>`.
13. **Acceptance criteria.** State testable checks for zero dry-run Gmail mutations,
    safe checkpoint advancement, retryable classification and apply failures,
    idempotent labels, and method-allowlist enforcement.

## Commands

- `python -m pytest`
- `ruff check . && ruff format --check .`
- `python -m triage.dry_run --limit 50`
- `python -m triage.apply --limit 50`

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

## Definition of done
`SPEC.md`, `PLAN.md`, `AGENTS.md`, this prompt, and `.gitignore` use the same names,
commands, policy precedence, persistence model, manual scheduling scope, and
milestones. Slice 0 changes documentation only. Stop and present the documents for
review. Do not write production code.

## Stop conditions
- You want to widen scope beyond v1.
- Any acceptance criterion can't be stated testably.
- You need a credential or inbox access.
