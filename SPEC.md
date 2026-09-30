# Gmail Triage v1 Specification

## 1. Scope

### In scope

- Consume Gmail history and classify queued messages in a manually started nightly
  dry run.
- Classify each message with one Jev evaluation request containing all five questions.
- Pass Jev results through the deterministic policy in this specification.
- In dry-run mode, report proposed labels without changing Gmail.
- Persist completed decisions so a later approved apply run can use them without
  calling Jev.
- After explicit human approval for a specific apply run, create or apply only these
  reversible Gmail labels: `Triage/PromoNoise`, `Triage/NeedsAction`, and
  `Triage/SecurityReview`.
- Render a local morning digest containing the `Triage/NeedsAction`,
  `Triage/SecurityReview`, and review-queue entries from the run.
- Append privacy-limited records for classification and apply attempts.

Dry-run is the default. It can advance the Gmail history checkpoint after it durably
records work, but it cannot change Gmail. Label application is a separate command. It
requires explicit human approval on every run, consumes persisted decisions, and
never calls Jev. Jev supplies classifications and probabilities. Only the
deterministic policy below may select labels or digest membership.

### Out of scope

- Deleting, trashing, archiving, replying to, forwarding, sending, or marking messages
  read or unread.
- Changing stars, importance, categories, folders, or any Gmail state other than the
  three managed labels named above.
- Automatic remediation or interaction with messages assessed as scams.
- Scheduled or unattended execution, scheduler infrastructure, and digest delivery.
- Automatic label application without per-run human approval.
- Full message-body or attachment retrieval for classification.

The pipeline owns only the three exact managed label names. It never adds, removes,
renames, or changes any other label, including another label whose name starts with
`Triage/`. Removing the three managed labels restores a message's pre-triage
organization because v1 makes no other message-state change.

## 2. Jev input representation

One Gmail message produces one Jev request. Its `state` is exactly:

```text
Sender: <sender>
Subject: <subject>
Snippet: <snippet>
```

The three values are derived as follows:

- `sender`: the decoded, unfolded value of the message's `From` header, retaining both
  display name and address when present.
- `subject`: the decoded, unfolded value of the message's `Subject` header.
- `snippet`: Gmail's `snippet` field. No full body, quoted history, attachment content,
  recipient headers, or other headers are added.

Existing Gmail label names and IDs are not included in `state`, any question, or any
other Jev request field. They do not influence classification or threshold policy.

For each value, replace CR, LF, tab, and other Unicode control characters with a
space, collapse consecutive Unicode whitespace to one ASCII space, and trim leading
and trailing whitespace. Use `(missing)` when a field is absent or normalizes to an
empty string.

The complete `state` is limited to 8,000 Unicode code points. Before assembling it:

1. Limit `sender` to 512 code points.
2. Limit `subject` to 1,024 code points.
3. Give `snippet` all remaining capacity after counting the literal field names,
   spaces, and two newline characters.

Whenever a nonempty value exceeds its capacity, retain the first `capacity - 3` code
points and append `...`. The resulting assembled `state`, including labels and
newlines, must never exceed 8,000 code points.

The request uses plain HTTPS:

- Endpoint: `POST https://ai-gateway.vercel.sh/v1/evaluate`
- Authorization: bearer token from `AI_GATEWAY_API_KEY`
- Model: `typesafe-ai/jev`
- Body: `{ "state": <state>, "questions": <all questions below> }`

No third-party model SDK is permitted on this call path.

## 3. Durable work, decisions, and checkpointing

The local state directory is `.triage/`. The history checkpoint is
`.triage/checkpoint.json`. Durable pending work and completed decisions are stored in
`.triage/decisions.jsonl`. Apply attempts are stored in
`.triage/apply_attempts.jsonl`. The entire directory is excluded from source control.

The system keeps three states separate:

- The history checkpoint records the last Gmail history record whose events have
  been durably handled.
- A classification job represents one `messageAdded` event and is either `pending`
  or `completed`.
- A completed decision is immutable. Its application state is derived by folding
  apply-attempt records for its decision key and is `pending`, `applied`,
  `no_delta`, or `superseded`.

The classification key is `(message_id, message_added_history_id,
classifier_version)`. A completed decision suppresses another Jev call only for the
same key. This rule permits a future `messageAdded` event for the same message, such
as a message restored to the inbox, to produce a new decision. The policy version is
stored separately so policy changes can be audited without changing event identity.

Incremental dry runs use Gmail history instead of a rolling time window. For each
history record in ascending order, the run writes all of these results before it
advances the checkpoint past the record:

- A `pending` classification job for each distinct message in that record that has
  the `INBOX` label.
- A permanent `not_in_inbox` handling record for each message that does not have the
  `INBOX` label when inspected.

A `not_in_inbox` result applies only to that `messageAdded` event. The system does
not revisit it. If Gmail later adds the same message to the inbox, the new history
ID creates a new classification key and the message can be classified.

