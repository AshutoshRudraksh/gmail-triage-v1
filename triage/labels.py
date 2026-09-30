from collections.abc import Iterable, Mapping

from .models import LabelDelta, ManagedLabelMap, PolicyOutcome
from .policy import MANAGED_LABEL_NAMES


def proposed_reconciliation(
    current_label_ids: Iterable[str],
    outcome: PolicyOutcome,
    labels: Iterable[Mapping[str, str]],
) -> LabelDelta:
    managed_by_id = {
        label["id"]: label["name"]
        for label in labels
        if label.get("name") in MANAGED_LABEL_NAMES and label.get("id")
    }
    current = {
        managed_by_id[label_id] for label_id in current_label_ids if label_id in managed_by_id
    }
    desired = set() if outcome is PolicyOutcome.REVIEW_QUEUE else {outcome.value}
    return LabelDelta(
        add=tuple(sorted(desired - current)),
        remove=tuple(sorted(current - desired)),
    )


def managed_label_map(labels: Iterable[Mapping[str, str]]) -> ManagedLabelMap | None:
    found = {
        label["name"]: label["id"] for label in labels if label.get("name") in MANAGED_LABEL_NAMES
    }
    if set(found) != set(MANAGED_LABEL_NAMES):
        return None
    return ManagedLabelMap(
        needs_action=found[PolicyOutcome.NEEDS_ACTION.value],
        promo_noise=found[PolicyOutcome.PROMO_NOISE.value],
        security_review=found[PolicyOutcome.SECURITY_REVIEW.value],
    )


def reconcile_labels(
    current_label_ids: Iterable[str],
    outcome: PolicyOutcome,
    labels: ManagedLabelMap,
) -> LabelDelta:
    by_name = labels.by_name()
    managed_ids = set(by_name.values())
    current = set(current_label_ids) & managed_ids
    desired = set() if outcome is PolicyOutcome.REVIEW_QUEUE else {by_name[outcome.value]}
    return LabelDelta(add=tuple(sorted(desired - current)), remove=tuple(sorted(current - desired)))
