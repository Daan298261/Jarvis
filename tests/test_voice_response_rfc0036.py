from __future__ import annotations

from pathlib import Path

from app.persona.acknowledgements import task_acknowledgement
from app.persona.pack import build_persona_instructions, reload_persona_pack
from app.voice_profiles.schema import VoiceProfileTTS


def test_acknowledgement_is_deterministic_and_not_a_success_claim():
    prompt = "Inspect the service logs and explain why startup is slow"
    first = task_acknowledgement(prompt)
    assert first == task_acknowledgement(prompt)
    assert first
    assert not any(word in first.lower() for word in ("done", "fixed", "completed", "success"))


def test_sensitive_acknowledgement_drops_wit():
    text = task_acknowledgement("Delete the failed payment export")
    assert text in {"On it.", "I'll check that now.", "I'll take a look."}


def test_persona_prioritizes_fast_natural_spoken_answers():
    reload_persona_pack()
    instructions = build_persona_instructions().lower()
    assert "first sentence" in instructions
    assert "one to three spoken sentences" in instructions
    assert "wit only" in instructions
    assert "copyrighted fictional character" in instructions


def test_speaking_rate_is_bounded():
    assert VoiceProfileTTS(speaking_rate=1.08).speaking_rate == 1.08


def test_both_task_surfaces_consume_streamed_tts_events():
    root = Path(__file__).resolve().parents[1]
    hook = (root / "frontend/src/tts/useTaskSpeech.ts").read_text(encoding="utf-8")
    chat = (root / "frontend/src/pages/Chat.tsx").read_text(encoding="utf-8")
    hud = (root / "frontend/src/hud/HudChat.tsx").read_text(encoding="utf-8")
    player = (root / "frontend/src/tts/chatTtsPlayer.ts").read_text(encoding="utf-8")

    assert "new EventSource" in hook
    assert 'event.kind !== "chat_tts"' in hook
    assert "unspokenRemainder" in hook
    assert "useTaskSpeech(" in chat
    assert "useTaskSpeech(" in hud
    assert "append=true" in player
