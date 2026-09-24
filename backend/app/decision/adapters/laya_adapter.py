"""Local Laya Reflex adapter (RFC-0171)."""

from __future__ import annotations

from ..laya import LayaError, infer, ready, status
from ..types import Answer, DecideRequest, PrivacyMode
from .base import ReflexAdapter, parse_typed_answers, questions_to_wire


class LayaAdapter:
    name = "laya"

    def available(self, request: DecideRequest) -> tuple[bool, str]:
        if request.privacy == "deny_cloud":
            # Local-only is fine for Laya.
            pass
        snap = status()
        if not snap.get("installed"):
            return False, "laya not installed"
        if not snap.get("enabled"):
            return False, "laya not enabled"
        if not snap.get("warm"):
            return False, "laya not warm"
        if not snap.get("loopback_only"):
            return False, "laya must be loopback-only"
        if not ready():
            return False, "laya not ready"
        return True, ""

    def decide(self, request: DecideRequest) -> tuple[dict[str, Answer], str, float]:
        try:
            payload = infer(request.state, questions_to_wire(request.questions))
        except LayaError as exc:
            raise RuntimeError(str(exc)) from exc
        answers = parse_typed_answers(request.questions, payload.get("answers") or {})
        version = str(payload.get("model") or status().get("version") or "laya-local")
        inference_ms = float(payload.get("inference_ms") or 0.0)
        return answers, version, inference_ms


ADAPTER: ReflexAdapter = LayaAdapter()
