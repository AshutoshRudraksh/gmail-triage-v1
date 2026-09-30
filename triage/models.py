from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class PolicyOutcome(StrEnum):
    SECURITY_REVIEW = "Triage/SecurityReview"
    NEEDS_ACTION = "Triage/NeedsAction"
    PROMO_NOISE = "Triage/PromoNoise"
    REVIEW_QUEUE = "ReviewQueue"


class ApplyResult(StrEnum):
    APPLIED = "applied"
    NO_DELTA = "no_delta"
    SUPERSEDED = "superseded"
    FAILED = "failed"


@dataclass(frozen=True, order=True)
class ClassificationKey:
    message_id: str
    message_added_history_id: str
    classifier_version: str


@dataclass(frozen=True)
class PendingJob:
    key: ClassificationKey
    thread_id: str
    timestamp: str
    run_id: str
    event: str = field(default="pending", init=False)


@dataclass(frozen=True)
class ValidatedAnswers:
    category: str
    category_probabilities: Mapping[str, float]
    needs_action: float
    is_urgent: float
    is_promo_noise: float
    scam_risk: float
    scam_risk_probabilities: tuple[float, float, float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "category_probabilities", MappingProxyType(dict(self.category_probabilities))
        )


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    managed_labels: tuple[str, ...]
    digest_section: str | None


@dataclass(frozen=True)
class CompletedDecision:
    key: ClassificationKey
    thread_id: str
    timestamp: str
    run_id: str
    state_sha256: str
    answers: ValidatedAnswers
    policy_version: str
    policy: PolicyDecision
    proposed_delta: LabelDelta
    event: str = field(default="completed", init=False)


@dataclass(frozen=True)
class NotInInboxRecord:
    key: ClassificationKey
    thread_id: str
    timestamp: str
    run_id: str
    event: str = field(default="not_in_inbox", init=False)


@dataclass(frozen=True)
class ClassificationFailure:
    key: ClassificationKey
    thread_id: str
    timestamp: str
    run_id: str
    state_sha256: str
    error_code: str
    event: str = field(default="failure", init=False)


@dataclass(frozen=True)
class Checkpoint:
    history_id: str


@dataclass(frozen=True)
class LabelDelta:
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplyAttempt:
    key: ClassificationKey
    timestamp: str
    run_id: str
    delta: LabelDelta
    result: ApplyResult
    error_code: str | None = None
    event: str = field(default="apply_attempt", init=False)


@dataclass(frozen=True)
class ManagedLabelMap:
    needs_action: str
    promo_noise: str
    security_review: str

    def by_name(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                PolicyOutcome.NEEDS_ACTION.value: self.needs_action,
                PolicyOutcome.PROMO_NOISE.value: self.promo_noise,
                PolicyOutcome.SECURITY_REVIEW.value: self.security_review,
            }
        )


@dataclass(frozen=True)
class DigestEntry:
    thread_id: str
    category: str
    outcome: PolicyOutcome
    needs_action: float
    is_urgent: float
    is_promo_noise: float
    scam_risk: float
    label_state: str
