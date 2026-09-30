from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from triage.jev_client import CATEGORIES
from triage.models import ValidatedAnswers


def answers(**changes: Any) -> ValidatedAnswers:
    values: dict[str, Any] = {
        "category": "other",
        "category_probabilities": {name: (1.0 if name == "other" else 0.0) for name in CATEGORIES},
        "needs_action": 0.1,
        "is_urgent": 0.1,
        "is_promo_noise": 0.1,
        "scam_risk": 1.0,
        "scam_risk_probabilities": (1.0, 0.0, 0.0, 0.0, 0.0),
    }
    values.update(changes)
    return ValidatedAnswers(**values)


class FakeGmail:
    def __init__(self, responses: Mapping[str, list[Any]] | None = None):
        self.responses = {method: deque(values) for method, values in (responses or {}).items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append((method, kwargs))
        queue = self.responses.get(method)
        if not queue:
            return {}
        value = queue.popleft()
        if isinstance(value, Exception):
            raise value
        return value


class FakeJev:
    def __init__(self, answers: ValidatedAnswers | Exception):
        self.answers = answers
        self.states: list[str] = []

    def evaluate(self, state: str) -> ValidatedAnswers:
        self.states.append(state)
        if isinstance(self.answers, Exception):
            raise self.answers
        return self.answers


class FakeRequest:
    def __init__(self, result: Mapping[str, Any]):
        self.result = result

    def execute(self) -> Mapping[str, Any]:
        return self.result


class FakeResource:
    def __init__(self):
        self.invocations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def _request(self, name: str, kwargs: dict[str, Any]) -> FakeRequest:
        self.invocations[name].append(kwargs)
        return FakeRequest({})

    def getProfile(self, **kwargs: Any) -> FakeRequest:
        return self._request("getProfile", kwargs)

    def list(self, **kwargs: Any) -> FakeRequest:
        return self._request("list", kwargs)

    def get(self, **kwargs: Any) -> FakeRequest:
        return self._request("get", kwargs)

    def create(self, **kwargs: Any) -> FakeRequest:
        return self._request("create", kwargs)

    def modify(self, **kwargs: Any) -> FakeRequest:
        return self._request("modify", kwargs)

    def history(self) -> FakeResource:
        return self

    def labels(self) -> FakeResource:
        return self

    def messages(self) -> FakeResource:
        return self


class FakeService:
    def __init__(self):
        self.resource = FakeResource()

    def users(self) -> FakeResource:
        return self.resource
