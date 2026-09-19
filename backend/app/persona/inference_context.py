"""Auto-grow inference context from live prompt size (owner chat + agent paths)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..agent.context_policy import next_context_size, profile_cap
from ..config import AppSettings, load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..inference.prompt_budget import estimate_messages_tokens
from ..providers.base import ChatMessage

OnExpanding = Callable[[int, int], Awaitable[None] | None]


def required_context_size(
    messages: list[ChatMessage],
    *,
    profile_name: str | None = None,
    settings: AppSettings | None = None,
) -> int:
    """Minimum loaded n_ctx for this message list (never below current if already loaded)."""
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
) -> dict[str, Any]:
    """Load or grow the worker model context to fit messages. Returns routing metadata."""
    app = settings or load_settings()
    profile = resolve_profile(profile_name or app.inference.profile)
    wanted = required_context_size(messages, profile_name=profile.name, settings=app)
    before = int(MANAGER.state.context_size or 0) if MANAGER.state.loaded else 0
    if not MANAGER.provider or not MANAGER.state.loaded:
        await MANAGER.load(app, profile.name, context_size=wanted)
        after = int(MANAGER.state.context_size or wanted)
        return {
            "action": "loaded",
            "context_before": before,
            "context_after": after,
            "wanted": wanted,
            "estimated_tokens": estimate_messages_tokens(messages),
        }
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
        "estimated_tokens": estimate_messages_tokens(messages),
    }


def model_lane_event_payload(*, lane: str, model: str, text: str = "", extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"lane": lane, "model": model, "text": text}
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)[:4000]
