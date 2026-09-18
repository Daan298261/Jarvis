from __future__ import annotations

import json

import pytest

from app.inference.context_window import clamp_n_keep, n_keep_for_messages
from app.inference.inference_prompt import (
    inference_message_text,
    sanitize_messages_for_inference,
    serialized_inference_prompt,
)
from app.inference.manager import InferenceManager
from app.persona.pack import compact_identity_instructions
from app.providers.base import ChatMessage, to_openai_messages


def test_reasoning_content_absent_from_serialized_inference_prompt():
    reasoning_blob = "INTERNAL_CHAIN_OF_THOUGHT " * 400
    messages = [
        ChatMessage(role="user", content="status check"),
        ChatMessage(
            role="assistant",
            content="Very well, sir — all nominal.",
            reasoning_content=reasoning_blob,
        ),
    ]
    wire = serialized_inference_prompt(messages)
    assert "reasoning_content" not in wire
    assert "INTERNAL_CHAIN_OF_THOUGHT" not in wire
    assert "all nominal" in wire


def test_user_plan_prompt_lines_preserved_for_inference():
    plan_user = "END STATE: x\nACCEPTANCE CRITERIA:\n- y\nPLAN:\n1. step"
    wire = serialized_inference_prompt([ChatMessage(role="user", content=plan_user)])
    assert "END STATE: x" in wire
    assert "PLAN:" in wire


def test_plan_and_labeled_reasoning_stripped_from_assistant_content():
    raw = (
        "PLAN: enumerate every vault file\n"
        "END STATE: full dump in prompt\n"
        "Reasoning: I will paste the entire graph.\n"
        "Final reply: Shall I proceed, sir?"
    )
    message = ChatMessage(role="assistant", content=raw)
    cleaned = inference_message_text(message)
    assert "PLAN:" not in cleaned
    assert "END STATE:" not in cleaned
    assert "Reasoning:" not in cleaned
    assert "Final reply:" not in cleaned.lower()
    assert "Shall I proceed" in cleaned


def test_redacted_thinking_blocks_never_serialize():
    think = "<think>" + ("secret " * 200) + "</think>"
    messages = [
        ChatMessage(role="assistant", content=f"{think}\nAnswer: done."),
    ]
    wire = serialized_inference_prompt(messages)
    assert "redacted_thinking" not in wire
    assert "secret" not in wire
    assert "Answer: done" in wire


@pytest.mark.parametrize("n_ctx", (4096, 8192, 16384))
def test_n_keep_strictly_below_n_ctx_for_configured_windows(n_ctx: int):
    identity = compact_identity_instructions()
    recovered = identity + "\n\nTool exposure: browser\n" + ("recovered blob " * 4000)
    messages = [
        ChatMessage(role="system", content=recovered),
        ChatMessage(role="user", content="voice check"),
    ]
    keep = n_keep_for_messages(messages, n_ctx, max_tokens=1024, identity_text=identity)
    assert keep < n_ctx
    assert keep == clamp_n_keep(keep, n_ctx, max_tokens=1024)


def test_manager_with_n_keep_never_emits_keep_ge_n_ctx():
    mgr = InferenceManager()
    mgr.state.context_size = 4096
    mgr.state.server_n_ctx = 4096
    messages = [
        ChatMessage(role="system", content="x" * 50000),
        ChatMessage(role="user", content="hi"),
    ]
    extra = mgr._with_n_keep({"n_keep": 9000}, messages, max_tokens=256)
    assert extra["n_keep"] < 4096


def test_to_openai_messages_can_include_reasoning_for_ui_paths():
    message = ChatMessage(role="assistant", content="hi", reasoning_content="hidden")
    infer = to_openai_messages([message], for_inference=True)
    ui = to_openai_messages([message], for_inference=False)
    assert "reasoning_content" not in infer[0]
    assert ui[0].get("reasoning_content") == "hidden"


def test_token_estimate_ignores_reasoning_channel_and_plan_lines():
    from app.inference.prompt_budget import estimate_messages_tokens

    messages = [
        ChatMessage(
            role="assistant",
            content="PLAN: huge\nReasoning: " + ("Z" * 8000) + "\nFinal reply: ok",
            reasoning_content="W" * 6000,
        ),
    ]
    estimated = estimate_messages_tokens(messages)
    assert estimated < 8000
