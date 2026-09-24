"""Jev cloud Reflex adapter — opt-in + real probe only (RFC-0171 / RFC-0116)."""

from __future__ import annotations

from ...licensing.inference import get_secret_by_provider
from ..jev_client import JevHttpError, post_systemone
from ..tier import TYPESAFE_PROVIDER, jev_calls_allowed, resolve_status
from ..types import Answer, DecideRequest
from .base import ReflexAdapter, parse_typed_answers, questions_to_wire


class JevAdapter:
    name = "jev"

    def available(self, request: DecideRequest) -> tuple[bool, str]:
        if request.privacy != "cloud_ok":
            return False, "privacy forbids cloud Jev"
        allowed, reason = jev_calls_allowed(resolve_status())
        if not allowed:
            return False, reason or "jev not connected"
        return True, ""

    def decide(self, request: DecideRequest) -> tuple[dict[str, Answer], str, float]:
        key = get_secret_by_provider(TYPESAFE_PROVIDER)
        if not key:
            raise RuntimeError("typesafe key missing")
        timeout_s = max(0.05, min(12.0, float(request.deadline_ms) / 1000.0))
        try:
            payload = post_systemone(
                api_key=key,
                state=dict(request.state),
                questions=questions_to_wire(request.questions),
                timeout=timeout_s,
            )
        except JevHttpError as exc:
            raise RuntimeError(str(exc)) from exc
        answers = parse_typed_answers(request.questions, payload.get("answers") or {})
        version = str(payload.get("model") or "jev-latest")
        # Network+inference lumped; reflex layer splits when possible.
        return answers, version, 0.0


ADAPTER: ReflexAdapter = JevAdapter()
