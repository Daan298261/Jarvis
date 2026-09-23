"""RFC-0115 answer routing: gates, profile pick, handoff injection."""

from __future__ import annotations

from typing import Any

from ..agent.planning import WorkingState
from ..config import AppSettings
from ..providers.base import ChatMessage
from .model_handoff import build_model_handoff, handoff_system_message
from .model_escalation import (
    apply_router_to_working,
    begin_user_turn_routing,
    effective_answer_profile_name,
    execute_visible_model_switch,
    profile_meets_minimum_tier,
)
from .orchestrator_router import RouterDecision, resolve_router_decision
from .profile_roles import infer_runtime_role_and_tier
from .runtime_profiles import RuntimeProfile, get_runtime_profile, list_runtime_profiles
from .runtime_router import AgentRoutingPreferences, RuntimeNodeState, route_runtime


def select_runtime_for_decision(
    decision: RouterDecision,
    *,
    current_profile: str,
    warm_models: tuple[str, ...] = (),
    profiles: list[RuntimeProfile] | None = None,
) -> str | None:
    minimum = int(decision.minimum_answer_tier or 0)
    if decision.action == "answer_basic" and minimum <= 1:
        if profile_meets_minimum_tier(current_profile, minimum):
            return current_profile
    preferred: tuple[str, ...] = ()
    if minimum <= 2:
        preferred = ("balanced", "fast", "qwen38_9b")
    elif minimum == 3:
        preferred = ("quality", "balanced")
    else:
        preferred = ("expert", "ornith_35b")
    prefs = AgentRoutingPreferences(
        minimum_answer_tier=minimum,
        policy="best-result",
        task_specialization="reasoning" if decision.required_answer_tier >= 3 else None,
        preferred_profiles=preferred,
    )
    nodes = [RuntimeNodeState(node_id="localhost", warm_models=warm_models)]
    routed = route_runtime(prefs, nodes=nodes, profiles=profiles)
    if not routed.accepted or routed.runtime_profile is None:
        return None
    return routed.runtime_profile.model_profile or routed.runtime_profile.name


def should_switch_for_decision(
    decision: RouterDecision,
    current_profile: str,
    *,
    runtime_row: RuntimeProfile | None = None,
) -> bool:
    if decision.action in {"switch_model", "delegate"}:
        return True
    if decision.action == "use_tool" and decision.minimum_answer_tier >= 2:
        return not profile_meets_minimum_tier(current_profile, decision.minimum_answer_tier, runtime_row=runtime_row)
    if decision.minimum_answer_tier >= 2:
        return not profile_meets_minimum_tier(current_profile, decision.minimum_answer_tier, runtime_row=runtime_row)
    if decision.action == "answer_basic":
        if decision.minimum_answer_tier <= 1:
            return False
        return not profile_meets_minimum_tier(
            current_profile, decision.minimum_answer_tier, runtime_row=runtime_row
        )
    return False


def runtime_row_for_profile(profile_name: str) -> RuntimeProfile | None:
    row = get_runtime_profile(profile_name)
    if row:
        return row
    for item in list_runtime_profiles():
        if (item.model_profile or item.name) == profile_name:
            return item
    return None


async def prepare_answer_route(
    task_id: str,
    *,
    user_message: str,
    working: WorkingState,
    settings: AppSettings,
    profile_name: str,
    history: list[ChatMessage],
    messages: list[ChatMessage],
    tools_available: bool = True,
    vision_requested: bool = False,
    new_user_turn: bool = True,
    model_output: dict[str, Any] | None = None,
    warm_models: tuple[str, ...] = (),
) -> tuple[str, list[ChatMessage], RouterDecision, bool]:
    """Return effective profile, messages (with optional handoff), decision, switched flag."""
    if new_user_turn:
        begin_user_turn_routing(working)

    loaded = profile_name
    effective = effective_answer_profile_name(working, profile_name, loaded)
    decision = resolve_router_decision(
        user_message,
        current_model=effective,
        task_class=working.task_class,
        recent_turn_count=len([m for m in history if m.role in {"user", "assistant"}]),
        vision_requested=vision_requested,
        prior_failures=len(working.known_failures),
        model_output=model_output,
    )
    apply_router_to_working(working, decision)

    runtime_row = runtime_row_for_profile(effective)
    switched = False
    if should_switch_for_decision(decision, effective, runtime_row=runtime_row):
        target = select_runtime_for_decision(
            decision,
            current_profile=effective,
            warm_models=warm_models or (effective,),
        )
        if target and target != effective:
            handoff = build_model_handoff(
                user_request=user_message,
                history=history,
                working_state_block=working.as_prompt_block(),
                observations=working.observations,
                failed_attempts=working.known_failures,
            )
            handoff_block = handoff_system_message(handoff)
            updated = list(messages)
            updated.insert(1, ChatMessage(role="system", content=handoff_block))
            await execute_visible_model_switch(
                task_id,
                from_profile=effective,
                to_profile=target,
                decision=decision,
                settings=settings,
                working=working,
                speak=True,
            )
            effective = target
            messages = updated
            switched = True
    return effective, messages, decision, switched
