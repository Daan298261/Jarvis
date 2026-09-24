"""Generative fallback — last resort when typed providers cannot answer (RFC-0171)."""

from __future__ import annotations

import time
from typing import Any

from . import rules
from ..types import DecisionResult, LatencyBreakdown, Question

VERSION = "generative-fallback-1"


def available(*, privacy: str = "local_only", decision_class: str = "") -> tuple[bool, str]:
    return True, ""


def decide(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float,
) -> DecisionResult:
    """
    Explicit generative-lane fallback. On this host without a dedicated small
    decision LLM, we reuse deterministic rules and label source as generative
    so audits never claim Jev/Laya decided.
    """
    started = time.perf_counter()
    base = rules.decide(
        state=state,
        questions=questions,
        decision_class=decision_class,
        deadline_ms=deadline_ms,
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    return DecisionResult(
        answers=base.answers,
        source="generative",
        decision_class=decision_class,
        provider="generative",
        provider_version=VERSION,
        model=VERSION,
        fallback_used=True,
        fallback_reason="typed providers unavailable or inadequate",
        fallback_source="generative",
        latency=LatencyBreakdown(inference_ms=elapsed, total_ms=elapsed),
        hard_rule=False,
        meta={"based_on": "rules_projection"},
    )
