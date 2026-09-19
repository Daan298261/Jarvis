from __future__ import annotations

from app.agent.context_policy import CONTEXT_NORMAL, CONTEXT_SIMPLE
from app.inference.prompt_budget import estimate_messages_tokens
from app.persona.inference_context import model_lane_event_payload, required_context_size
from app.providers.base import ChatMessage


def test_required_context_grows_with_large_history():
    messages = [
        ChatMessage(role="system", content="You are Jarvis."),
        ChatMessage(role="user", content="x" * 12000),
    ]
    estimated = estimate_messages_tokens(messages)
    assert estimated > 1000
    size = required_context_size(messages)
    assert size >= CONTEXT_SIMPLE


def test_model_lane_payload_json():
    raw = model_lane_event_payload(lane="front", model="tiny-chat", text="Hello.")
    assert '"lane"' in raw
    assert "front" in raw


def test_small_prompt_stays_modest():
    messages = [
        ChatMessage(role="system", content="Hi"),
        ChatMessage(role="user", content="Hello"),
    ]
    size = required_context_size(messages)
    assert size in {CONTEXT_SIMPLE, CONTEXT_NORMAL, 32768}
