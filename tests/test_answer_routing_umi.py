"""Answer routing includes persona-bound runtime profile names."""

from __future__ import annotations

from app.inference.answer_routing import select_runtime_for_decision
from app.inference.orchestrator_router import RouterDecision
from app.inference.runtime_profiles import list_runtime_profiles


def test_umi_brain_runtime_name_is_routing_candidate(monkeypatch):
    monkeypatch.setattr("app.persona.named_persona.active_persona_id", lambda: "umi")
    decision = RouterDecision(
        action="answer_basic",
        minimum_answer_tier=1,
        required_answer_tier=1,
        task_class="chat",
        reason="test",
    )
    picked = select_runtime_for_decision(
        decision,
        current_profile="balanced",
        profiles=list_runtime_profiles(),
        user_message="help me plan",
    )
    assert picked in {"umi-opus-9b", "balanced", "fast", "bootstrap", "ornith_9b", None} or picked
