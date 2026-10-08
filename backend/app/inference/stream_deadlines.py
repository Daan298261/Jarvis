"""Caller-supplied streaming stall budgets for inference chat streams.

Budgets themselves live on ``InferenceSettings``. ``providers.base.chat_stream``
must not invent a default — ``None`` means no guard.
"""

from __future__ import annotations

from typing import Any

from ..config import InferenceSettings
from ..observability.rolling_log import record_event


def resolve_prompt_tps(settings: InferenceSettings, measured_tps: float | None) -> float:
    """Use the live measured prompt-processing rate when it is positive."""
    try:
        measured = float(measured_tps) if measured_tps is not None else 0.0
    except (TypeError, ValueError):
        measured = 0.0
    if measured > 0.0:
        return measured
    fallback = float(settings.prompt_tps_fallback)
    return fallback if fallback > 0.0 else 1.0


def compute_first_token_deadline_ms(
    settings: InferenceSettings,
    *,
    prompt_tokens: int,
    prompt_tps: float | None,
) -> float:
    """Scale first-token wait with prompt size / prompt_tps, then apply floor/cap."""
    tokens = max(0, int(prompt_tokens or 0))
    tps = resolve_prompt_tps(settings, prompt_tps)
    prompt_ms = (tokens / tps) * 1000.0
    raw = float(settings.stream_first_token_base_ms) + prompt_ms
    floor = float(settings.stream_first_token_min_ms)
    cap = float(settings.stream_first_token_max_ms)
    if floor > cap:
        floor, cap = cap, floor
    return max(floor, min(cap, raw))


def compute_idle_deadline_ms(settings: InferenceSettings) -> float:
    return float(settings.stream_idle_ms)


def compute_chat_stream_deadlines(
    settings: InferenceSettings,
    *,
    prompt_tokens: int,
    prompt_tps: float | None,
) -> tuple[float, float]:
    """Return ``(first_token_deadline_ms, idle_deadline_ms)`` from settings + prompt size."""
    return (
        compute_first_token_deadline_ms(
            settings,
            prompt_tokens=prompt_tokens,
            prompt_tps=prompt_tps,
        ),
        compute_idle_deadline_ms(settings),
    )


def compute_chat_call_deadline_ms(
    settings: InferenceSettings,
    *,
    prompt_tokens: int,
    prompt_tps: float | None,
) -> float:
    """Non-stream chat returns one body, so the budget is first-token plus idle.

    Scaled with the same prompt-size rules as streaming. Callers pass the
    result into ``ModelProvider.chat``; this function does not invent a
    timeout when settings are absent.
    """
    first_ms, idle_ms = compute_chat_stream_deadlines(
        settings,
        prompt_tokens=prompt_tokens,
        prompt_tps=prompt_tps,
    )
    return first_ms + idle_ms


def record_stream_stall(
    stall: Any,
    *,
    lane: str,
    prompt_token_estimate: int | None = None,
) -> dict[str, Any]:
    """Append one rolling-log event for a stream stall. Never swallows the stall."""
    tokens = prompt_token_estimate
    if tokens is None:
        tokens = getattr(stall, "prompt_tokens", None)
    return record_event(
        "inference_stream_stall",
        message=str(stall),
        lane=str(lane or ""),
        provider=str(getattr(stall, "provider", "") or ""),
        model=str(getattr(stall, "model", "") or ""),
        deadline=str(getattr(stall, "deadline", "") or ""),
        budget_ms=round(float(getattr(stall, "budget_ms", 0.0) or 0.0), 1),
        elapsed_ms=round(float(getattr(stall, "elapsed_ms", 0.0) or 0.0), 1),
        prompt_token_estimate=int(tokens or 0),
    )
