"""Jev cloud Reflex adapter — opt-in + real probe required (RFC-0171 / RFC-0116)."""

from __future__ import annotations

import time
from typing import Any

from ..jev_client import JevHttpError, parse_answer, post_systemone
from ..tier import jev_calls_allowed, resolve_status
from ..types import Answer, DecisionResult, LatencyBreakdown, Question, questions_to_provider_map
from ...licensing.inference import get_secret_by_provider

VERSION = "jev-latest"
TYPESAFE_PROVIDER = "typesafe"


def available(*, privacy: str = "local_only", decision_class: str = "") -> tuple[bool, str]:
    if privacy in {"local_only", "require_local"}:
        return False, "Jev requires allow_cloud privacy"
    status = resolve_status()
    ok, reason = jev_calls_allowed(status)
    if not ok:
        return False, reason
    return True, ""


def decide(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float,
) -> DecisionResult:
    ok, reason = available(privacy="allow_cloud", decision_class=decision_class)
    if not ok:
        raise RuntimeError(reason or "Jev unavailable")
    api_key = get_secret_by_provider(TYPESAFE_PROVIDER)
    if not api_key:
        raise RuntimeError("TypeSafe API key is missing")
    timeout_s = max(0.05, float(deadline_ms) / 1000.0)
    started = time.perf_counter()
    try:
        result = post_systemone(
            api_key=api_key,
            state=state,
            questions=questions_to_provider_map(questions),
            timeout=timeout_s,
        )
    except JevHttpError as exc:
        raise RuntimeError(str(exc)) from exc
    elapsed = (time.perf_counter() - started) * 1000.0
    if elapsed > deadline_ms:
        raise TimeoutError(f"Jev exceeded deadline ({elapsed:.1f}ms > {deadline_ms}ms)")
    raw_answers = result.get("answers") or {}
    answers: dict[str, Answer] = {}
    for question in questions:
        parsed = parse_answer(question.id, raw_answers.get(question.id))
        if parsed is None:
            continue
        qtype = question.type
        value: Any = parsed.value
        if qtype == "boolean":
            value = bool(float(parsed.value) >= 0.5)
        answers[question.id] = Answer(
            question_id=question.id,
            type=qtype,
            value=value,
            confidence=parsed.confidence,
        )
    if len(answers) != len(questions):
        missing = [q.id for q in questions if q.id not in answers]
        raise RuntimeError(f"Jev missing typed answers for: {', '.join(missing)}")
    return DecisionResult(
        answers=answers,
        source="jev",
        decision_class=decision_class,
        provider="jev",
        provider_version=str(result.get("model") or VERSION),
        model=str(result.get("model") or VERSION),
        latency=LatencyBreakdown(
            network_ms=elapsed,
            inference_ms=elapsed,
            total_ms=elapsed,
        ),
        fixture=bool(result.get("fixture")),
    )
