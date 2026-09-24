"""Short TTL cache for pure/idempotent Reflex decisions (RFC-0171)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from .types import Answer, Question

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Answer]]] = {}
DEFAULT_TTL_S = 8.0
MAX_ENTRIES = 256


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(
    *,
    provider: str,
    provider_version: str,
    decision_class: str,
    state: dict[str, Any],
    questions: tuple[Question, ...] | list[Question],
) -> str:
    q_payload = [
        {
            "id": q.id,
            "type": q.type,
            "prompt": q.prompt,
            "choices": list(q.choices),
            "score_min": q.score_min,
            "score_max": q.score_max,
        }
        for q in questions
    ]
    blob = _canonical(
        {
            "provider": provider,
            "provider_version": provider_version,
            "decision_class": decision_class,
            "state": state,
            "questions": q_payload,
        }
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(key: str) -> dict[str, Answer] | None:
    now = time.monotonic()
    with _LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        expires, answers = row
        if expires <= now:
            _CACHE.pop(key, None)
            return None
        return dict(answers)


def put(key: str, answers: dict[str, Answer], *, ttl_s: float = DEFAULT_TTL_S) -> None:
    if not answers:
        return
    expires = time.monotonic() + max(0.1, float(ttl_s))
    with _LOCK:
        if len(_CACHE) >= MAX_ENTRIES:
            # Drop oldest expiry first.
            oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])[: max(1, MAX_ENTRIES // 8)]
            for dead, _ in oldest:
                _CACHE.pop(dead, None)
        _CACHE[key] = (expires, dict(answers))


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def all_questions_pure(questions: tuple[Question, ...] | list[Question]) -> bool:
    return bool(questions) and all(q.pure for q in questions)
