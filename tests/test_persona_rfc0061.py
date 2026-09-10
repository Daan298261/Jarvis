from __future__ import annotations

import asyncio
import json

import pytest

from app.api import settings as settings_api
from app.api.voice import voice_speak
from app.config import AppSettings, TtsSettings
from app.inference.backends import normalize_chat_messages
from app.inference.manager import InferenceManager
from app.persona.pack import (
    build_persona_instructions,
    inject_persona_messages,
    load_persona_pack,
    reload_persona_pack,
)
from app.persona.quiet import is_quiet_or_dnd_active, should_speak_chat_reply
from app.providers.base import ChatMessage, ChatResult


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def chat(self, messages, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(content="acknowledged")


def test_persona_pack_loads_default_british_butler_register():
    pack = reload_persona_pack()
    assert pack.id == "jarvis-default-v1"
    assert pack.locale == "en-GB"
    assert "british" in pack.system_prefix.lower()
    assert "Codsworth" in "\n".join(pack.must_not)
    assert pack.tts.speak_chat_replies is True


def test_build_persona_instructions_includes_traits_and_constraints():
    pack = load_persona_pack()
    block = build_persona_instructions(pack)
    assert "Personality traits:" in block
    assert "british_understated" in block
    assert "You must not:" in block
    assert "copyrighted fictional character" in block


def test_inject_persona_messages_places_pack_first():
    messages = [
        ChatMessage(role="system", content="Task-specific guidance."),
        ChatMessage(role="user", content="Hello"),
    ]
    injected = inject_persona_messages(messages)
    assert injected[0].role == "system"
    assert "british" in injected[0].content.lower()
    assert injected[1].role == "system"
    assert injected[1].content == "Task-specific guidance."


def test_normalize_chat_messages_keeps_persona_at_front():
    messages = inject_persona_messages(
        [
            ChatMessage(role="system", content="Operational rules."),
            ChatMessage(role="user", content="Status?"),
        ]
    )
    normalized = normalize_chat_messages(messages)
    assert normalized[0].role == "system"
    assert normalized[0].content.index("british") < normalized[0].content.index("Operational rules.")


@pytest.mark.asyncio
async def test_prepare_chat_messages_injects_persona_for_llama_backend():
    manager = InferenceManager()
    prepared = manager.prepare_chat_messages(
        [
            ChatMessage(role="system", content="Agent loop prompt."),
            ChatMessage(role="user", content="Do the thing."),
        ]
    )
    assert prepared[0].role == "system"
    assert "british" in prepared[0].content.lower()
    assert "Agent loop prompt." in prepared[0].content


@pytest.mark.asyncio
async def test_prepare_chat_messages_injects_persona_for_remote_backend():
    manager = InferenceManager()
    manager.state.backend = "remote-openai-compatible"
    provider = _RecordingProvider()
    manager.provider = provider
    await manager.chat([ChatMessage(role="user", content="Remote request.")], max_tokens=16, thinking=False)
    assert provider.calls
    system_text = provider.calls[0][0].content
    assert isinstance(system_text, str)
    assert "british" in system_text.lower()


def test_tts_settings_default_speak_chat_replies_true():
    settings = AppSettings()
    assert settings.tts.speak_chat_replies is True


def test_settings_round_trip_tts_speak_chat_replies(monkeypatch):
    current = AppSettings()
    saved: list[AppSettings] = []

    monkeypatch.setattr(settings_api, "load_settings", lambda: current)
    monkeypatch.setattr(settings_api, "save_settings", lambda value: saved.append(value.model_copy(deep=True)))
    monkeypatch.setattr(settings_api.REGISTRY, "apply_settings", lambda _value: None)

    result = asyncio.run(
        settings_api.update_settings(settings_api.SettingsUpdate(tts_speak_chat_replies=False))
    )

    assert result["tts"]["speak_chat_replies"] is False
    assert saved
    assert saved[-1].tts.speak_chat_replies is False

    restored = asyncio.run(
        settings_api.update_settings(settings_api.SettingsUpdate(tts_speak_chat_replies=True))
    )
    assert restored["tts"]["speak_chat_replies"] is True


def test_should_speak_chat_reply_respects_setting():
    assert should_speak_chat_reply(AppSettings(tts=TtsSettings(speak_chat_replies=True))) is True
    assert should_speak_chat_reply(AppSettings(tts=TtsSettings(speak_chat_replies=False))) is False


def test_quiet_or_dnd_hook_stub_is_documented_noop():
    assert is_quiet_or_dnd_active() is False


def test_persona_pack_changes_apply_without_model_code_edits(tmp_path, monkeypatch):
    custom = {
        "id": "custom-pack-v2",
        "locale": "en-GB",
        "system_prefix": "Custom persona prefix for tests.",
        "traits": {"register": "test"},
        "must": ["Stay helpful"],
        "must_not": ["Invent facts"],
        "tts": {"voice_profile_id": "test-voice", "speak_chat_replies": True},
    }
    pack_file = tmp_path / "persona_pack.json"
    pack_file.write_text(json.dumps(custom), encoding="utf-8")
    monkeypatch.setattr("app.persona.pack.persona_pack_path", lambda: pack_file)
    reload_persona_pack()
    block = build_persona_instructions()
    assert "Custom persona prefix for tests." in block
    assert "Stay helpful" in block


@pytest.mark.asyncio
async def test_voice_speak_returns_audio_bytes(monkeypatch):
    from app.api.voice import SpeakIn

    async def fake_synthesize(text: str) -> bytes:
        assert text == "Hello there."
        return b"RIFFfake-wav"

    monkeypatch.setattr("app.api.voice.synthesize_speech", fake_synthesize)
    response = await voice_speak(SpeakIn(text="Hello there."))
    assert response.body == b"RIFFfake-wav"
    assert response.media_type == "audio/wav"
