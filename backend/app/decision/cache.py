"""Short-TTL cache for pure/idempotent Reflex decisions (RFC-0171)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from .types import Answer, DecisionResult, LatencyBreakdown, Question, compact_state

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, DecisionResult]] = {}
DEFAULT_TTL_S = 8.0
MAX_ENTRIES = 256


def _stable_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_key(
    *,
    provider: str,
    provider_version: str,
    decision_class: str,
    state: dict[str, Any],
    questions: list[Question],
) -> str:
    qmap = [
        {
            "id": q.id,
            "type": q.type,
            "prompt": q.prompt,
            "choices": list(q.choices),
            "min": q.min_score,
            "max": q.max_score,
        }
        for q in questions
    ]
    return _stable_hash(
        {
            "provider": provider,
            "provider_version": provider_version,
            "decision_class": decision_class,
            "state": compact_state(state),
            "questions": qmap,
        }
    )


def get(key: str) -> DecisionResult | None:
    now = time.monotonic()
    with _LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        expires, result = row
        if expires <= now:
            _CACHE.pop(key, None)
            return None
        # Return a shallow copy so callers cannot mutate the cache entry.
        return DecisionResult(
            answers=dict(result.answers),
            source="cache",
            decision_class=result.decision_class,
            provider=result.provider,
            provider_version=result.provider_version,
            model=result.model,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
            fallback_source=result.fallback_source,
            cached=True,
            latency=LatencyBreakdown(total_ms=0.0, inference_ms=0.0),
            hard_rule=result.hard_rule,
            request_id=result.request_id,
            fixture=result.fixture,
            meta={**result.meta, "cache_hit": True, "cache_of": result.source},
        )


def put(key: str, result: DecisionResult, *, ttl_s: float = DEFAULT_TTL_S) -> None:
    if result.fallback_used and result.source == "deadline_fallback":
        return
    if not result.answers:
        return
    # Only cache pure providers (not generative open-ended).
    if result.provider == "generative" and not result.hard_rule:
        return
    expires = time.monotonic() + max(0.5, float(ttl_s))
    with _LOCK:
        if len(_CACHE) >= MAX_ENTRIES:
            # Drop expired first, then oldest insertion order.
            now = time.monotonic()
            stale = [k for k, (exp, _) in _CACHE.items() if exp <= now]
            for k in stale:
                _CACHE.pop(k, None)
            while len(_CACHE) >= MAX_ENTRIES and _CACHE:
                _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (expires, result)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def answers_from_dict(raw: dict[str, Any]) -> dict[str, Answer]:
    out: dict[str, Answer] = {}
    for qid, payload in (raw or {}).items():
        if not isinstance(payload, dict):
            continue
        qtype = str(payload.get("type") or "choice")
        value = payload.get("value")
        if value is None:
            value = payload.get(qtype) if qtype != "boolean" else payload.get("boolean")
        if value is None and qtype in {"boolean", "noul"}:
            value = payload.get("noul")
        conf = payload.get("confidence")
        try:
            confidence = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            confidence = None
        out[str(qid)] = Answer(
            question_id=str(qid),
            type=qtype,  # type: ignore[arg-type]
            value=value,
            confidence=confidence,
        )
    return out
