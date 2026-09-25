from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.planning import WorkingState
from app.inference.answer_routing import prepare_answer_route, select_runtime_for_decision
from app.inference.complexity_scorer import score_question_complexity
from app.inference.model_handoff import build_model_handoff
from app.inference.model_escalation import CANONICAL_SWITCH_USER_MESSAGE, effective_answer_profile_name
from app.inference.orchestrator_router import resolve_router_decision
from app.inference.profile_roles import infer_runtime_role_and_tier
from app.inference.runtime_profiles import RuntimeProfile, reset_runtime_profiles
from app.inference.runtime_router import AgentRoutingPreferences, RuntimeNodeState, route_runtime
from app.providers.base import ChatMessage
from app.providers.completion_text import strip_think_blocks


@pytest.fixture
def runtime_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    reset_runtime_profiles()
    return jarvis_env["tmp"]


def _rt(name: str, tier: int, role: str, warm: bool = False) -> RuntimeProfile:
    return RuntimeProfile(
        id=name,
        name=name,
        label=name,
        model=name,
        provider="local-llama",
        endpoint="127.0.0.1:8088",
        context_limit=32768,
        quantization="Q8",
        privacy_class="local-only",
        cost_ceiling_usd=0.0,
        model_profile=name,
        enabled=True,
        runtime_role=role,
        answer_tier=tier,
    )


def test_profile_defaults_ornith_orchestrator_tier1(runtime_store):
    role, tier = infer_runtime_role_and_tier("ornith_9b")
    assert role == "orchestrator"
    assert tier == 1
    role, tier = infer_runtime_role_and_tier("balanced")
    assert role == "general"
    assert tier == 2


def test_gate_before_score_ornith_cannot_satisfy_tier2(runtime_store):
    profiles = [
        _rt("ornith_9b", 1, "orchestrator"),
        _rt("balanced", 2, "general"),
    ]
    prefs = AgentRoutingPreferences(minimum_answer_tier=2, policy="best-result")
    decision = route_runtime(
        prefs,
        nodes=[RuntimeNodeState(node_id="localhost", warm_models=("ornith_9b",))],
        profiles=profiles,
    )
    assert decision.accepted is True
    assert decision.runtime_profile is not None
    assert decision.runtime_profile.name == "balanced"


def test_warm_bonus_cannot_bypass_tier_gate(runtime_store):
    profiles = [
        _rt("ornith_9b", 1, "orchestrator"),
        _rt("fast", 2, "general"),
    ]
    prefs = AgentRoutingPreferences(minimum_answer_tier=2, policy="best-result")
    warm = route_runtime(
        prefs,
        nodes=[RuntimeNodeState(node_id="localhost", warm_models=("fast",))],
        profiles=profiles,
    )
    cold = route_runtime(
        prefs,
        nodes=[RuntimeNodeState(node_id="localhost", warm_models=())],
        profiles=profiles,
    )
    assert warm.runtime_profile.name == cold.runtime_profile.name == "fast"
    assert warm.score is not None and warm.score.warm_bonus > 0
    ornith_only = route_runtime(
        prefs,
        nodes=[RuntimeNodeState(node_id="localhost", warm_models=("ornith_9b",))],
        profiles=profiles,
    )
    assert ornith_only.runtime_profile.name == "fast"


def test_trivial_request_stays_on_ornith_answer_basic():
    decision = resolve_router_decision("hello", current_model="ornith_9b")
    assert decision.action == "answer_basic"
    assert decision.minimum_answer_tier <= 1


def test_architecture_question_escalates():
    decision = resolve_router_decision(
        "How should we redesign the Jarvis architecture for multi-agent routing?",
        current_model="ornith_9b",
    )
    assert decision.minimum_answer_tier >= 3
    assert decision.action in {"switch_model", "use_tool"}


