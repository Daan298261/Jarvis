"""Generative fallback adapter — last resort, never attributed as Jev/Laya (RFC-0171)."""

from __future__ import annotations

from typing import Any, Callable

from ..types import Answer, DecideRequest, Question
from .base import ReflexAdapter
from .rules import RulesAdapter

GenerativeFn = Callable[[DecideRequest], dict[str, Answer]]
_GENERATIVE_FN: GenerativeFn | None = None


def set_generative_fn(fn: GenerativeFn | None) -> None:
    global _GENERATIVE_FN
    _GENERATIVE_FN = fn


def reset_generative_fn() -> None:
    set_generative_fn(None)


class GenerativeFallbackAdapter:
    name = "generative_fallback"

    def available(self, request: DecideRequest) -> tuple[bool, str]:
        return True, ""

    def decide(self, request: DecideRequest) -> tuple[dict[str, Answer], str, float]:
        if _GENERATIVE_FN is not None:
            answers = _GENERATIVE_FN(request)
            return answers, "generative-fixture", 1.0
        # Production fallback: re-run deterministic rules with explicit generative label.
        # Never invent cloud attribution. Incomplete answers are allowed; decide() audits.
        rules = RulesAdapter()
        answers, _version, _ms = rules.decide(request)
        # Fill remaining with safe defaults so the turn never strands.
        for question in request.questions:
            if question.id in answers:
                continue
            answers[question.id] = _safe_default(question, request)
        return answers, "generative-local-heuristic", 1.0


def _safe_default(question: Question, request: DecideRequest) -> Answer:
    if question.type == "choice":
        choices = list(question.choices)
        pick = choices[0] if choices else ""
        if "none" in choices:
            pick = "none"
        return Answer(question.id, "choice", pick, 0.2)
    if question.type == "score":
        local = request.state.get("local_score")
        try:
            value = float(local) if local is not None else 0.5
        except (TypeError, ValueError):
            value = 0.5
        return Answer(question.id, "score", value, 0.2)
    return Answer(question.id, "boolean", 0.0, 0.2)


ADAPTER: ReflexAdapter = GenerativeFallbackAdapter()
