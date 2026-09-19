"""Auto-grow inference context from live prompt size (owner chat + agent paths)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..agent.context_policy import next_context_size, profile_cap
from ..agent.front_responder import RUNTIME_ROLE, resolve_front_model_id, spawn_context_switch_keep_busy
from ..config import AppSettings, load_settings
from ..events import BUS
from ..inference.context_model_select import select_profile_for_context
from ..inference.manager import MANAGER
from ..inference.profiles import ModelProfile, resolve_profile
from ..inference.prompt_budget import PromptBudget, calculate_prompt_budget, estimate_messages_tokens
from ..inference.runtime_profiles import RuntimeProfile, list_runtime_profiles
from ..providers.base import ChatMessage

OnExpanding = Callable[[int, int], Awaitable[None] | None]


def required_context_size(
    messages: list[ChatMessage],
    *,
    profile_name: str | None = None,
    settings: AppSettings | None = None,
) -> int:
    app = settings or load_settings()
    profile = resolve_profile(profile_name or app.inference.profile)
    cap = profile_cap(profile)
    estimated = estimate_messages_tokens(messages)
    current = int(MANAGER.state.context_size or 0) if MANAGER.state.loaded else 0
    if current <= 0:
        from ..agent.context_policy import initial_context_size

        return min(cap, initial_context_size("mixed", profile))
    target = next_context_size(current, cap, estimated) or current
    if estimated >= int(current * 0.85):
        from ..agent.model_policy import bump_context_tier

        bumped = bump_context_tier(current)
        target = max(target, min(bumped, cap))
    return max(current, min(target, cap))


async def ensure_context_for_messages(
    messages: list[ChatMessage],
    *,
    settings: AppSettings | None = None,
    profile_name: str | None = None,
    on_expanding: OnExpanding | None = None,
    task_id: str | None = None,
    bus_channel: str | None = None,
) -> dict[str, Any]:
    app = settings or load_settings()
    profile = resolve_profile(profile_name or app.inference.profile)
    if estimate_messages_tokens(messages) > profile_cap(profile):
        budget = calculate_prompt_budget(
            messages,
            None,
            profile=profile,
            max_tokens=1024,
            active_context=MANAGER.live_context_size() or profile_cap(profile),
        )
        switched = await maybe_autoselect_runtime_for_budget(
            budget,
            profile,
            app,
            user_prompt=messages[-1].content if messages else "",
            task_id=task_id,
            bus_channel=bus_channel,
        )
        if switched:
            profile = switched
    wanted = required_context_size(messages, profile_name=profile.name, settings=app)
    before = int(MANAGER.state.context_size or 0) if MANAGER.state.loaded else 0
    if not MANAGER.provider or not MANAGER.state.loaded:
        await MANAGER.load(app, profile.name, context_size=wanted)
        after = int(MANAGER.state.context_size or wanted)
        return {"action": "loaded", "context_before": before, "context_after": after, "wanted": wanted, "profile": profile.name}
    if wanted > before:
        if on_expanding:
            maybe = on_expanding(before, wanted)
            if hasattr(maybe, "__await__"):
                await maybe
        await MANAGER.ensure_runtime(app, profile.name, context_size=wanted)
    after = int(MANAGER.state.context_size or wanted)
    return {
        "action": "expanded" if after > before else "unchanged",
        "context_before": before,
        "context_after": after,
        "wanted": wanted,
        "profile": profile.name,
    }


def runtime_role_for_lane(lane: str) -> str:
    if lane == "front":
        return RUNTIME_ROLE
    if lane == "worker":
        return "worker"
    return "system"


def model_lane_event_payload(
    *,
    lane: str,
    model: str,
    text: str = "",
    extra: dict[str, Any] | None = None,
    runtime_role: str | None = None,
    source_model: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "lane": lane,
        "model": model,
        "text": text,
        "runtime_role": runtime_role or runtime_role_for_lane(lane),
        "source_model": source_model or model,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)[:4000]


def chat_segment_payload(text: str, *, source_model: str, runtime_role: str) -> str:
    return json.dumps({"text": text, "source_model": source_model, "runtime_role": runtime_role}, ensure_ascii=False)[:4000]


async def maybe_autoselect_runtime_for_budget(
    budget: PromptBudget,
    profile: ModelProfile,
    settings: AppSettings,
    *,
    user_prompt: str = "",
    task_id: str | None = None,
    bus_channel: str | None = None,
) -> ModelProfile | None:
    required = int(budget.required_context or 0)
    cap = int(budget.profile_cap or profile_cap(profile))
    if required <= cap and budget.pressure < 0.95:
        return None
    runtimes = list_runtime_profiles()
    current_runtime: RuntimeProfile | ModelProfile | None = None
    for row in runtimes:
        if (row.model_profile or row.name) == profile.name or row.name == profile.name:
            current_runtime = row
            break
    if current_runtime is None:
        current_runtime = profile
    chosen = select_profile_for_context(required, runtimes, current_runtime)
    if chosen is None or not isinstance(chosen, RuntimeProfile):
        return None

    async def _publish_keep_busy(text: str) -> None:
        target = task_id or bus_channel
        if not target:
            return
        await BUS.publish(
            target,
            "chat_tts",
            "Switching model",
            chat_segment_payload(text, source_model=resolve_front_model_id(settings), runtime_role=RUNTIME_ROLE),
            stage="chat",
            persist=False,
        )

    spawn_context_switch_keep_busy(settings=settings, user_text=user_prompt, on_spoken=_publish_keep_busy)
    from ..inference.hotswap import activate_runtime_profile

    await activate_runtime_profile(chosen, force=True)
    return resolve_profile((chosen.model_profile or chosen.name or profile.name).strip())
