"""Laya local Reflex adapter (RFC-0171)."""

from __future__ import annotations

from typing import Any

from ..laya import runtime as laya_runtime
from ..types import DecisionResult, LatencyBreakdown, Question

VERSION = "laya-managed"


def available(*, privacy: str = "local_only", decision_class: str = "") -> tuple[bool, str]:
    if privacy not in {"local_only", "require_local", "allow_cloud"}:
        return False, f"unsupported privacy {privacy}"
    if not laya_runtime.is_ready():
        return False, "Laya not installed/warm"
    return True, ""


def decide(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float,
) -> DecisionResult:
    answers, elapsed, fixture = laya_runtime.decide_local(
        state=state,
        questions=questions,
        decision_class=decision_class,
        deadline_ms=deadline_ms,
    )
    status = laya_runtime.status()
    return DecisionResult(
        answers=answers,
        source="laya",
        decision_class=decision_class,
        provider="laya",
        provider_version=str(status.get("version") or VERSION),
        model=str(status.get("version") or VERSION),
        latency=LatencyBreakdown(inference_ms=elapsed, total_ms=elapsed),
        fixture=bool(fixture),
    )
