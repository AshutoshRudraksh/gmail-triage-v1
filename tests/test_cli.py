from pathlib import Path

from tests.fakes import FakeGmail, FakeJev, answers
from triage import apply, dry_run
from triage.models import Checkpoint
from triage.persistence import StateStore


def test_apply_requires_fresh_exact_approval(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    monkeypatch.setattr(
        apply,
        "client_from_environment",
        lambda _: (_ for _ in ()).throw(AssertionError("must not authenticate")),
    )
    assert apply.main([]) == 2


def test_dry_run_bootstrap_requires_exact_approval(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "bootstrap")
    monkeypatch.setattr(
        dry_run,
        "client_from_environment",
        lambda _: (_ for _ in ()).throw(AssertionError("must not authenticate")),
    )
    assert dry_run.main(["--bootstrap"]) == 2


def test_no_unattended_approval_option() -> None:
    option_strings = {
        option for action in apply.parser()._actions for option in action.option_strings
    }
    assert "--yes" not in option_strings


def test_dry_run_command_lists_labels_and_writes_digest(tmp_path: Path, monkeypatch) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(Checkpoint("1"))
    gmail = FakeGmail(
        {
            "users.history.list": [
                {
                    "history": [
                        {
                            "id": "2",
                            "messagesAdded": [
                                {"message": {"id": "m", "threadId": "t", "labelIds": ["INBOX"]}}
                            ],
                        }
                    ]
                }
            ],
            "users.labels.list": [{"labels": []}],
            "users.messages.get": [
                {
                    "id": "m",
                    "threadId": "t",
                    "labelIds": ["INBOX"],
                    "snippet": "hello",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "a@example.com"},
                            {"name": "Subject", "value": "Hi"},
                        ]
                    },
                }
            ],
        }
    )
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "secret")
    monkeypatch.setenv("TRIAGE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(dry_run, "client_from_environment", lambda mode: gmail)
    monkeypatch.setattr(dry_run, "JevClient", lambda key: FakeJev(answers()))
    assert dry_run.main(["--limit", "50"]) == 0
    methods = [method for method, _ in gmail.calls]
    assert "users.labels.list" in methods
    assert "users.messages.modify" not in methods
    digest = (tmp_path / "digest.txt").read_text()
    assert "https://mail.google.com/mail/u/0/#all/t" in digest
    assert "ReviewQueue" in digest


def test_dry_run_loads_gateway_key_from_env_file(tmp_path: Path, monkeypatch) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(Checkpoint("1"))
    env_file = tmp_path / ".env"
    env_file.write_text("AI_GATEWAY_API_KEY=from-file\n")
    gmail = FakeGmail(
        {
            "users.history.list": [{"history": []}],
            "users.labels.list": [{"labels": []}],
        }
    )
    captured: dict[str, str] = {}
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("TRIAGE_ENV_FILE", str(env_file))
    monkeypatch.setenv("TRIAGE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(dry_run, "client_from_environment", lambda mode: gmail)

    def fake_jev(key: str) -> FakeJev:
        captured["key"] = key
        return FakeJev(answers())

    monkeypatch.setattr(dry_run, "JevClient", fake_jev)
    assert dry_run.main(["--limit", "50"]) == 0
    assert captured["key"] == "from-file"
