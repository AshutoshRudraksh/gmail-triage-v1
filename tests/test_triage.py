from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeGmail, FakeJev, FakeService, answers
from triage.digest import entries_for, render_digest
from triage.gmail_client import (
    APPLY_METHODS,
    DRY_RUN_METHODS,
    MODIFY_SCOPE,
    READONLY_SCOPE,
    GmailClient,
    MethodNotAllowed,
)
from triage.jev_client import (
    CATEGORIES,
    QUESTIONS,
    JevClient,
    JevError,
    build_state,
    validate_response,
)
from triage.labels import proposed_reconciliation, reconcile_labels
from triage.models import (
    ApplyAttempt,
    ApplyResult,
    ClassificationFailure,
    ClassificationKey,
    CompletedDecision,
    LabelDelta,
    ManagedLabelMap,
    PendingJob,
    PolicyOutcome,
    ValidatedAnswers,
)
from triage.persistence import PersistenceError, StateStore
from triage.pipeline import (
    CheckpointError,
    apply_decisions,
    bootstrap_intake,
    classify_pending,
    incremental_intake,
)
from triage.policy import POLICY_VERSION, decide, proposed_delta


def decision(message_id: str, history_id: str, outcome: PolicyOutcome) -> CompletedDecision:
    answer = answers(
        scam_risk=4.0 if outcome is PolicyOutcome.SECURITY_REVIEW else 1.0,
        needs_action=0.9 if outcome is PolicyOutcome.NEEDS_ACTION else 0.1,
        is_promo_noise=0.95 if outcome is PolicyOutcome.PROMO_NOISE else 0.1,
    )
    policy = decide(answer)
    return CompletedDecision(
        ClassificationKey(message_id, history_id, "1"),
        f"thread-{message_id}",
        "2026-01-01T00:00:00Z",
        "run",
        "a" * 64,
        answer,
        POLICY_VERSION,
        policy,
        proposed_delta(policy),
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"scam_risk": 4, "needs_action": 1, "is_promo_noise": 1}, PolicyOutcome.SECURITY_REVIEW),
        ({"needs_action": 0.85}, PolicyOutcome.NEEDS_ACTION),
        ({"is_urgent": 0.85}, PolicyOutcome.NEEDS_ACTION),
        ({"is_promo_noise": 0.9}, PolicyOutcome.PROMO_NOISE),
        ({}, PolicyOutcome.REVIEW_QUEUE),
    ],
)
def test_policy_precedence_and_inclusive_thresholds(
    changes: dict[str, float], expected: PolicyOutcome
) -> None:
    assert decide(answers(**changes)).outcome is expected


def test_state_normalization_and_exact_limit() -> None:
    state = build_state(" A\r\n\tB ", None, "x" * 9000)
    assert state.startswith("Sender: A B\nSubject: (missing)\nSnippet: ")
    assert len(state) == 8000
    assert state.endswith("...")


def valid_wire_response() -> dict[str, Any]:
    return {
        "answers": {
            "category": {
                "type": "choice",
                "choice": "finance",
                "probabilities": {name: 1 / 6 for name in CATEGORIES},
            },
            "needs_action": {"type": "boolean", "probability": 0.85},
            "is_urgent": {"type": "boolean", "probability": 0.2},
            "is_promo_noise": {"type": "boolean", "probability": 0.0},
            "scam_risk": {
                "type": "score",
                "score": 3.0,
                "probabilities": {str(index): 0.2 for index in range(5)},
            },
        }
    }


def test_response_is_strict_and_normalizes_score() -> None:
    result = validate_response(valid_wire_response())
    assert result.scam_risk == 4.0
    invalid = valid_wire_response()
    invalid["answers"]["needs_action"]["type"] = "noul"
    with pytest.raises(JevError, match="invalid_response"):
        validate_response(invalid)


def test_response_rejects_nonfinite_and_missing_probabilities() -> None:
    invalid = valid_wire_response()
    invalid["answers"]["scam_risk"]["score"] = float("nan")
    with pytest.raises(JevError):
        validate_response(invalid)
    invalid = valid_wire_response()
    del invalid["answers"]["category"]["probabilities"]["other"]
    with pytest.raises(JevError):
        validate_response(invalid)