@pytest.mark.asyncio
async def test_visible_model_switch_event(runtime_store, jarvis_env):
    from app.inference.model_escalation import execute_visible_model_switch
    from app.inference.orchestrator_router import RouterDecision

    published: list[tuple] = []

    async def capture(task_id, kind, title, detail="", stage="", **kwargs):
        published.append((kind, detail))

    working = WorkingState()
    decision = RouterDecision(
        action="switch_model",
        required_answer_tier=2,
        minimum_answer_tier=2,
        reason="test",
    )
    with patch("app.inference.model_escalation.BUS.publish", new=AsyncMock(side_effect=capture)):
        with patch("app.inference.model_escalation.publish_owner_text", new=AsyncMock()):
            with patch("app.inference.model_escalation.MANAGER.load", new=AsyncMock()):
                await execute_visible_model_switch(
                    "task-1",
                    from_profile="ornith_9b",
                    to_profile="balanced",
                    decision=decision,
                    settings=jarvis_env["settings"],
                    working=working,
                )
    kinds = [k for k, _ in published]
    assert "model_switch" in kinds
    switch_payload = json.loads(next(d for k, d in published if k == "model_switch"))
    assert switch_payload["user_message"] == CANONICAL_SWITCH_USER_MESSAGE


def test_handoff_preserves_request_and_recent_turns():
    history = [
        ChatMessage(role="user", content="older question"),
        ChatMessage(role="assistant", content="older answer"),
        ChatMessage(role="user", content="current architecture question"),
    ]
    handoff = build_model_handoff(
        user_request="current architecture question",
        history=history,
        working_state_block="Goal: test",
    )
    assert handoff.user_request == "current architecture question"
    assert any("current architecture" in (m.content or "") for m in handoff.recent_turns)


def test_handoff_strips_hidden_reasoning():
    history = [
        ChatMessage(
            role="assistant",
            content="Visible line",
            reasoning_content="hidden chain of thought must not transfer",
        )
    ]
    handoff = build_model_handoff(user_request="q", history=history)
    blob = json.dumps(handoff.as_dict())
    assert "hidden chain" not in blob
    for turn in handoff.recent_turns:
        assert "hidden" not in (turn.content or "").lower()


def test_escalated_model_stays_for_turn():
    working = WorkingState(active_answer_profile="quality", minimum_answer_tier=3)
    assert effective_answer_profile_name(working, "ornith_9b", "ornith_9b") == "quality"


def test_screenshot_capabilities_prompt_tier2_tool_path():
    prompt = (
        "Can you tell me about your current capabilities, e.g. how much of it is fully "
        "implemented and working and how much is only half baked?"
    )
    baseline = score_question_complexity(prompt, task_class="conversation")
    decision = resolve_router_decision(prompt, current_model="ornith_9b")
    assert baseline.minimum_answer_tier >= 2
    assert decision.prefer_tool or decision.action == "use_tool"
    assert decision.action != "answer_basic"


@pytest.mark.asyncio
async def test_prepare_answer_route_switches_from_ornith(runtime_store, jarvis_env):
    working = WorkingState()
    messages = [ChatMessage(role="user", content="Explain the system architecture in depth")]
    profiles = [_rt("ornith_9b", 1, "orchestrator"), _rt("quality", 3, "reasoner")]
    with patch("app.inference.answer_routing.execute_visible_model_switch", new=AsyncMock()) as switch:
        with patch("app.inference.runtime_router.list_runtime_profiles", return_value=profiles):
            profile, _, decision, switched = await prepare_answer_route(
                "t1",
                user_message=messages[0].content,
                working=working,
                settings=jarvis_env["settings"],
                profile_name="ornith_9b",
                history=[],
                messages=messages,
                warm_models=("ornith_9b",),
            )
    assert decision.minimum_answer_tier >= 3
    assert switch.called
    assert switch.call_args.kwargs["to_profile"] == "quality"


def test_select_runtime_for_decision_respects_tier(runtime_store):
    profiles = [_rt("ornith_9b", 1, "orchestrator"), _rt("quality", 3, "reasoner")]
    decision = resolve_router_decision("architecture plan for routing", current_model="ornith_9b")
    target = select_runtime_for_decision(
        decision,
        current_profile="ornith_9b",
        profiles=profiles,
    )
    assert target == "quality"
