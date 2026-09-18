"""RFC-0114: canonical prompt budget, overflow detection, and inference preflight."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from ..agent.compaction import compact_history
from ..agent.context_policy import CONTEXT_LONG, CONTEXT_NORMAL, CONTEXT_SIMPLE, profile_cap
from ..config import AppSettings
from .context_window import CHARS_PER_TOKEN, is_n_keep_overflow
from .inference_prompt import inference_message_text
from ..providers.base import ChatMessage
from .profiles import ModelProfile

PRESSURE_COMPACT = 0.70
PRESSURE_EXPAND_OK = 0.85
SYSTEM_RESERVE_TOKENS = 256


@dataclass(frozen=True)
class PromptBudget:
    prompt_tokens: int
    tool_tokens: int
    output_reserve: int
    system_reserve: int
    required_context: int
    active_context: int
    profile_cap: int
    pressure: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "tool_tokens": self.tool_tokens,
            "output_reserve": self.output_reserve,
            "system_reserve": self.system_reserve,
            "required_context": self.required_context,
            "active_context": self.active_context,
            "profile_cap": self.profile_cap,
            "pressure": round(self.pressure, 4),
        }


@dataclass
class PreparedInference:
    messages: list[ChatMessage]
    tools: list[dict[str, Any]] | None
    profile: ModelProfile
    budget: PromptBudget


class ModelCapacityExceeded(Exception):
    """The active model window cannot fit the prompt after compact + expand (same-model recovery exhausted)."""

    def __init__(self, budget: PromptBudget) -> None:
        self.budget = budget
        super().__init__(context_capacity_error(budget))


def context_capacity_error(budget: PromptBudget) -> str:
    return (
        "Context capacity exceeded after compact/expand recovery: "
        f"required_context={budget.required_context} tokens, "
        f"active_context={budget.active_context}, profile_cap={budget.profile_cap} "
        f"(pressure={budget.pressure:.2f})."
    )


_OVERFLOW_MARKERS = (
    "context size has been exceeded",
    "context length exceeded",
    "maximum context length",
    "too many tokens",
    "prompt is too long",
)


def is_context_overflow(exc: BaseException) -> bool:
    if is_n_keep_overflow(getattr(exc, "body", None)) or is_n_keep_overflow(exc):
        return True
    text = str(exc).lower()
    body = getattr(exc, "body", None)
    if body is not None:
        text = f"{text} {body}".lower()
    message = getattr(exc, "message", None)
    if message:
        text = f"{text} {message}".lower()
    return any(marker in text for marker in _OVERFLOW_MARKERS)


def _message_text(message: ChatMessage) -> str:
    return inference_message_text(message)


def estimate_text_tokens(text: str, *, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    """Conservative fallback when no backend tokenizer is available."""
    if not text:
        return 0
    return max(1, len(text) // max(1, chars_per_token))


def estimate_messages_tokens(messages: Iterable[ChatMessage]) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(_message_text(message))
        if message.tool_calls:
            total += estimate_text_tokens(json.dumps(message.tool_calls, ensure_ascii=False))
    return total


def estimate_tool_tokens(tools: list[dict[str, Any]] | None) -> int:
    if not tools:
        return 0
    return estimate_text_tokens(json.dumps(tools, ensure_ascii=False))


def output_reserve_tokens(active_context: int, max_tokens: int | None) -> int:
    limit = int(active_context or 0)
    requested = int(max_tokens or 1024)
    return max(256, min(requested, max(256, limit // 2) if limit > 0 else requested))


def calculate_prompt_budget(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    *,
    profile: ModelProfile,
    max_tokens: int | None,
    active_context: int,
) -> PromptBudget:
    cap = profile_cap(profile)
    active = int(active_context or 0) or cap
    prompt_tokens = estimate_messages_tokens(messages)
    tool_tokens = estimate_tool_tokens(tools)
    output_reserve = output_reserve_tokens(active, max_tokens)
    system_reserve = SYSTEM_RESERVE_TOKENS
    required = prompt_tokens + tool_tokens + output_reserve + system_reserve
    pressure = required / active if active > 0 else 1.0
    return PromptBudget(
        prompt_tokens=prompt_tokens,
        tool_tokens=tool_tokens,
        output_reserve=output_reserve,
        system_reserve=system_reserve,
        required_context=required,
        active_context=active,
        profile_cap=cap,
        pressure=pressure,
    )


def choose_context_window(required: int, cap: int, current: int) -> int:
    """Pick the smallest tier that fits ``required``, never below ``current`` (no mid-turn shrink)."""
    cap = int(cap or CONTEXT_LONG)
    current = max(0, int(current or 0))
    required = max(1, int(required or 0))
    chosen = current
    for tier in (CONTEXT_SIMPLE, CONTEXT_NORMAL, CONTEXT_LONG):
        if tier < required:
            continue
        if tier > cap:
            break
        chosen = max(chosen, tier)
        if tier >= required:
            return chosen
    if required <= cap:
        return max(chosen, min(cap, required))
    return max(chosen, cap)


ContextEventEmitter = Callable[[str, PromptBudget, str], Awaitable[None]]


async def prepare_inference(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    profile: ModelProfile,
    max_tokens: int | None,
    settings: AppSettings,
    *,
    manager: Any,
    working_state_block: str | None = None,
    emit: ContextEventEmitter | None = None,
) -> PreparedInference:
    """Preflight every inference call: budget, compact, expand — before the HTTP request."""
    active = manager.live_context_size()
    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
        active_context=active,
    )
    if budget.pressure < PRESSURE_COMPACT:
        return PreparedInference(messages, tools, profile, budget)

    if emit:
        await emit("context_pressure_detected", budget, "preflight pressure >= 0.70")

    if emit:
        await emit("context_compaction_started", budget, "compact_history")
    messages = compact_history(messages, working_state_block=working_state_block)
    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
        active_context=manager.live_context_size(),
    )
    if budget.pressure < PRESSURE_COMPACT:
        return PreparedInference(messages, tools, profile, budget)

    cap = profile_cap(profile)
    live = int(manager.state.context_size or 0)
    if live < cap:
        target = choose_context_window(budget.required_context, cap, manager.live_context_size())
        if target > manager.live_context_size():
            grown = await manager.apply_context(settings, target, allow_shrink=False)
            if emit:
                await emit(
                    "context_expanded",
                    calculate_prompt_budget(
                        messages,
                        tools,
                        profile=profile,
                        max_tokens=max_tokens,
                        active_context=grown,
                    ),
                    f"expanded to {grown}",
                )
            budget = calculate_prompt_budget(
                messages,
                tools,
                profile=profile,
                max_tokens=max_tokens,
                active_context=grown,
            )
            if budget.pressure < PRESSURE_EXPAND_OK:
                return PreparedInference(messages, tools, profile, budget)

    return PreparedInference(messages, tools, profile, budget)


async def recover_context_after_overflow(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    profile: ModelProfile,
    max_tokens: int | None,
    settings: AppSettings,
    *,
    manager: Any,
    working_state_block: str | None = None,
    emit: ContextEventEmitter | None = None,
) -> tuple[list[ChatMessage], bool]:
    """Compact and expand after a recoverable overflow error (same-model recovery only)."""
    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
        active_context=manager.live_context_size(),
    )
    if emit:
        await emit("context_retry", budget, "overflow recovery")

    if emit:
        await emit("context_compaction_started", budget, "post-overflow compact")
    messages = compact_history(messages, working_state_block=working_state_block)

    cap = profile_cap(profile)
    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
        active_context=manager.live_context_size(),
    )
    target = choose_context_window(budget.required_context, cap, manager.live_context_size())
    if target > manager.live_context_size():
        grown = await manager.apply_context(settings, target, allow_shrink=False)
        if emit and grown >= target:
            await emit(
                "context_expanded",
                calculate_prompt_budget(
                    messages,
                    tools,
                    profile=profile,
                    max_tokens=max_tokens,
                    active_context=grown,
                ),
                f"recovery expanded to {grown}",
            )

    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
        active_context=manager.live_context_size(),
    )
    if budget.pressure < PRESSURE_EXPAND_OK:
        return messages, True

    if emit:
        await emit("context_recovery_failed", budget, "recovery exhausted")
    return messages, False


# Re-export for compaction module compatibility
def estimate_prompt_tokens(messages: list[ChatMessage]) -> int:
    return estimate_messages_tokens(messages)
