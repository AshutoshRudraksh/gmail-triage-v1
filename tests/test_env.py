from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from triage.env import EnvError, load_env, parse_env


def test_parse_env_skips_comments_and_empty_values() -> None:
    parsed = parse_env(
        "\n".join(
            [
                "# comment",
                "AI_GATEWAY_API_KEY=",
                'GOOGLE_TOKEN_PATH="secrets/token.json"',
                "export GOOGLE_CLIENT_SECRET_PATH=secrets/credentials.json",
            ]
        )
    )
    assert parsed == {
        "GOOGLE_TOKEN_PATH": "secrets/token.json",
        "GOOGLE_CLIENT_SECRET_PATH": "secrets/credentials.json",
    }


def test_parse_env_rejects_malformed_line() -> None:
    with pytest.raises(EnvError, match="invalid env line 1"):
        parse_env("not-a-binding")


def test_load_env_does_not_override_process_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AI_GATEWAY_API_KEY=from-file\nTRIAGE_STATE_DIR=from-file\n")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "from-process")
    monkeypatch.delenv("TRIAGE_STATE_DIR", raising=False)
    load_env(env_file)
    assert os.environ["AI_GATEWAY_API_KEY"] == "from-process"
    assert os.environ["TRIAGE_STATE_DIR"] == "from-file"


def test_missing_env_file_is_a_no_op(tmp_path: Path) -> None:
    load_env(tmp_path / "missing.env")


def test_env_example_has_required_names_and_no_secret_values() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "AI_GATEWAY_API_KEY=" in text
    assert "GOOGLE_CLIENT_SECRET_PATH=secrets/credentials.json" in text
    assert "GOOGLE_TOKEN_PATH=secrets/token.json" in text
    assert "sk-" not in text
    assert "AIza" not in text
    assert "vck_" not in text


def test_secret_files_are_ignored_and_example_is_not() -> None:
    for path in (
        ".env",
        "secrets/credentials.json",
        "secrets/token.json",
        "client_secret.json",
        ".cursor/debug-50c9f7.log",
        "gmail_triage.egg-info/PKG-INFO",
        ".coverage",
        "htmlcov/index.html",
        ".cursor/skills/verify-gmail-triage/evidence/probe.txt",
        ".cursor/skills/verify-gmail-triage/runs/probe.txt",
    ):
        ignored = subprocess.run(["git", "check-ignore", "-q", path], check=False)
        assert ignored.returncode == 0, path
    example = subprocess.run(["git", "check-ignore", "-q", ".env.example"], check=False)
    assert example.returncode == 1
