from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from .env import EnvError, load_env
from .gmail_client import client_from_environment
from .persistence import PersistenceError, StateStore
from .pipeline import apply_decisions

APPROVAL = "APPLY TRIAGE LABELS"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Approved Gmail triage label application")
    result.add_argument("--limit", type=int, default=50)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.limit < 1:
        print("--limit must be positive", file=sys.stderr)
        return 2
    try:
        load_env()
    except EnvError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        answer = input(f"Type {APPROVAL} to modify Gmail labels: ")
    except EOFError:
        answer = ""
    if answer != APPROVAL:
        print("Apply not approved.", file=sys.stderr)
        return 2
    state_dir = Path(os.environ.get("TRIAGE_STATE_DIR", ".triage"))
    store = StateStore(state_dir)
    try:
        gmail = client_from_environment("apply")
        with store.lock("apply"):
            count = apply_decisions(gmail, store, arguments.limit, run_id=str(uuid.uuid4()))
        print(f"Applied or reconciled {count} decisions.")
    except (PersistenceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
