"""Reflex adapter protocol + shared answer parsing (RFC-0171)."""

from __future__ import annotations

from typing import Any, Protocol

from ..jev_client import parse_answer
from ..types import Answer, DecideRequest, Question, QuestionType


class ReflexAdapter(Protocol):
    name: str

    def available(self, request: DecideRequest) -> tuple[bool, str]:
        ...

    def decide(self, request: DecideRequest) -> tuple[dict[str, Answer], str, float]:
        """Return answers, provider_version, inference_ms."""
        ...


def questions_to_wire(questions: tuple[Question, ...] | list[Question]) -> dict[str, Any]:
    return {q.id: q.to_wire() for q in questions}


def parse_typed_answers(
    questions: tuple[Question, ...] | list[Question],
    raw_answers: dict[str, Any],
) -> dict[str, Answer]:
    parsed: dict[str, Answer] = {}
    for question in questions:
        raw = raw_answers.get(question.id)
        item = parse_answer(question.id, raw)
        if item is None:
            # Accept boolean alias payloads.
            if isinstance(raw, dict) and question.type == "boolean" and "boolean" in raw:
                try:
                    value = float(raw.get("boolean"))
                except (TypeError, ValueError):
                    continue
                conf = raw.get("confidence")
                try:
                    confidence = float(conf) if conf is not None else None
                except (TypeError, ValueError):
                    confidence = None
                parsed[question.id] = Answer(question.id, "boolean", value, confidence)
            continue
        qtype: QuestionType
        if item.primitive == "choice":
            qtype = "choice"
            value = item.value
            if question.choices and value not in question.choices:
                continue
        elif item.primitive == "score":
            qtype = "score"
            value = float(item.value)
            value = max(question.score_min, min(question.score_max, value))
        else:
            qtype = "boolean"
            value = float(item.value)
            value = max(0.0, min(1.0, value))
        parsed[question.id] = Answer(question.id, qtype, value, item.confidence)
    return parsed
