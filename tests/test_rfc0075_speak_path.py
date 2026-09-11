from __future__ import annotations

import pytest

from app.persona.chat_delivery import (
    clear_stream_speak_state,
    enqueue_chat_tts,
    maybe_enqueue_streaming_social_tts,
    pending_chat_tts,
    reset_chat_delivery,
    stream_speak_offset,
)
from app.tts.reply_class import classify_reply_for_speech, register_reply_classifier_hook
from app.tts.speak_filter import filter_text_for_speech, rewrite_for_speech


@pytest.fixture(autouse=True)
def _reset_delivery():
    reset_chat_delivery()
    register_reply_classifier_hook(None)
    yield
    reset_chat_delivery()
    register_reply_classifier_hook(None)


def test_classify_social_weather_and_greeting():
    assert classify_reply_for_speech("**18** to **11** degrees.", user_prompt="What's the weather?") == "social"
    assert classify_reply_for_speech("Hello, sir.", user_prompt="How are you?") == "social"


def test_classify_technical_code_and_traces():
    body = "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: no"
    assert classify_reply_for_speech(body) == "technical"
    assert classify_reply_for_speech("```python\nprint(1)\n```") == "technical"
    assert classify_reply_for_speech("PLAN:\n- step one\n- step two\n" * 5) == "technical"


def test_optional_classifier_hook_can_override():
    register_reply_classifier_hook(lambda _text, _user: "technical")
    assert classify_reply_for_speech("Hi there.", user_prompt="hello") == "technical"


def test_social_weather_speaks_natural_prose_not_markup():
    raw = "Very well, sir. **18** to **11** degrees with light cloud."
    filtered = filter_text_for_speech(raw, source="owner_chat", user_prompt="weather today?")
    assert "**" not in filtered
    assert "asterisk" not in filtered.lower()
    assert "eighteen" in filtered
    assert "eleven" in filtered


def test_technical_still_strips_fences_and_urls():
    raw = "Updated `main.py` — see https://example.com/x\n```diff\n+ fix\n```\nDone."
    filtered = filter_text_for_speech(raw, source="task_chat")
    assert "https://" not in filtered
    assert "```" not in filtered
    assert "main.py" in filtered or "Updated" in filtered


def test_rewrite_strips_list_markers_and_headings():
    raw = "## Forecast\n- **18** degrees\n- dry"
    out = rewrite_for_speech(filter_text_for_speech("# Forecast\n- dry", reply_class="technical"), reply_class="technical")
    assert "#" not in out
    assert "-" not in out or "dry" in out


def test_enqueue_chat_tts_records_reply_class():
    item_id = enqueue_chat_tts(
        "Good evening, sir.",
        source="owner_chat",
        user_prompt="hello",
    )
    assert item_id
    pending = pending_chat_tts()
    assert pending[-1]["reply_class"] == "social"


def test_streaming_social_tts_enqueues_first_sentence_only():
    stream_key = "test:stream"
    clear_stream_speak_state(stream_key)
    first = maybe_enqueue_streaming_social_tts(
        "Certainly",
        source="owner_chat",
        stream_key=stream_key,
        user_prompt="How are you?",
    )
    assert first is None

    second = maybe_enqueue_streaming_social_tts(
        "Certainly. One moment while I look.",
        source="owner_chat",
        stream_key=stream_key,
        user_prompt="How are you?",
    )
    assert second
    assert stream_speak_offset(stream_key) > 0
    assert len(pending_chat_tts()) == 1
    assert pending_chat_tts()[-1]["partial"] is True
    assert pending_chat_tts()[-1]["text"].startswith("Certainly")

    third = maybe_enqueue_streaming_social_tts(
        "Certainly. One moment while I look. All is well.",
        source="owner_chat",
        stream_key=stream_key,
        user_prompt="How are you?",
    )
    assert third is None


def test_early_social_blocked_when_awaiting_tool_unless_ack():
    stream_key = "test:tool"
    clear_stream_speak_state(stream_key)
    assert (
        maybe_enqueue_streaming_social_tts(
            "It is 18 degrees outside.",
            source="task_chat",
            stream_key=stream_key,
            user_prompt="weather?",
            awaiting_tool_result=True,
        )
        is None
    )
    ack = maybe_enqueue_streaming_social_tts(
        "One moment.",
        source="task_chat",
        stream_key=stream_key,
        user_prompt="weather?",
        awaiting_tool_result=True,
    )
    assert ack
