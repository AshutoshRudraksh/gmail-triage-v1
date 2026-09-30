# Gmail triage

A manually started nightly pipeline. Dry run consumes Gmail history, classifies mail with Jev, and writes a local digest. Apply consumes those decisions and adds only three reversible labels after you type an approval phrase.

v1 does not delete, archive, reply, send, or mark mail read. It has no scheduler.

## Setup

Python 3.11+ and a virtualenv.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

Put your Vercel AI Gateway key in `.env` as `AI_GATEWAY_API_KEY`. Download a Google Cloud OAuth desktop client JSON to `secrets/credentials.json`. Enable the Gmail API on that project. The first authorized run writes `secrets/token.json`.

Never commit `.env`, `secrets/credentials.json`, or `secrets/token.json`. `.env.example` is the template only.

## Commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python -m triage.dry_run --limit 50
.venv/bin/python -m triage.dry_run --bootstrap --limit 50
.venv/bin/python -m triage.apply --limit 50
```

Dry run is read-only. The first incremental run needs `--bootstrap` and the typed word `BOOTSTRAP`. Apply needs the typed phrase `APPLY TRIAGE LABELS` every time. There is no `--yes` flag.

Local state lives in `.triage/` (checkpoint, decisions, digest). That directory is gitignored.

## Labels

Apply may create and reconcile only:

- `Triage/NeedsAction`
- `Triage/PromoNoise`
- `Triage/SecurityReview`

Policy order is security review, then needs action, then promo noise, else review queue with no label.

## Docs

`SPEC.md` is the behavior contract. `AGENTS.md` is for coding agents. `PLAN.md` is the milestone list.
