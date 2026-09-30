from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from .gmail_client import Gmail
from .jev_client import Jev, JevError, build_state
from .labels import managed_label_map, proposed_reconciliation, reconcile_labels
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
)
from .persistence import StateStore
from .policy import MANAGED_LABEL_NAMES, POLICY_VERSION, decide

CLASSIFIER_VERSION = "1"


class CheckpointError(RuntimeError):
    pass


def _http_status(exc: Exception) -> int | None:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _message_key(message_id: str, history_id: str) -> ClassificationKey:
    return ClassificationKey(message_id, history_id, CLASSIFIER_VERSION)


def _message(gmail: Gmail, message_id: str) -> Mapping[str, Any]:
    return gmail.call(
        "users.messages.get",
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject"],
    )


def _queue_message(
    store: StateStore,
    gmail: Gmail,
    message_ref: Mapping[str, Any],
    history_id: str,
    run_id: str,
    now: Callable[[], str],
    handled_keys: set[ClassificationKey],
) -> bool:
    message_id = str(message_ref["id"])
    key = _message_key(message_id, history_id)
    if key in handled_keys:
        return False
    message = message_ref if "labelIds" in message_ref else _message(gmail, message_id)
    common = {
        "key": key,
        "thread_id": str(message.get("threadId", message_ref.get("threadId", ""))),
        "timestamp": now(),
        "run_id": run_id,
    }
    if "INBOX" in message.get("labelIds", []):
        appended = store.append_decision(PendingJob(**common))
        handled_keys.add(key)
        return appended
    store.append_decision(NotInInboxRecord(**common))
    handled_keys.add(key)
    return False


def incremental_intake(
    gmail: Gmail,
    store: StateStore,
    limit: int,
    run_id: str,
    now: Callable[[], str] = utc_now,
) -> int:
    checkpoint = store.read_checkpoint()
    if checkpoint is None:
        raise CheckpointError("No checkpoint; rerun with --bootstrap")
    request_start_history_id = checkpoint.history_id
    handled_keys = store.handled_classification_keys()
    queued = 0
    page_token: str | None = None
    while True:
        arguments: dict[str, Any] = {
            "userId": "me",
            "startHistoryId": request_start_history_id,
            "historyTypes": ["messageAdded"],
        }
        if page_token:
            arguments["pageToken"] = page_token
        try:
            response = gmail.call("users.history.list", **arguments)
        except Exception as exc:
            if _http_status(exc) in {400, 404}:
                raise CheckpointError(
                    "Gmail history checkpoint expired; approve a bootstrap"
                ) from exc
            raise
        records = sorted(response.get("history", []), key=lambda item: int(item["id"]))
        for record in records:
            history_id = str(record["id"])
            if int(history_id) <= int(checkpoint.history_id):
                continue
            seen: set[str] = set()
            queued_in_record = 0
            for added in record.get("messagesAdded", []):
                message_ref = added["message"]
                message_id = str(message_ref["id"])
                if message_id in seen:
                    continue
                seen.add(message_id)
                if _queue_message(store, gmail, message_ref, history_id, run_id, now, handled_keys):
                    queued_in_record += 1
            store.write_checkpoint(Checkpoint(history_id))
            checkpoint = Checkpoint(history_id)
            queued += queued_in_record
            if queued >= limit:
                return queued
        page_token = response.get("nextPageToken")
        if not page_token:
            return queued


def bootstrap_intake(
    gmail: Gmail,
    store: StateStore,
    run_id: str,
    now: Callable[[], str] = utc_now,
) -> int:
    profile = gmail.call("users.getProfile", userId="me")
    high_water = str(profile["historyId"])
    references: dict[str, Mapping[str, Any]] = {}
    page_token: str | None = None
    while True:
        arguments: dict[str, Any] = {"userId": "me", "q": "in:inbox newer_than:1d"}
        if page_token:
            arguments["pageToken"] = page_token
        response = gmail.call("users.messages.list", **arguments)
        for item in response.get("messages", []):
            references.setdefault(str(item["id"]), item)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    messages = [_message(gmail, message_id) for message_id in references]
    handled_keys = store.handled_classification_keys()
    queued = 0
    for message in messages:
        if _queue_message(store, gmail, message, high_water, run_id, now, handled_keys):
            queued += 1
    store.write_checkpoint(Checkpoint(high_water))
    return queued