def test_jev_request_uses_current_wire_format() -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(valid_wire_response()).encode()

    def opener(request: Any, timeout: float) -> Response:
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    JevClient("secret", opener=opener).evaluate("state")
    assert captured["url"] == "https://ai-gateway.vercel.sh/v1/evaluate"
    assert captured["body"] == {
        "model": "typesafe-ai/jev",
        "state": "state",
        "questions": QUESTIONS,
    }
    assert QUESTIONS["needs_action"]["type"] == "boolean"
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_gmail_allowlists_reject_before_dispatch() -> None:
    dry_run = GmailClient(FakeService(), DRY_RUN_METHODS)
    apply_client = GmailClient(FakeService(), APPLY_METHODS)
    with pytest.raises(MethodNotAllowed, match="users.messages.modify"):
        dry_run.call("users.messages.modify", userId="me")
    with pytest.raises(MethodNotAllowed, match="users.history.list"):
        apply_client.call("users.history.list", userId="me", startHistoryId="1")
    assert dry_run.allowed_methods == {
        "users.getProfile",
        "users.history.list",
        "users.labels.list",
        "users.messages.list",
        "users.messages.get",
    }
    assert apply_client.allowed_methods == {
        "users.getProfile",
        "users.labels.list",
        "users.labels.create",
        "users.messages.get",
        "users.messages.modify",
    }
    assert READONLY_SCOPE == "https://www.googleapis.com/auth/gmail.readonly"
    assert MODIFY_SCOPE == "https://www.googleapis.com/auth/gmail.modify"


def test_checkpoint_and_duplicate_pending_are_idempotent(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    job = PendingJob(
        ClassificationKey("m", "10", "1"),
        "t",
        "2026-01-01T00:00:00Z",
        "r",
    )
    assert store.append_decision(job)
    assert not store.append_decision(job)
    store.write_checkpoint(checkpoint := __import__("triage").Checkpoint("10"))
    assert store.read_checkpoint() == checkpoint
    assert len(store.pending_jobs()) == 1


def test_strict_decoder_rejects_unknown_fields(tmp_path: Path) -> None:
    (tmp_path / "decisions.jsonl").write_text('{"event":"pending","extra":true}\n')
    with pytest.raises(PersistenceError):
        StateStore(tmp_path).decision_events()


def test_incremental_queues_complete_oversized_record_and_orders_numerically(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(__import__("triage").Checkpoint("9"))
    messages = [{"id": f"m{i}", "threadId": f"t{i}", "labelIds": ["INBOX"]} for i in range(3)]
    gmail = FakeGmail(
        {
            "users.history.list": [
                {
                    "history": [
                        {"id": "11", "messagesAdded": [{"message": messages[2]}]},
                        {
                            "id": "10",
                            "messagesAdded": [
                                {"message": messages[0]},
                                {"message": messages[0]},
                                {"message": messages[1]},
                            ],
                        },
                    ]
                }
            ]
        }
    )
    assert incremental_intake(gmail, store, 1, "run") == 2
    assert store.read_checkpoint().history_id == "10"
    assert [job.key.message_id for job in store.pending_jobs()] == ["m0", "m1"]


def test_non_inbox_then_readd_creates_new_key(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(__import__("triage").Checkpoint("1"))
    gmail = FakeGmail(
        {
            "users.history.list": [
                {
                    "history": [
                        {
                            "id": "2",
                            "messagesAdded": [
                                {"message": {"id": "m", "threadId": "t", "labelIds": []}}
                            ],
                        },
                        {
                            "id": "3",
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "m",
                                        "threadId": "t",
                                        "labelIds": ["INBOX"],
                                    }
                                }
                            ],
                        },
                    ]
                }
            ]
        }
    )
    assert incremental_intake(gmail, store, 50, "run") == 1
    assert store.pending_jobs()[0].key.message_added_history_id == "3"


