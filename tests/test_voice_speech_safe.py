"""Nothing unpronounceable or internal reaches the voice."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.providers.completion_text import visible_completion_text
from app.tts.speak_filter import filter_text_for_speech
from app.tts.speech_safe import speech_safe

LEAKED_TRACE = (
    "Thinking Process:\n\n1.  **Analyze the Request:**\n"
    "    *   **Role:** Jarvis (British-inspired, intelligent, dry). Address owner as \"sir\".\n"
    "    *   The user wants Steam opened."
)


def test_paths_become_names_and_markdown_disappears():
    spoken = speech_safe('**Done.** I opened "C:\\Program Files (x86)\\Steam\\steam.exe" for you.')
    assert "\\" not in spoken and "*" not in spoken and "C:" not in spoken
    assert "steam" in spoken.lower()


def test_urls_become_site_names():
    assert speech_safe("Details are on https://www.bbc.co.uk/news/world today.") == "Details are on bbc.co.uk today."


def test_symbol_only_text_is_not_spoken():
    assert speech_safe("\\\\ ** __ ## ``") == ""


def test_lists_and_inline_code_read_naturally():
    spoken = speech_safe("- first item\n- second item\nRun `pip install x` then **restart**.")
    assert spoken == "first item. second item. Run pip install x then restart."


def test_leaked_reasoning_trace_is_never_spoken_or_returned():
    assert speech_safe(LEAKED_TRACE) == ""
    assert visible_completion_text("", LEAKED_TRACE) == ""
    assert visible_completion_text(LEAKED_TRACE) == ""


def test_trace_with_final_answer_keeps_only_the_answer():
    text = "Thinking Process:\n1. **Analyze the Request:** user wants steam.\n\nFinal answer: Steam is open, sir."
    assert visible_completion_text(text) == "Steam is open, sir."


def test_short_answer_in_reasoning_channel_still_used():
    assert visible_completion_text("", "Latest headlines: markets were mixed, sir.") == "Latest headlines: markets were mixed, sir."


def test_filter_output_is_speech_safe():
    spoken = filter_text_for_speech(
        "I opened **Steam** from C:\\Program Files (x86)\\Steam\\steam.exe and it is running now.",
        source="task_chat",
    )
    assert spoken
    assert "*" not in spoken and "\\" not in spoken


def test_speak_endpoint_refuses_unspeakable_text(jarvis_env, monkeypatch):
    from app.main import app

    called: list[str] = []

    async def fake_synth(text, **_kwargs):
        called.append(text)
        raise RuntimeError("not reached in this test")

    monkeypatch.setattr("app.api.voice.speak_text", fake_synth)
    client = TestClient(app)
    response = client.post("/api/voice/speak", json={"text": LEAKED_TRACE})
    assert response.status_code == 204
    assert called == []
    client.post("/api/voice/speak", json={"text": "**Steam** is open at C:\\Games\\steam.exe."})
    assert called and "*" not in called[-1] and "\\" not in called[-1]
