# Gmail method allowlist

Dry run may only use read methods. It must not modify messages or create labels.

## Sub-features

- `allow-read` may call `users.getProfile`, `users.history.list`, `users.labels.list`, `users.messages.list`, and `users.messages.get`.
- `deny-mutate` records zero `users.messages.modify` and `users.labels.create` calls.
- `digest-without-send` writes a local file and never sends mail.

## How to get to it (user POV)

- Run a dry run (`.venv/bin/python -m triage.dry_run --limit 50`) and inspect that Gmail labels did not change.

## Driving it with verify-gmail-triage helpers

Preconditions:

- Isolated digest drive from [Dry-run digest](./dry-run-digest.md).

- **Start the isolated dry run.** Run `.cursor/skills/verify-gmail-triage/helpers/drive-dry-run`.
- **Read the method list.** Open `evidence/dry-run-digest/<run_id>/gmail_calls.json`. Methods are a subset of the dry-run allowlist.
- **Confirm no mutation.** `mutating_methods.txt` is empty. `result.txt` is `pass`.

## Gotchas

- A live dry run still uses the network. Prove skipped mutations from the recorded method list, not from the command name.
- Apply mode is a different allowlist and is not proven by a dry-run drive.
- `users.labels.list` on dry run is required for proposed label names. That is a read, not a mutation.