def test_replayed_record_does_not_reverse_durable_handling(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(__import__("triage").Checkpoint("9"))
    job = PendingJob(ClassificationKey("m", "10", "1"), "t", "time", "first")
    store.append_decision(job)
    gmail = FakeGmail(
        {
            "users.history.list": [
                {
                    "history": [
                        {
                            "id": "10",
                            "messagesAdded": [
                                {"message": {"id": "m", "threadId": "t", "labelIds": []}}
                            ],
                        }
                    ]
                }
            ]
        }
    )
    assert incremental_intake(gmail, store, 50, "replay") == 0
    assert store.pending_jobs() == (job,)
    assert len(store.decision_events()) == 1
    assert store.read_checkpoint().history_id == "10"


def test_expired_checkpoint_stops_without_advancing(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.write_checkpoint(__import__("triage").Checkpoint("9"))

    class ExpiredHistory(Exception):
        def __init__(self) -> None:
            self.resp = type("Resp", (), {"status": "404"})()

    gmail = FakeGmail({"users.history.list": [ExpiredHistory()]})
    with pytest.raises(CheckpointError, match="expired"):
        incremental_intake(gmail, store, 50, "run")
    assert store.read_checkpoint().history_id == "9"
    assert store.decision_events() == ()


def test_bootstrap_pagination_failure_writes_no_checkpoint(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    gmail = FakeGmail(
        {
            "users.getProfile": [{"historyId": "20"}],
            "users.messages.list": [
                {"messages": [{"id": "m"}], "nextPageToken": "next"},
                RuntimeError("failure"),
            ],
        }
    )
    with pytest.raises(RuntimeError):
        bootstrap_intake(gmail, store, "run")
    assert store.read_checkpoint() is None
    assert store.decision_events() == ()


def test_failed_classification_retries_then_completes(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_decision(PendingJob(ClassificationKey("m", "2", "1"), "t", "time", "run"))
    message = {
        "id": "m",
        "threadId": "t",
        "snippet": "hello",
        "payload": {"headers": [{"name": "From", "value": "a@example.com"}]},
    }
    gmail = FakeGmail({"users.messages.get": [message, message]})
    assert not classify_pending(gmail, FakeJev(JevError("timeout")), store, 1, "r1")
    completed = classify_pending(gmail, FakeJev(answers()), store, 1, "r2")
    assert len(completed) == 1
    assert store.pending_jobs() == ()
    assert [
        event.error_code
        for event in store.decision_events()
        if isinstance(event, ClassificationFailure)
    ] == ["timeout"]


def test_classification_timeout_does_not_block_later_jobs(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_decision(PendingJob(ClassificationKey("a", "2", "1"), "ta", "time", "run"))
    store.append_decision(PendingJob(ClassificationKey("b", "3", "1"), "tb", "time", "run"))
    first = {
        "id": "a",
        "threadId": "ta",
        "snippet": "one",
        "payload": {"headers": [{"name": "From", "value": "a@example.com"}]},
    }
    second = {
        "id": "b",
        "threadId": "tb",
        "snippet": "two",
        "payload": {"headers": [{"name": "From", "value": "b@example.com"}]},
    }

    class SelectiveJev:
        def evaluate(self, state: str) -> ValidatedAnswers:
            if "one" in state:
                raise JevError("timeout")
            return answers()

    completed = classify_pending(
        FakeGmail({"users.messages.get": [first, second]}),
        SelectiveJev(),
        store,
        50,
        "run",
    )
    assert [item.key.message_id for item in completed] == ["b"]
    assert [job.key.message_id for job in store.pending_jobs()] == ["a"]


def test_classify_proposed_delta_uses_current_managed_labels(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_decision(PendingJob(ClassificationKey("m", "2", "1"), "t", "time", "run"))
    completed = classify_pending(
        FakeGmail(
            {
                "users.messages.get": [
                    {
                        "id": "m",
                        "threadId": "t",
                        "labelIds": ["INBOX", "promo"],
                        "snippet": "hello",
                        "payload": {"headers": [{"name": "From", "value": "a@example.com"}]},
                    }
                ]
            }
        ),
        FakeJev(answers(needs_action=0.9)),
        store,
        1,
        "run",
        ({"name": "Triage/PromoNoise", "id": "promo"},),
    )
    assert completed[0].proposed_delta == LabelDelta(
        add=("Triage/NeedsAction",),
        remove=("Triage/PromoNoise",),
    )


def test_digest_order_link_and_privacy() -> None:
    decisions = (
        decision("review", "1", PolicyOutcome.REVIEW_QUEUE),
        decision("security", "2", PolicyOutcome.SECURITY_REVIEW),
        decision("action", "3", PolicyOutcome.NEEDS_ACTION),
        decision("promo", "4", PolicyOutcome.PROMO_NOISE),
    )
    text = render_digest(entries_for(decisions))
    assert text.index("SecurityReview") < text.index("NeedsAction") < text.index("ReviewQueue")
    assert "https://mail.google.com/mail/u/0/#all/thread-security" in text
    assert "thread-promo" not in text
    assert "sender" not in text.lower() and "subject" not in text.lower()


def test_label_reconciliation_only_uses_managed_ids() -> None:
    labels = ManagedLabelMap("needs", "promo", "security")
    delta = reconcile_labels(["INBOX", "other", "promo"], PolicyOutcome.NEEDS_ACTION, labels)
    assert delta == LabelDelta(add=("needs",), remove=("promo",))


def test_proposed_reconciliation_maps_existing_custom_label_ids() -> None:
    labels = (
        {"name": "Triage/PromoNoise", "id": "promo"},
        {"name": "Unmanaged", "id": "other"},
    )
    delta = proposed_reconciliation(
        ["INBOX", "promo", "other"],
        PolicyOutcome.NEEDS_ACTION,
        labels,
    )
    assert delta == LabelDelta(
        add=("Triage/NeedsAction",),
        remove=("Triage/PromoNoise",),
    )


def test_apply_creates_reconciles_and_is_idempotent(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_decision(decision("m", "2", PolicyOutcome.NEEDS_ACTION))
    gmail = FakeGmail(
        {
            "users.labels.list": [{"labels": [{"name": "Triage/NeedsAction", "id": "needs"}]}],
            "users.labels.create": [
                {"name": "Triage/PromoNoise", "id": "promo"},
                {"name": "Triage/SecurityReview", "id": "security"},
            ],
            "users.messages.get": [{"labelIds": ["INBOX", "promo"]}],
            "users.messages.modify": [{}],
        }
    )
    assert apply_decisions(gmail, store, 50, "apply") == 1
    modify = [call for call in gmail.calls if call[0] == "users.messages.modify"]
    assert modify[0][1]["body"] == {
        "addLabelIds": ["needs"],
        "removeLabelIds": ["promo"],
    }
    idle = FakeGmail(
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
            "users.messages.get": [RuntimeError("must not get a completed decision")],
        }
    )
    assert apply_decisions(idle, store, 50, "again") == 0
    assert [method for method, _ in idle.calls] == ["users.labels.list"]


def test_apply_supersedes_old_and_retries_failure(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    old = decision("m", "2", PolicyOutcome.PROMO_NOISE)
    new = decision("m", "10", PolicyOutcome.REVIEW_QUEUE)
    store.append_decision(old)
    store.append_decision(new)
    labels = {
        "labels": [
            {"name": "Triage/NeedsAction", "id": "needs"},
            {"name": "Triage/PromoNoise", "id": "promo"},
            {"name": "Triage/SecurityReview", "id": "security"},
        ]
    }
    failed = FakeGmail(
        {
            "users.labels.list": [labels],
            "users.messages.get": [RuntimeError("get")],
        }
    )
    assert apply_decisions(failed, store, 50, "first") == 0
    attempts = store.apply_attempts()
    assert attempts[0].key == old.key and attempts[0].result is ApplyResult.SUPERSEDED
    assert attempts[1].key == new.key and attempts[1].result is ApplyResult.FAILED
    retry = FakeGmail(
        {
            "users.labels.list": [labels],
            "users.messages.get": [{"labelIds": ["promo"]}],
            "users.messages.modify": [{}],
        }
    )
    assert apply_decisions(retry, store, 50, "second") == 1


def test_remote_success_before_log_converges_to_no_delta(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_decision(decision("m", "2", PolicyOutcome.NEEDS_ACTION))
    labels = {
        "labels": [
            {"name": "Triage/NeedsAction", "id": "needs"},
            {"name": "Triage/PromoNoise", "id": "promo"},
            {"name": "Triage/SecurityReview", "id": "security"},
        ]
    }
    gmail = FakeGmail(
        {
            "users.labels.list": [labels],
            "users.messages.get": [{"labelIds": ["needs"]}],
        }
    )
    assert apply_decisions(gmail, store, 50, "retry") == 1
    assert store.apply_attempts()[-1].result is ApplyResult.NO_DELTA
    assert all(method != "users.messages.modify" for method, _ in gmail.calls)


def test_failed_apply_remains_pending(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    item = decision("m", "2", PolicyOutcome.NEEDS_ACTION)
    store.append_decision(item)
    store.append_apply(
        ApplyAttempt(item.key, "time", "run", LabelDelta(), ApplyResult.FAILED, "error")
    )
    assert store.pending_apply_decisions() == (item,)
