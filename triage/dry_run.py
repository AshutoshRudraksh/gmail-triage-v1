from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from .digest import entries_for, render_digest
from .env import EnvError, load_env
from .gmail_client import client_from_environment
from .jev_client import JevClient
from .persistence import PersistenceError, StateStore
from .pipeline import (
    CheckpointError,
    bootstrap_intake,
    classify_pending,
    incremental_intake,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Read-only Gmail triage dry run")
    result.add_argument("--limit", type=int, default=50)
    result.add_argument("--bootstrap", action="store_true")
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
    if arguments.bootstrap:
        try:
            answer = input("Type BOOTSTRAP to approve rebuilding the Gmail checkpoint: ")
        except EOFError:
            answer = ""
        if answer != "BOOTSTRAP":
            print("Bootstrap not approved.", file=sys.stderr)
            return 2
    api_key = os.environ.get("AI_GATEWAY_API_KEY")
    if not api_key:
        print("AI_GATEWAY_API_KEY is required", file=sys.stderr)
        return 2
    state_dir = Path(os.environ.get("TRIAGE_STATE_DIR", ".triage"))
    store = StateStore(state_dir)
    run_id = str(uuid.uuid4())
    try:
        gmail = client_from_environment("dry_run")
        with store.lock("dry-run"):
            if arguments.bootstrap:
                bootstrap_intake(gmail, store, run_id)
            else:
                incremental_intake(gmail, store, arguments.limit, run_id)
            label_response = gmail.call("users.labels.list", userId="me")
            gmail_labels = tuple(label_response.get("labels", ()))
            completed = classify_pending(
                gmail,
                JevClient(api_key),
                store,
                arguments.limit,
                run_id,
                gmail_labels,
            )
            digest = render_digest(entries_for(completed))
            digest_path = state_dir / "digest.txt"
            digest_path.write_text(digest, encoding="utf-8")
            print(digest)
    except (CheckpointError, PersistenceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