def _headers(message: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in message.get("payload", {}).get("headers", []):
        name = str(item.get("name", "")).lower()
        if name in {"from", "subject"} and name not in result:
            result[name] = str(item.get("value", ""))
    return result


def classify_pending(
    gmail: Gmail,
    jev: Jev,
    store: StateStore,
    limit: int,
    run_id: str,
    gmail_labels: tuple[Mapping[str, str], ...] = (),
    now: Callable[[], str] = utc_now,
) -> tuple[CompletedDecision, ...]:
    completed: list[CompletedDecision] = []
    for job in store.pending_jobs()[:limit]:
        state = ""
        try:
            message = _message(gmail, job.key.message_id)
            headers = _headers(message)
            state = build_state(headers.get("from"), headers.get("subject"), message.get("snippet"))
            state_hash = hashlib.sha256(state.encode()).hexdigest()
            answers = jev.evaluate(state)
        except JevError as exc:
            store.append_decision(
                ClassificationFailure(
                    key=job.key,
                    thread_id=job.thread_id,
                    timestamp=now(),
                    run_id=run_id,
                    state_sha256=hashlib.sha256(state.encode()).hexdigest(),
                    error_code=exc.code,
                )
            )
            continue
        except Exception:
            store.append_decision(
                ClassificationFailure(
                    key=job.key,
                    thread_id=job.thread_id,
                    timestamp=now(),
                    run_id=run_id,
                    state_sha256=hashlib.sha256(state.encode()).hexdigest(),
                    error_code="gmail_get_error",
                )
            )
            continue
        policy = decide(answers)
        proposed = proposed_reconciliation(
            message.get("labelIds", ()),
            policy.outcome,
            gmail_labels,
        )
        decision = CompletedDecision(
            key=job.key,
            thread_id=str(message.get("threadId", job.thread_id)),
            timestamp=now(),
            run_id=run_id,
            state_sha256=state_hash,
            answers=answers,
            policy_version=POLICY_VERSION,
            policy=policy,
            proposed_delta=proposed,
        )
        if store.append_decision(decision):
            completed.append(decision)
    return tuple(completed)


def _selected_decisions(
    decisions: tuple[CompletedDecision, ...],
) -> tuple[tuple[CompletedDecision, ...], tuple[CompletedDecision, ...]]:
    grouped: dict[str, list[CompletedDecision]] = {}
    for decision in decisions:
        grouped.setdefault(decision.key.message_id, []).append(decision)
    selected: list[CompletedDecision] = []
    superseded: list[CompletedDecision] = []
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: int(item.key.message_added_history_id))
        selected.append(ordered[-1])
        superseded.extend(ordered[:-1])
    return tuple(selected), tuple(superseded)


def apply_decisions(
    gmail: Gmail,
    store: StateStore,
    limit: int,
    run_id: str,
    now: Callable[[], str] = utc_now,
) -> int:
    selected, superseded = _selected_decisions(store.pending_apply_decisions())
    for decision in superseded:
        store.append_apply(
            ApplyAttempt(
                decision.key,
                now(),
                run_id,
                LabelDelta(),
                ApplyResult.SUPERSEDED,
            )
        )
    selected = selected[:limit]
    try:
        response = gmail.call("users.labels.list", userId="me")
        labels = list(response.get("labels", []))
        names = {item.get("name") for item in labels}
        for name in MANAGED_LABEL_NAMES:
            if name not in names:
                labels.append(
                    gmail.call(
                        "users.labels.create",
                        userId="me",
                        body={
                            "name": name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                )
        label_map = managed_label_map(labels)
        if label_map is None:
            raise RuntimeError("managed label creation did not return IDs")
    except Exception:
        for decision in selected:
            store.append_apply(
                ApplyAttempt(
                    decision.key,
                    now(),
                    run_id,
                    LabelDelta(),
                    ApplyResult.FAILED,
                    "gmail_labels_error",
                )
            )
        return 0
    successes = 0
    for decision in selected:
        delta = LabelDelta()
        try:
            message = gmail.call(
                "users.messages.get",
                userId="me",
                id=decision.key.message_id,
                format="minimal",
            )
            delta = reconcile_labels(
                message.get("labelIds", []), decision.policy.outcome, label_map
            )
            if delta.add or delta.remove:
                gmail.call(
                    "users.messages.modify",
                    userId="me",
                    id=decision.key.message_id,
                    body={
                        "addLabelIds": list(delta.add),
                        "removeLabelIds": list(delta.remove),
                    },
                )
                result = ApplyResult.APPLIED
            else:
                result = ApplyResult.NO_DELTA
            store.append_apply(ApplyAttempt(decision.key, now(), run_id, delta, result))
            successes += 1
        except Exception:
            store.append_apply(
                ApplyAttempt(
                    decision.key,
                    now(),
                    run_id,
                    delta,
                    ApplyResult.FAILED,
                    "gmail_modify_error" if delta.add or delta.remove else "gmail_get_error",
                )
            )
    return successes
