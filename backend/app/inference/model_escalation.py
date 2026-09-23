"""RFC-0115 visible model switch, observability events, and idle orchestrator restore."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from ..agent.planning import WorkingState
from ..config import AppSettings, load_settings
from ..events import BUS
from ..inference.manager import MANAGER
from ..persona.chat_delivery import publish_owner_text
from .profile_roles import default_orchestrator_profile_name, infer_runtime_role_and_tier, orchestrator_profile_names
from .orchestrator_router import RouterDecision

CANONICAL_SWITCH_USER_MESSAGE = (
    "I'm switching to a more capable model so I can answer that properly."
)

_idle_restore_task: asyncio.Task | None = None


def orchestrator_idle_seconds(settings: AppSettings | None = None) -> int:
    app = settings or load_settings()
    raw = int(getattr(app.inference, "orchestrator_idle_seconds", 120) or 120)
    return max(60, min(180, raw))


def is_orchestrator_profile(profile_name: str) -> bool:
    return (profile_name or "").strip().lower() in orchestrator_profile_names()


def profile_meets_minimum_tier(profile_name: str, minimum_tier: int, *, runtime_row=None) -> bool:
    if minimum_tier <= 0:
        return True
    if runtime_row is not None:
        tier = int(getattr(runtime_row, "answer_tier", 0) or 0)
        if tier >= minimum_tier:
            return True
    _, tier = infer_runtime_role_and_tier(profile_name)
    return tier >= minimum_tier


def effective_answer_profile_name(
    working: WorkingState,
    requested: str | None,
    loaded: str | None,
) -> str:
    """Keep escalated model for the remainder of the current user turn (RFC-0115 §10)."""
    active = (working.active_answer_profile or "").strip()
    if active:
        return active
    if requested:
        return requested
    return loaded or default_orchestrator_profile_name()


def begin_user_turn_routing(working: WorkingState) -> None:
    working.active_answer_profile = ""
    working.minimum_answer_tier = 0
    working.router_action = ""


def apply_router_to_working(working: WorkingState, decision: RouterDecision) -> None:
    working.minimum_answer_tier = max(int(working.minimum_answer_tier or 0), int(decision.minimum_answer_tier))
    working.router_action = decision.action
    if decision.task_class:
        working.task_class = decision.task_class


def schedule_orchestrator_restore(settings: AppSettings | None = None) -> None:
    """After a heavy model finishes a turn, restore warm orchestrator after idle timeout."""
    global _idle_restore_task
    app = settings or load_settings()
    target = default_orchestrator_profile_name()

    async def _run() -> None:
        await asyncio.sleep(orchestrator_idle_seconds(app))
        if not MANAGER.state.loaded:
            return
        current = (MANAGER.state.profile or "").strip().lower()
        if is_orchestrator_profile(current):
            return
        try:
            await MANAGER.load(app, target)
        except Exception:
            return

    if _idle_restore_task and not _idle_restore_task.done():
        _idle_restore_task.cancel()
    _idle_restore_task = asyncio.create_task(_run())


async def publish_route_observability(
    task_id: str,
    *,
    request_id: str,
    from_model: str,
    to_model: str,
    decision: RouterDecision,
    required_context: int = 0,
    active_context: int = 0,
    automatic: bool = True,
    phase: str,
) -> None:
    payload = {
        "request_id": request_id,
        "from_model": from_model,
        "to_model": to_model,
        "required_answer_tier": decision.required_answer_tier,
        "required_context": required_context,
        "active_context": active_context,
        "reason": decision.reason,
        "automatic": automatic,
        "phase": phase,
    }
    await BUS.publish(
        task_id,
        "model_route_decision" if phase == "decision" else f"model_switch_{phase}",
        phase.replace("_", " ").title(),
        json.dumps(payload, ensure_ascii=False)[:4000],
        stage="model",
    )


async def execute_visible_model_switch(
    task_id: str,
    *,
    from_profile: str,
    to_profile: str,
    decision: RouterDecision,
    settings: AppSettings,
    working: WorkingState,
    required_context: int = 0,
    active_context: int = 0,
    speak: bool = True,
) -> None:
    request_id = str(uuid.uuid4())
    await publish_route_observability(
        task_id,
        request_id=request_id,
        from_model=from_profile,
        to_model=to_profile,
        decision=decision,
        required_context=required_context,
        active_context=active_context,
        phase="decision",
    )
    await BUS.publish(
        task_id,
        "model_switch_started",
        "Model switch started",
        json.dumps({"request_id": request_id, "from": from_profile, "to": to_profile}, ensure_ascii=False),
        stage="model",
    )
    if speak:
        await publish_owner_text(
            CANONICAL_SWITCH_USER_MESSAGE,
            source="model_switch",
            speak=True,
        )
    await MANAGER.load(settings, to_profile, force=True)
    working.model_escalation_count = int(working.model_escalation_count or 0) + 1
    working.active_answer_profile = to_profile
    working.escalated = True
    switch_payload = {
        "from": from_profile,
        "to": to_profile,
        "reason": decision.reason,
        "user_message": CANONICAL_SWITCH_USER_MESSAGE,
        "request_id": request_id,
    }
    await BUS.publish(
        task_id,
        "model_switch",
        "Switching model",
        json.dumps(switch_payload, ensure_ascii=False)[:4000],
        stage="model",
    )
    await publish_route_observability(
        task_id,
        request_id=request_id,
        from_model=from_profile,
        to_model=to_profile,
        decision=decision,
        required_context=required_context,
        active_context=active_context,
        phase="completed",
    )
    if not is_orchestrator_profile(to_profile):
        schedule_orchestrator_restore(settings)


async def reroute_inference_failure(
    task_id: str,
    *,
    working: WorkingState,
    settings: AppSettings,
    current_profile: str,
    reason_code: str,
    user_message: str = "",
) -> str | None:
    """Inference reroute uses the same tier gates + visible switch (RFC-0115 §12)."""
    from .answer_routing import select_runtime_for_decision
    from .orchestrator_router import resolve_router_decision

    decision = resolve_router_decision(
        user_message or working.goal,
        current_model=current_profile,
        task_class=working.task_class,
        prior_failures=len(working.known_failures),
    )
    apply_router_to_working(working, decision)
    target = select_runtime_for_decision(
        decision,
        current_profile=current_profile,
        warm_models=(current_profile,) if current_profile else (),
    )
    if not target or target == current_profile:
        return None
    decision.reason = f"{reason_code}: {decision.reason}"
    await execute_visible_model_switch(
        task_id,
        from_profile=current_profile,
        to_profile=target,
        decision=decision,
        settings=settings,
        working=working,
        speak=True,
    )
    return target
