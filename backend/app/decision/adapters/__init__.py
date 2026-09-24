"""Adapter protocol for Reflex providers (RFC-0171)."""

from __future__ import annotations

from typing import Any, Protocol

from ..types import DecisionResult, Question


class ReflexAdapter(Protocol):
    name: str
    version: str

    def available(self, *, privacy: str, decision_class: str) -> tuple[bool, str]:
        ...

    def decide(
        self,
        *,
        state: dict[str, Any],
        questions: list[Question],
        decision_class: str,
        deadline_ms: float,
    ) -> DecisionResult:
        ...
