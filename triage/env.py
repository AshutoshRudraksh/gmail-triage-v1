from __future__ import annotations

import os
import re
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvError(ValueError):
    pass


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise EnvError(f"invalid env line {line_number}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not _KEY.fullmatch(key):
            raise EnvError(f"invalid env line {line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            result[key] = value
    return result


def env_file_path() -> Path:
    return Path(os.environ.get("TRIAGE_ENV_FILE", ".env"))


def load_env(path: Path | None = None) -> None:
    target = env_file_path() if path is None else path
    if not target.is_file():
        return
    for key, value in parse_env(target.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)
