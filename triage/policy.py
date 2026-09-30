from .models import LabelDelta, PolicyDecision, PolicyOutcome, ValidatedAnswers

POLICY_VERSION = "1"
MANAGED_LABEL_NAMES = (
    PolicyOutcome.NEEDS_ACTION.value,
    PolicyOutcome.PROMO_NOISE.value,
    PolicyOutcome.SECURITY_REVIEW.value,
)


def decide(answers: ValidatedAnswers) -> PolicyDecision:
    if answers.scam_risk >= 4:
        outcome = PolicyOutcome.SECURITY_REVIEW
    elif answers.needs_action >= 0.85 or answers.is_urgent >= 0.85:
        outcome = PolicyOutcome.NEEDS_ACTION
    elif answers.is_promo_noise >= 0.90:
        outcome = PolicyOutcome.PROMO_NOISE
    else:
        outcome = PolicyOutcome.REVIEW_QUEUE
    label = () if outcome is PolicyOutcome.REVIEW_QUEUE else (outcome.value,)
    section = None if outcome is PolicyOutcome.PROMO_NOISE else outcome.value
    return PolicyDecision(outcome, label, section)


def proposed_delta(decision: PolicyDecision) -> LabelDelta:
    selected = set(decision.managed_labels)
    return LabelDelta(
        add=tuple(sorted(selected)),
        remove=tuple(sorted(set(MANAGED_LABEL_NAMES) - selected)),
    )
