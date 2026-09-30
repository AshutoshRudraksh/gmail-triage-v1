from pathlib import Path

from tests.fakes import FakeGmail, FakeJev, answers
from triage import apply, dry_run
from triage.models import Checkpoint, ClassificationKey, CompletedDecision, LabelDelta
from triage.persistence import StateStore
from triage.policy import POLICY_VERSION, decide


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


def test_no_unattended_or_debug_body_options() -> None:
    apply_flags = {option for action in apply.parser()._actions for option in action.option_strings}
    dry_flags = {option for action in dry_run.parser()._actions for option in action.option_strings}
    assert "--yes" not in apply_flags
    assert "--debug-bodies" not in apply_flags
    assert "--debug-bodies" not in dry_flags


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
    assert "users.labels.create" not in methods
    digest = (tmp_path / "digest.txt").read_text()
    assert "https://mail.google.com/mail/u/0/#all/t" in digest
    assert "ReviewQueue" in digest
    assert "a@example.com" not in digest
    assert "hello" not in digest


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


def test_apply_main_never_constructs_jev(tmp_path: Path, monkeypatch) -> None:
    store = StateStore(tmp_path)
    answer = answers()
    policy = decide(answer)
    store.append_decision(
        CompletedDecision(
            ClassificationKey("m", "2", "1"),
            "t",
            "time",
            "run",
            "a" * 64,
            answer,
            POLICY_VERSION,
            policy,
            LabelDelta(),
        )
    )
    gmail = FakeGmail(
        {
            "users.labels.list": [
                {
                    "labels": [
                        {"name": "Triage/NeedsAction", "id": "needs"},
                        {"name": "Triage/PromoNoise", "id": "promo"},
                        {"name": "Triage/SecurityReview", "id": "security"},
                    ]
                }
            ],
            "users.messages.get": [{"labelIds": ["INBOX"]}],
        }
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Jev must not run during apply")

    monkeypatch.setattr("triage.jev_client.JevClient", forbidden)
    if hasattr(apply, "JevClient"):
        monkeypatch.setattr(apply, "JevClient", forbidden)
    monkeypatch.setattr("builtins.input", lambda _: apply.APPROVAL)
    monkeypatch.setenv("TRIAGE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(apply, "client_from_environment", lambda mode: gmail)
    assert apply.main(["--limit", "50"]) == 0
    assert {method for method, _ in gmail.calls} <= {
        "users.labels.list",
        "users.labels.create",
        "users.messages.get",
        "users.messages.modify",
    }
