from __future__ import annotations

from types import SimpleNamespace

from app.providers.completion_text import (
    delta_text_channels,
    empty_generation_error,
    visible_completion_text,
)


def test_visible_text_prefers_content_over_reasoning():
    assert (
        visible_completion_text("The match is tonight.", "I should check the fixture list")
        == "The match is tonight."
    )


def test_visible_text_uses_reasoning_when_content_is_empty():
    assert (
        visible_completion_text("", "Latest headlines: markets were mixed, sir.")
        == "Latest headlines: markets were mixed, sir."
    )


def test_visible_text_strips_think_blocks_then_keeps_the_answer():
    raw = "<think>plan the briefing</think>\nMarkets closed mixed."
    assert visible_completion_text(raw) == "Markets closed mixed."


def test_visible_text_uses_reasoning_content_channel_from_parts():
    parts = [
        {"type": "reasoning", "text": "Need current events."},
        {"type": "text", "text": ""},
    ]
    assert visible_completion_text(parts, "BBC: a brief recap.") == "BBC: a brief recap."


def test_delta_channels_read_reasoning_content():
    delta = SimpleNamespace(
        content="",
        reasoning_content="Usable answer hidden in thinking.",
        model_extra={"reasoning_content": "Usable answer hidden in thinking."},
        model_dump=lambda exclude_none=True: {
            "content": "",
            "reasoning_content": "Usable answer hidden in thinking.",
        },
    )
    content, reasoning = delta_text_channels(delta)
    assert content == ""
    assert "Usable answer" in reasoning


def test_empty_generation_error_includes_finish_reason():
    assert "finish_reason=length" in empty_generation_error("length")
    assert "couldn't form a reply" not in empty_generation_error().lower()
