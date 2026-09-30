from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def python_bin() -> Path:
    return repo_root() / ".venv" / "bin" / "python"


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_dir(run_id: str) -> Path:
    path = skill_root() / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def evidence_dir(feature: str, run_id: str) -> Path:
    path = skill_root() / "evidence" / feature / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def require_venv() -> Path:
    binary = python_bin()
    if not binary.is_file():
        raise SystemExit(f"missing {binary}")
    return binary


def reexec_venv() -> None:
    binary = require_venv()
    venv_prefix = (repo_root() / ".venv").resolve()
    if Path(sys.prefix).resolve() != venv_prefix:
        os.execv(str(binary), [str(binary), *sys.argv])


def isolated_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for name in (
        "AI_GATEWAY_API_KEY",
        "GOOGLE_CLIENT_SECRET_PATH",
        "GOOGLE_TOKEN_PATH",
        "TRIAGE_STATE_DIR",
        "TRIAGE_ENV_FILE",
    ):
        env.pop(name, None)
    return env
