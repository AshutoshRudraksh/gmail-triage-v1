from __future__ import annotations

import fcntl
import json
import math
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    ApplyAttempt,
    ApplyResult,
    Checkpoint,
    ClassificationFailure,
    ClassificationKey,
    CompletedDecision,
    LabelDelta,
    NotInInboxRecord,
    PendingJob,
    PolicyDecision,
    PolicyOutcome,
    ValidatedAnswers,
)

DecisionEvent = PendingJob | CompletedDecision | NotInInboxRecord | ClassificationFailure
CATEGORIES = {"recruiter/job", "finance", "newsletter", "personal", "transactional", "other"}


class PersistenceError(RuntimeError):
    pass


def _exact(data: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != keys:
        raise PersistenceError("invalid persisted event")
    return data


def _key_to_dict(key: ClassificationKey) -> dict[str, str]:
    return {
        "message_id": key.message_id,
        "message_added_history_id": key.message_added_history_id,
        "classifier_version": key.classifier_version,
    }


def _key_from_dict(value: Any) -> ClassificationKey:
    data = _exact(value, {"message_id", "message_added_history_id", "classifier_version"})
    if not all(isinstance(item, str) and item for item in data.values()):
        raise PersistenceError("invalid classification key")
    return ClassificationKey(**data)


def _delta_to_dict(delta: LabelDelta) -> dict[str, list[str]]:
    return {"add": list(delta.add), "remove": list(delta.remove)}


def _delta_from_dict(value: Any) -> LabelDelta:
    data = _exact(value, {"add", "remove"})
    if not all(
        isinstance(values, list) and all(isinstance(item, str) for item in values)
        for values in data.values()
    ):
        raise PersistenceError("invalid label delta")
    return LabelDelta(tuple(data["add"]), tuple(data["remove"]))


def _probability(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def encode_decision_event(event: DecisionEvent) -> dict[str, Any]:
    common = {
        "event": event.event,
        "key": _key_to_dict(event.key),
        "thread_id": event.thread_id,
        "timestamp": event.timestamp,
        "run_id": event.run_id,
    }
    if isinstance(event, CompletedDecision):
        common.update(
            {
                "state_sha256": event.state_sha256,
                "answers": {
                    "category": event.answers.category,
                    "category_probabilities": dict(event.answers.category_probabilities),
                    "needs_action": event.answers.needs_action,
                    "is_urgent": event.answers.is_urgent,
                    "is_promo_noise": event.answers.is_promo_noise,
                    "scam_risk": event.answers.scam_risk,
                    "scam_risk_probabilities": list(event.answers.scam_risk_probabilities),
                },
                "policy_version": event.policy_version,
                "policy": {
                    "outcome": event.policy.outcome.value,
                    "managed_labels": list(event.policy.managed_labels),
                    "digest_section": event.policy.digest_section,
                },
                "proposed_delta": _delta_to_dict(event.proposed_delta),
            }
        )
    elif isinstance(event, ClassificationFailure):
        common.update({"state_sha256": event.state_sha256, "error_code": event.error_code})
    return common


def decode_decision_event(value: Any) -> DecisionEvent:
    if not isinstance(value, dict) or not isinstance(value.get("event"), str):
        raise PersistenceError("invalid persisted event")
    event_type = value["event"]
    base = {"event", "key", "thread_id", "timestamp", "run_id"}
    if event_type in {"pending", "not_in_inbox"}:
        data = _exact(value, base)
    elif event_type == "failure":
        data = _exact(value, base | {"state_sha256", "error_code"})
    elif event_type == "completed":
        data = _exact(
            value,
            base | {"state_sha256", "answers", "policy_version", "policy", "proposed_delta"},
        )
    else:
        raise PersistenceError("unknown decision event")
    for name in ("thread_id", "timestamp", "run_id"):
        if not isinstance(data[name], str):
            raise PersistenceError("invalid persisted event")
    common = {
        "key": _key_from_dict(data["key"]),
        "thread_id": data["thread_id"],
        "timestamp": data["timestamp"],
        "run_id": data["run_id"],
    }
    if event_type == "pending":
        return PendingJob(**common)
    if event_type == "not_in_inbox":
        return NotInInboxRecord(**common)
    if event_type == "failure":
        if not _valid_hash(data["state_sha256"]) or not isinstance(data["error_code"], str):
            raise PersistenceError("invalid failure")
        return ClassificationFailure(
            **common,
            state_sha256=data["state_sha256"],
            error_code=data["error_code"],
        )
    answers = _exact(
        data["answers"],
        {
            "category",
            "category_probabilities",
            "needs_action",
            "is_urgent",
            "is_promo_noise",
            "scam_risk",
            "scam_risk_probabilities",
        },
    )
    policy = _exact(data["policy"], {"outcome", "managed_labels", "digest_section"})
    category_probabilities = answers["category_probabilities"]
    score_probabilities = answers["scam_risk_probabilities"]
    scam_risk = answers["scam_risk"]
    if (
        not isinstance(answers["category"], str)
        or answers["category"] not in CATEGORIES
        or not isinstance(category_probabilities, dict)
        or set(category_probabilities) != CATEGORIES
        or not all(_probability(value) for value in category_probabilities.values())
        or not all(
            _probability(answers[name]) for name in ("needs_action", "is_urgent", "is_promo_noise")
        )
        or isinstance(scam_risk, bool)
        or not isinstance(scam_risk, (int, float))
        or not math.isfinite(scam_risk)
        or not 1 <= scam_risk <= 5
        or not isinstance(score_probabilities, list)
        or len(score_probabilities) != 5
        or not all(_probability(value) for value in score_probabilities)
        or not _valid_hash(data["state_sha256"])
        or not isinstance(data["policy_version"], str)
        or not isinstance(policy["managed_labels"], list)
        or not all(isinstance(value, str) for value in policy["managed_labels"])
        or not (policy["digest_section"] is None or isinstance(policy["digest_section"], str))
    ):
        raise PersistenceError("invalid completed decision")
    try:
        validated = ValidatedAnswers(
            category=answers["category"],
            category_probabilities=answers["category_probabilities"],
            needs_action=answers["needs_action"],
            is_urgent=answers["is_urgent"],
            is_promo_noise=answers["is_promo_noise"],
            scam_risk=answers["scam_risk"],
            scam_risk_probabilities=tuple(answers["scam_risk_probabilities"]),
        )
        policy_decision = PolicyDecision(
            outcome=PolicyOutcome(policy["outcome"]),
            managed_labels=tuple(policy["managed_labels"]),
            digest_section=policy["digest_section"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError("invalid completed decision") from exc
    return CompletedDecision(
        **common,
        state_sha256=data["state_sha256"],
        answers=validated,
        policy_version=data["policy_version"],
        policy=policy_decision,
        proposed_delta=_delta_from_dict(data["proposed_delta"]),
    )


def encode_apply_attempt(attempt: ApplyAttempt) -> dict[str, Any]:
    return {
        "event": attempt.event,
        "key": _key_to_dict(attempt.key),
        "timestamp": attempt.timestamp,
        "run_id": attempt.run_id,
        "delta": _delta_to_dict(attempt.delta),
        "result": attempt.result.value,
        "error_code": attempt.error_code,
    }


def decode_apply_attempt(value: Any) -> ApplyAttempt:
    data = _exact(value, {"event", "key", "timestamp", "run_id", "delta", "result", "error_code"})
    if data["event"] != "apply_attempt":
        raise PersistenceError("invalid apply event")
    try:
        result = ApplyResult(data["result"])
    except ValueError as exc:
        raise PersistenceError("invalid apply result") from exc
    if result is ApplyResult.FAILED and not isinstance(data["error_code"], str):
        raise PersistenceError("failed attempt requires error code")
    if result is not ApplyResult.FAILED and data["error_code"] is not None:
        raise PersistenceError("successful attempt cannot have error code")
    return ApplyAttempt(
        key=_key_from_dict(data["key"]),
        timestamp=data["timestamp"],
        run_id=data["run_id"],
        delta=_delta_from_dict(data["delta"]),
        result=result,
        error_code=data["error_code"],
    )


def append_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_jsonl(path: Path) -> Iterator[Any]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise PersistenceError(f"invalid JSON line {line_number}") from exc


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.decisions_path = directory / "decisions.jsonl"
        self.apply_path = directory / "apply_attempts.jsonl"
        self.checkpoint_path = directory / "checkpoint.json"

    def decision_events(self) -> tuple[DecisionEvent, ...]:
        return tuple(decode_decision_event(item) for item in read_jsonl(self.decisions_path))

    def apply_attempts(self) -> tuple[ApplyAttempt, ...]:
        return tuple(decode_apply_attempt(item) for item in read_jsonl(self.apply_path))

    def append_decision(self, event: DecisionEvent) -> bool:
        if not isinstance(event, ClassificationFailure):
            for old in self.decision_events():
                if old.event == event.event and old.key == event.key:
                    return False
        append_json(self.decisions_path, encode_decision_event(event))
        return True

    def append_apply(self, attempt: ApplyAttempt) -> None:
        append_json(self.apply_path, encode_apply_attempt(attempt))

    def handled_classification_keys(self) -> set[ClassificationKey]:
        return {
            event.key
            for event in self.decision_events()
            if isinstance(event, (PendingJob, CompletedDecision, NotInInboxRecord))
        }

    def pending_jobs(self) -> tuple[PendingJob, ...]:
        events = self.decision_events()
        completed = {event.key for event in events if isinstance(event, CompletedDecision)}
        jobs = {
            event.key: event
            for event in events
            if isinstance(event, PendingJob) and event.key not in completed
        }
        return tuple(
            sorted(
                jobs.values(),
                key=lambda item: (
                    int(item.key.message_added_history_id),
                    item.key.message_id,
                ),
            )
        )

    def completed_decisions(self) -> tuple[CompletedDecision, ...]:
        unique: dict[ClassificationKey, CompletedDecision] = {}
        for event in self.decision_events():
            if isinstance(event, CompletedDecision):
                unique.setdefault(event.key, event)
        return tuple(unique.values())

    def pending_apply_decisions(self) -> tuple[CompletedDecision, ...]:
        terminal = {
            attempt.key
            for attempt in self.apply_attempts()
            if attempt.result in {ApplyResult.APPLIED, ApplyResult.NO_DELTA, ApplyResult.SUPERSEDED}
        }
        return tuple(item for item in self.completed_decisions() if item.key not in terminal)

    def read_checkpoint(self) -> Checkpoint | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            data = _exact(json.loads(self.checkpoint_path.read_text()), {"history_id"})
        except (json.JSONDecodeError, OSError) as exc:
            raise PersistenceError("invalid checkpoint") from exc
        if not isinstance(data["history_id"], str) or not data["history_id"].isdigit():
            raise PersistenceError("invalid checkpoint")
        return Checkpoint(data["history_id"])

    def write_checkpoint(self, checkpoint: Checkpoint) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.directory, prefix=".checkpoint-", text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"history_id": checkpoint.history_id}, stream, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.checkpoint_path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @contextmanager
    def lock(self, name: str) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{name}.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise PersistenceError(f"{name} is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