The checkpoint write is atomic. The run must durably write every event result for a
history record before it writes that record's history ID to the checkpoint. A crash
before the checkpoint write can repeat intake, but the classification key makes that
repeat idempotent.

For incremental intake, the default `--limit 50` is the target maximum number of
newly queued classification jobs. It is not a raw history-record limit. Intake stops
only between complete history records. If one record contains more eligible messages
than the remaining budget, the run queues the entire record, may exceed the target,
advances the checkpoint past that record, and then stops. This is the only
oversized-record behavior. It prevents gaps within a history record.

After intake, dry run attempts pending classification jobs in oldest-event order.
It makes at most `--limit` classification attempts per run, including retries of
jobs queued by earlier runs. Each attempt makes one Jev request. A timeout, network
failure, HTTP failure, or invalid Jev response records a classification attempt with
its error code and UTC timestamp. It does not create a completed decision. The job
remains `pending` and is retryable. Other pending jobs and later history records may
proceed because the failed job is already durable and no longer depends on
checkpoint replay.

A validated Jev response passes through policy and creates one immutable completed
decision. That decision starts with application state `pending`. Apply state never
changes the history checkpoint or classification state.

When no checkpoint exists, an explicitly approved bootstrap:

1. Reads the mailbox's current `historyId` as the bootstrap high-water mark.
2. Lists messages matching `in:inbox newer_than:1d`.
3. Writes a pending job for every returned message using the bootstrap high-water
   mark as the event ID.
4. Writes the checkpoint only after Gmail pagination is complete and every job is
   durable.

The bootstrap has no silent truncation. It discovers and durably queues every
matching message regardless of `--limit`; `--limit` still caps classification
attempts. If Gmail pagination fails, the bootstrap writes no checkpoint and retries
discovery later.

If Gmail rejects an expired or invalid `startHistoryId`, the run stops with a
checkpoint error. It does not substitute a time window or advance the checkpoint.
The owner must explicitly approve a new bootstrap.

## 4. Jev questions

All questions are submitted together in one request for a classification attempt.

| Name | Type | Definition |
| --- | --- | --- |
| `category` | `choice` | Choose exactly one of `recruiter/job`, `finance`, `newsletter`, `personal`, `transactional`, or `other` as the message's primary purpose. |
| `needs_action` | `boolean` | Probability of true. The sender asks the owner to take a concrete action or provide a response. |
| `is_urgent` | `boolean` | Probability of true. Delaying owner attention beyond the same day could cause a missed deadline, loss, or material problem. |
| `is_promo_noise` | `boolean` | Probability of true. The message is bulk promotional content with no personal relevance or required action. |
| `scam_risk` | `score` (1–5) | Rate fraud or phishing risk. 1 is clearly legitimate, 2 is probably legitimate, 3 is uncertain, 4 is probably malicious, and 5 is highly likely malicious. |

The evaluate endpoint indexes a five-level score from 0 through 4. The Jev boundary
adds one to the validated wire score so the stored policy-domain `scam_risk` remains
on the specified 1 through 5 scale.

`category` is persisted for review and digest context but does not directly cause an
action in v1. A malformed, missing, non-finite, or out-of-range answer is an invalid
Jev response. It leaves the classification job pending under the retry rule in
Section 3.

## 5. Deterministic threshold policy

The policy consumes only validated Jev results and evaluates rules in this exact
precedence order:

1. If `scam_risk >= 4`, select only `Triage/SecurityReview`. Include the message in
   the digest's security-review section.
2. Otherwise, if `needs_action >= 0.85` or `is_urgent >= 0.85`, select only
   `Triage/NeedsAction`. Include the message in the digest's needs-action section.
3. Otherwise, if `is_promo_noise >= 0.90`, select only `Triage/PromoNoise`. Omit the
   message from the digest.
4. Otherwise, select no label and use the `ReviewQueue` outcome. Include the message
   in the digest's review-queue section.

Threshold comparisons are inclusive. Each completed decision has exactly one policy
outcome: `Triage/SecurityReview`, `Triage/NeedsAction`, `Triage/PromoNoise`, or
`ReviewQueue`. The policy is the only component allowed to map Jev output to a label
or digest section.

## 6. Approved label application

`python -m triage.apply --limit 50` consumes persisted completed decisions with
derived application state `pending`. It never reads Gmail history and never invokes
Jev. The command requires fresh human approval every time it runs.

After approval, apply lists Gmail labels and idempotently creates any missing exact
managed label. It creates no other label. The three exact managed labels are:

- `Triage/NeedsAction`
- `Triage/PromoNoise`
- `Triage/SecurityReview`

Before touching a message, apply groups pending decisions by message ID. It selects
the completed decision with the newest Gmail `messageAdded` history ID and appends a
`superseded` attempt for each older pending decision. Bootstrap decisions are older
than later incremental decisions. This prevents a stale pending decision from
overwriting a newer outcome.

For each selected decision, apply gets the message's current label IDs and computes
a delta against only these three labels. A labeled outcome removes the other managed
labels and adds the selected managed label. `ReviewQueue` removes all managed labels
and adds none. Apply never mutates a Gmail system label, another user label, or
another label under `Triage/`.

