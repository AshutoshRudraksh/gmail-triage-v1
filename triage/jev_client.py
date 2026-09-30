from __future__ import annotations

import json
import math
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import suppress
from email.header import decode_header, make_header
from typing import Any, Protocol, cast

from .models import ValidatedAnswers

ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
MODEL = "typesafe-ai/jev"
CATEGORIES = ("recruiter/job", "finance", "newsletter", "personal", "transactional", "other")
SCAM_LEVELS = (
    "clearly legitimate",
    "probably legitimate",
    "uncertain",
    "probably malicious",
    "highly likely malicious",
)
QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Choose the message's primary purpose.",
        "criteria": {item: item for item in CATEGORIES},
    },
    "needs_action": {
        "type": "boolean",
        "instructions": "Does the sender ask the owner for a concrete action or response?",
    },
    "is_urgent": {
        "type": "boolean",
        "instructions": (
            "Could delaying owner attention beyond today cause a deadline, "
            "loss, or material problem?"
        ),
    },
    "is_promo_noise": {
        "type": "boolean",
        "instructions": "Is this bulk promotion with no personal relevance or required action?",
    },
    "scam_risk": {
        "type": "score",
        "instructions": "Rate fraud or phishing risk.",
        "criteria": list(SCAM_LEVELS),
    },
}


class Jev(Protocol):
    def evaluate(self, state: str) -> ValidatedAnswers: ...


class JevError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _normalize(value: str | None) -> str:
    if value:
        with suppress(LookupError, UnicodeError):
            value = str(make_header(decode_header(value)))
    value = value or ""
    value = "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)
    value = re.sub(r"\s+", " ", value, flags=re.UNICODE).strip()
    return value or "(missing)"


def _truncate(value: str, capacity: int) -> str:
    if len(value) <= capacity:
        return value
    if capacity <= 3:
        return "." * capacity
    return value[: capacity - 3] + "..."


def build_state(sender: str | None, subject: str | None, snippet: str | None) -> str:
    sender_value = _truncate(_normalize(sender), 512)
    subject_value = _truncate(_normalize(subject), 1024)
    overhead = len("Sender: \nSubject: \nSnippet: ")
    snippet_capacity = 8000 - overhead - len(sender_value) - len(subject_value)
    snippet_value = _truncate(_normalize(snippet), snippet_capacity)
    state = f"Sender: {sender_value}\nSubject: {subject_value}\nSnippet: {snippet_value}"
    if len(state) > 8000:
        raise AssertionError("state exceeds 8000 code points")
    return state


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevError("invalid_response")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise JevError("invalid_response")
    return result


def validate_response(payload: Any) -> ValidatedAnswers:
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise JevError("invalid_response")
    answers = payload["answers"]
    if set(answers) != set(QUESTIONS):
        raise JevError("invalid_response")
    category = answers["category"]
    if (
        not isinstance(category, dict)
        or set(category) != {"type", "choice", "probabilities"}
        or category.get("type") != "choice"
        or category.get("choice") not in CATEGORIES
        or not isinstance(category.get("probabilities"), dict)
        or set(category["probabilities"]) != set(CATEGORIES)
    ):
        raise JevError("invalid_response")
    category_probabilities = {
        name: _probability(category["probabilities"][name]) for name in CATEGORIES
    }
    boolean_values: dict[str, float] = {}
    for name in ("needs_action", "is_urgent", "is_promo_noise"):
        answer = answers[name]
        if not isinstance(answer, dict) or set(answer) != {"type", "probability"}:
            raise JevError("invalid_response")
        if answer["type"] != "boolean":
            raise JevError("invalid_response")
        boolean_values[name] = _probability(answer["probability"])
    score = answers["scam_risk"]
    if (
        not isinstance(score, dict)
        or score.get("type") != "score"
        or set(score) != {"type", "score", "probabilities"}
        or not isinstance(score.get("probabilities"), dict)
        or set(score["probabilities"]) != {str(index) for index in range(5)}
    ):
        raise JevError("invalid_response")
    raw_score = score["score"]
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise JevError("invalid_response")
    normalized_score = float(raw_score) + 1
    if not math.isfinite(normalized_score) or not 1 <= normalized_score <= 5:
        raise JevError("invalid_response")
    score_probabilities = cast(
        tuple[float, float, float, float, float],
        tuple(_probability(score["probabilities"][str(i)]) for i in range(5)),
    )
    return ValidatedAnswers(
        category=category["choice"],
        category_probabilities=category_probabilities,
        needs_action=boolean_values["needs_action"],
        is_urgent=boolean_values["is_urgent"],
        is_promo_noise=boolean_values["is_promo_noise"],
        scam_risk=normalized_score,
        scam_risk_probabilities=score_probabilities,
    )


class JevClient:
    def __init__(
        self,
        api_key: str,
        timeout: float = 30,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ):
        if not api_key:
            raise ValueError("AI_GATEWAY_API_KEY is required")
        self._api_key = api_key
        self._timeout = timeout
        self._opener = opener

    def evaluate(self, state: str) -> ValidatedAnswers:
        body = json.dumps(
            {"model": MODEL, "state": state, "questions": QUESTIONS},
            separators=(",", ":"),
        ).encode()
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload: Mapping[str, Any] = json.loads(response.read())
        except TimeoutError as exc:
            raise JevError("timeout") from exc
        except urllib.error.HTTPError as exc:
            raise JevError("http_error") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise JevError("network_error") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise JevError("invalid_response") from exc
        return validate_response(payload)
