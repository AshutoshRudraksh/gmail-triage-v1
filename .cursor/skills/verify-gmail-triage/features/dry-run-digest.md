# Dry-run digest

A dry run classifies queued inbox events and writes a local morning digest with Gmail permalinks, without changing Gmail labels.

## Sub-features

- `digest-render` prints `Gmail Triage Digest` and writes `$TRIAGE_STATE_DIR/digest.txt`.
- `digest-link` includes `https://mail.google.com/mail/u/0/#all/<thread_id>`.
- `digest-privacy` omits sender, subject, snippet, and body.
- `digest-limit` accepts `--limit 50` as the CLI default the user runs.

## How to get to it (user POV)

- Run `.venv/bin/python -m triage.dry_run --limit 50` in a terminal after a checkpoint exists.

## Driving it with verify-gmail-triage helpers

Preconditions:

- `helpers/doctor` printed `doctor ok`.
- Owner `.triage/` is not the state directory.
- Live Gmail and Jev are not required for this isolated drive.

- **Start isolated dry run.** Run `.cursor/skills/verify-gmail-triage/helpers/drive-dry-run`. The helper calls `triage.dry_run.main(["--limit", "50"])` with scratch `TRIAGE_STATE_DIR` and `TRIAGE_ENV_FILE`.
- **Read the digest.** Open `evidence/dry-run-digest/<run_id>/digest.txt` and `stdout.txt`. Both contain `Gmail Triage Digest` and `https://mail.google.com/mail/u/0/#all/t`.
- **Confirm privacy.** `digest.txt` does not contain `sender` or `a@example.com`.
- **Confirm files.** `exit_code.txt` is `0`. Scratch state also has `digest.txt`.
- **Proof.** Keep the evidence directory after cleanup. `result.txt` must read `pass`.

## Gotchas

- Running `python -m triage.dry_run` against the owner's `.env` calls real Gmail and Jev and may open a browser. That is a different path. Do not report it verified from this helper.
- Promo-noise outcomes are omitted from the digest. An empty review section is still a valid digest.
- Pytest passing is not digest proof.