For a nonempty delta, apply sends one `users.messages.modify` request whose body
contains both complete `addLabelIds` and `removeLabelIds` arrays. A successful
request appends an `applied` attempt. An empty delta records `no_delta` without a
modify call. A Gmail get or modify failure records the attempt and error, leaves the
derived state `pending`, and permits a later apply run to retry it. Every decision
attempt, including superseded, no-delta, and failed attempts, appends a record to
`.triage/apply_attempts.jsonl`.

## 7. Digest

The local digest groups entries in this order: `Triage/SecurityReview`,
`Triage/NeedsAction`, then `ReviewQueue`. Each entry includes the category, relevant
scores or probabilities, proposed or applied label state, and this Gmail permalink:

```text
https://mail.google.com/mail/u/0/#all/<thread_id>
```

The digest uses the stored Gmail thread ID in the link and does not present an opaque
message ID as the action target. It contains no sender, subject, snippet, or body.
Digest delivery is out of scope.

## 8. Privacy and persistence

Secrets, OAuth tokens, and credential paths come only from environment variables or
an environment-configured local token path. They are never written to logs, records,
fixtures, or source control.

The append-only decision log stores:

- The UTC timestamp, run ID, classification key, Gmail thread ID, and attempt status.
- The SHA-256 hash of the exact UTF-8 encoded Jev `state` in lowercase hexadecimal.
- Validated answers and returned probabilities for completed decisions.
- The classifier version, policy version, policy outcome, and proposed managed-label
  delta for completed decisions.
- A stable error code for failed attempts.

The apply-attempt log stores the decision key, UTC timestamp, run ID, requested
managed-label delta, result, and stable Gmail error code. It does not store message
text or non-managed label names.

The decision log, apply-attempt log, digest, and console logs never store sender,
subject, snippet, full body, headers, attachment content, credentials, or raw Jev
request or response payloads. There is no `--debug-bodies` option.

## 9. Gmail authorization and method allowlists

Dry run uses exactly the
`https://www.googleapis.com/auth/gmail.readonly` OAuth scope. Its allowlisted
methods are:

- `users.getProfile`
- `users.history.list`
- `users.labels.list`
- `users.messages.list`
- `users.messages.get`

The dry-run client rejects every other Gmail method before dispatch. It cannot
create labels or call a mutation method.

Apply uses exactly the `https://www.googleapis.com/auth/gmail.modify` OAuth scope.
Its method allowlist is:

- `users.getProfile`
- `users.labels.list`
- `users.labels.create`
- `users.messages.get`
- `users.messages.modify`

The apply client rejects every other Gmail method before dispatch. In particular, it
cannot list messages, consume history, send mail, create drafts, trash messages,
delete messages, or modify threads.

## 10. Commands and milestones

The project commands are:

- `python -m pytest`
- `ruff check . && ruff format --check .`
- `python -m triage.dry_run --limit 50`
- `python -m triage.apply --limit 50`

Implementation follows these milestones:

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

## 11. Acceptance criteria

Dry-run behavior is accepted when:

1. `python -m triage.dry_run --limit 50` uses only the five dry-run methods in
   Section 9 and makes zero Gmail mutation calls.
2. Sampled `labelIds` are identical before and after the run.
3. A Jev timeout or network failure records an attempt, leaves the job pending, and
   does not create a completed decision or block later history work.
4. A retry of a pending job can create one completed decision without another
   decision for the same classification key.
5. The digest renders locally without a Gmail send or draft operation.

Incremental intake is accepted when:

1. A checkpoint advances only after every event in the history record has a durable
   pending job, completed decision, or `not_in_inbox` record.
2. A history record that exceeds the remaining limit is queued in full, and the next
   run begins after that record.
3. A non-inbox event is never reconsidered. A later inbox re-addition gets a new
   classification key and can be classified.
4. A crash before checkpoint replacement can repeat intake without creating
   duplicate jobs.
5. An expired checkpoint stops the run and requires an approved bootstrap.

Apply behavior is accepted when:

1. Apply makes zero Jev calls and consumes only persisted completed decisions.
2. Missing exact managed labels are created once after approval. Existing managed
   labels are reused.
3. Reconciliation changes only the three managed labels.
4. One nonempty reconciliation uses one `users.messages.modify` call with both label
   ID arrays.
5. Every attempt is recorded. A Gmail failure leaves the decision pending and a
   later apply run can retry it.
6. A second successful apply for the same decision makes no mutation.
7. The method allowlist rejects every Gmail method not listed for apply in Section 9.
8. When two pending decisions exist for one message, apply marks the older decision
   `superseded` and reconciles only the newest outcome.

## 12. Slice 0 completion boundary

Slice 0 changes documentation only. No production pipeline, Gmail access, Jev call,
credential setup, or inbox operation is part of this slice. Implementation begins
only after the human owner approves and locks this specification.
