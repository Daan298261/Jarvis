from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError

from app.agent.compaction import compact_history, estimate_prompt_tokens
from app.agent.context_policy import CONTEXT_LONG, CONTEXT_NORMAL, profile_cap
from app.inference.manager import MANAGER
from app.inference.prompt_budget import (
    ModelCapacityExceeded,
    calculate_prompt_budget,
    choose_context_window,
    is_context_overflow,
    output_reserve_tokens,
    prepare_inference,
)
from app.inference.profiles import PROFILES
from app.providers.base import ChatMessage


def test_prompt_budget_includes_tools_and_output_reserve():
    messages = [ChatMessage(role="user", content="hello")]
    tools = [{"type": "function", "function": {"name": "filesystem", "parameters": {"type": "object"}}}]
    budget = calculate_prompt_budget(
        messages,
        tools,
        profile=PROFILES["balanced"],
        max_tokens=1024,
        active_context=16384,
    )
    assert budget.tool_tokens > 0
    assert budget.output_reserve == output_reserve_tokens(16384, 1024)
    assert budget.required_context == (
        budget.prompt_tokens + budget.tool_tokens + budget.output_reserve + budget.system_reserve
    )
    assert budget.pressure == budget.required_context / budget.active_context


def test_token_estimate_consistent_via_compaction_helper():
    messages = [ChatMessage(role="user", content="a" * 800)]
    assert estimate_prompt_tokens(messages) == 400


def test_choose_context_window_grows_tiers_without_shrink():
    assert choose_context_window(9000, CONTEXT_LONG, 8192) == CONTEXT_NORMAL
    assert choose_context_window(20000, CONTEXT_LONG, 16384) == CONTEXT_LONG
    assert choose_context_window(5000, CONTEXT_LONG, 16384) == 16384


def test_is_context_overflow_detects_llama_markers():
    request = httpx.Request("POST", "http://127.0.0.1:8088/v1/chat/completions")
    response = httpx.Response(400, request=request, text="Context size has been exceeded.")
    exc = APIStatusError("Context size has been exceeded.", response=response, body=None)
    assert is_context_overflow(exc)
    assert is_context_overflow(RuntimeError("maximum context length reached"))
    assert not is_context_overflow(RuntimeError("connection reset"))


@pytest.mark.asyncio
async def test_prepare_inference_compacts_before_capacity_error(jarvis_env):
    settings = jarvis_env["settings"]
    profile = PROFILES["balanced"]
    MANAGER.state.context_size = 16384
    MANAGER.state.server_n_ctx = CONTEXT_LONG
    head = [ChatMessage(role="system", content="sys")]
    middle = [ChatMessage(role="assistant", content="x" * 5000) for _ in range(20)]
    tail = [ChatMessage(role="user", content="latest")]
    messages = head + middle + tail
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}]
    prepared = await prepare_inference(
        messages,
        tools,
        profile,
        1024,
        settings,
        manager=MANAGER,
    )
    assert len(prepared.messages) < len(messages)
    assert prepared.budget.pressure < 1.0 or prepared.budget.active_context >= prepared.budget.required_context


@pytest.mark.asyncio
async def test_prepare_inference_expands_16k_to_32k_under_pressure(jarvis_env):
    settings = jarvis_env["settings"]
    profile = PROFILES["balanced"]
    MANAGER.state.context_size = CONTEXT_NORMAL
    MANAGER.state.server_n_ctx = CONTEXT_LONG
    big = ChatMessage(role="user", content="y" * 12000)
    messages = [ChatMessage(role="system", content="s"), big]
    prepared = await prepare_inference(
        messages,
        None,
        profile,
        512,
        settings,
        manager=MANAGER,
    )
    assert MANAGER.state.context_size >= CONTEXT_LONG or prepared.budget.pressure < 0.85


def test_model_capacity_exceeded_carries_budget_snapshot():
    budget = calculate_prompt_budget(
        [ChatMessage(role="user", content="hi")],
        None,
        profile=PROFILES["fast"],
        max_tokens=256,
        active_context=8192,
    )
    exc = ModelCapacityExceeded(budget)
    assert exc.budget.profile_cap == profile_cap(PROFILES["fast"])
    assert "capacity exceeded" in str(exc).lower()
