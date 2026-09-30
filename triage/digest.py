import json
from collections.abc import Iterable

from .models import CompletedDecision, DigestEntry, PolicyOutcome

ORDER = {
    PolicyOutcome.SECURITY_REVIEW: 0,
    PolicyOutcome.NEEDS_ACTION: 1,
    PolicyOutcome.REVIEW_QUEUE: 2,
}


def entries_for(decisions: Iterable[CompletedDecision]) -> tuple[DigestEntry, ...]:
    entries = [
        DigestEntry(
            thread_id=item.thread_id,
            category=item.answers.category,
            outcome=item.policy.outcome,
            needs_action=item.answers.needs_action,
            is_urgent=item.answers.is_urgent,
            is_promo_noise=item.answers.is_promo_noise,
            scam_risk=item.answers.scam_risk,
            label_state=item.policy.outcome.value,
        )
        for item in decisions
        if item.policy.outcome is not PolicyOutcome.PROMO_NOISE
    ]
    return tuple(sorted(entries, key=lambda item: (ORDER[item.outcome], item.thread_id)))


def render_digest(entries: Iterable[DigestEntry]) -> str:
    grouped: dict[PolicyOutcome, list[DigestEntry]] = {outcome: [] for outcome in ORDER}
    for entry in entries:
        grouped[entry.outcome].append(entry)
    lines = ["Gmail Triage Digest"]
    for outcome in ORDER:
        lines.extend(("", outcome.value))
        for entry in grouped[outcome]:
            scores = json.dumps(
                {
                    "category": entry.category,
                    "needs_action": entry.needs_action,
                    "is_urgent": entry.is_urgent,
                    "is_promo_noise": entry.is_promo_noise,
                    "scam_risk": entry.scam_risk,
                    "label_state": entry.label_state,
                },
                sort_keys=True,
            )
            lines.append(f"- {scores} https://mail.google.com/mail/u/0/#all/{entry.thread_id}")
    return "\n".join(lines) + "\n"
