"""One speech path: every model lane uses the active persona's neural voice."""

from __future__ import annotations

import pytest

from app.config import AppSettings, PersonaAppearanceSettings
from app.persona.chat_delivery import enqueue_chat_tts, pending_chat_tts, reset_chat_delivery
from app.tts.persona_speech import (
    SpeechRefused,
    chatterbox_speech_blocked,
    recent_speech_trace,
    reset_speech_trace,
    resolve_speaking_voice,
    speak_text,
    speech_lane_for_model,
)
from app.tts.synthesize import TtsSynthesisError
from app.workers.voice import SynthesizedSpeech


def _settings(
    *,
    active: str = "mestor",
    activated: str = "tactical_aide_original_v1",
    profiles: dict | None = None,
) -> AppSettings:
    settings = AppSettings()
    settings.named_personas.active_id = active
    settings.named_personas.activated_voice_profile_id = activated
    if profiles:
        settings.named_personas.profiles = profiles
    return settings


def _bind(monkeypatch, settings: AppSettings) -> None:
    monkeypatch.setattr("app.tts.persona_speech.load_settings", lambda: settings)


@pytest.fixture
def persona_voice(monkeypatch):
    settings = _settings()
    _bind(monkeypatch, settings)
    reset_speech_trace()
    reset_chat_delivery()
    yield settings
    reset_speech_trace()
    reset_chat_delivery()


def test_lane_label_does_not_invent_a_voice(persona_voice):
    assert speech_lane_for_model("front", "Qwen3.5-2B") == "front"
    assert speech_lane_for_model("worker", "Qwen3.5-27B") == "worker"
    assert speech_lane_for_model("worker", "laya-multilingual") == "laya"
    assert speech_lane_for_model("specialist", "enki-coder") == "specialist"
    assert speech_lane_for_model("worker", "expert") == "worker"


def test_every_lane_resolves_the_active_persona_voice(persona_voice):
    seen = []
    for lane, model, speaker in (
        ("front", "Qwen3.5-2B", None),
        ("worker", "Qwen3.5-27B", None),
        ("laya", "laya-multilingual", None),
        ("specialist", "expert-27b", "enki"),
    ):
        voice = resolve_speaking_voice(lane=lane, model=model, speaker_persona_id=speaker)
        seen.append(voice)
        assert voice.refused is False
        assert voice.persona_id == "mestor"
        assert voice.profile_id == "tactical_aide_original_v1"
        assert voice.engine_id == "kokoro"
        assert voice.profile_id != "windows_natural_en_v1"
    assert {item.lane for item in seen} == {"front", "worker", "laya", "specialist"}
    paths = {item["path"] for item in recent_speech_trace()}
    assert paths == {"persona_speech.resolve_speaking_voice"}


@pytest.mark.asyncio
async def test_speak_text_is_the_only_synthesis_entry(persona_voice, monkeypatch):
    calls: list[dict] = []

    async def synthesize(
        text,
        *,
        voice_profile_id=None,
        blocked_engines=None,
        playback=None,
        exact_profile=False,
        allow_neural_fallback=False,
    ):
        calls.append(
            {
                "text": text,
                "voice_profile_id": voice_profile_id,
                "blocked": tuple(blocked_engines or ()),
                "playback": playback,
                "exact_profile": exact_profile,
                "allow_neural_fallback": allow_neural_fallback,
            }
        )
        return SynthesizedSpeech(b"RIFFpersona", "kokoro", voice_profile_id or "", requested_engine_id="kokoro")

    def boom(*_args, **_kwargs):
        raise AssertionError("speech must not health-probe or install packages")

    monkeypatch.setattr("app.tts.persona_speech.synthesize_speech_result", synthesize)
    monkeypatch.setattr("app.tts.kokoro_adapter.verify_kokoro_runtime", boom)
    monkeypatch.setattr("app.tts.pack_install.ensure_kokoro_python", boom)
    monkeypatch.setattr("app.tts.pack_install.ensure_chatterbox_python", boom)

    for lane, model in (
        ("front", "Qwen3.5-2B"),
        ("worker", "Qwen3.5-27B"),
        ("laya", "laya-multilingual"),
        ("specialist", "Qwen3.5-27B"),
    ):
        result = await speak_text("Good evening.", lane=lane, model=model, speaker_persona_id="enki")
        assert result.audio == b"RIFFpersona"
        assert result.profile_id == "tactical_aide_original_v1"

    assert len(calls) == 4
    assert {call["voice_profile_id"] for call in calls} == {"tactical_aide_original_v1"}
    assert all(call["allow_neural_fallback"] is True for call in calls)
    assert all(call["playback"][0] == pytest.approx(0.96) for call in calls)
    spoken = [item for item in recent_speech_trace() if item["path"] == "persona_speech.speak_text"]
    assert [item["lane"] for item in spoken] == ["front", "worker", "laya", "specialist"]
    assert {item["persona_id"] for item in spoken} == {"mestor"}


def test_enqueue_stamps_the_persona_voice_for_each_lane(persona_voice):
    for lane in ("front", "worker", "laya", "specialist"):
        item_id = enqueue_chat_tts(
            "Good evening, sir.",
            source="owner_chat",
            user_prompt="hello",
            lane=lane,
            model="Qwen3.5-27B" if lane == "worker" else "laya-multilingual" if lane == "laya" else "",
            speaker_persona_id="enki",
        )
        assert item_id
    pending = pending_chat_tts()
    assert [item["lane"] for item in pending] == ["front", "worker", "laya", "specialist"]
    assert {item["persona_id"] for item in pending} == {"mestor"}
    assert {item["voice_profile_id"] for item in pending} == {"tactical_aide_original_v1"}


def test_windows_natural_is_never_the_persona_voice(persona_voice, monkeypatch):
    poisoned = _settings(active="anzu", activated="windows_natural_en_v1")
    _bind(monkeypatch, poisoned)
    voice = resolve_speaking_voice(lane="worker", model="Qwen3.5-27B")
    assert voice.refused is False
    assert voice.persona_id == "anzu"
    assert voice.profile_id == "butler_original_v1"
    assert voice.engine_id == "kokoro"


def test_specialist_auto_speak_false_keeps_the_main_voice(persona_voice):
    persona_voice.named_personas.profiles["enki"] = PersonaAppearanceSettings(specialists_auto_speak=False)
    voice = resolve_speaking_voice(lane="specialist", speaker_persona_id="enki", model="enki-coder")
    assert voice.persona_id == "mestor"
    assert voice.profile_id == "tactical_aide_original_v1"


def test_specialist_auto_speak_uses_that_personas_pack(persona_voice, monkeypatch):
    persona_voice.named_personas.profiles["enki"] = PersonaAppearanceSettings(
        specialists_auto_speak=True,
        speaking_rate=1.06,
        pitch=1,
    )
    monkeypatch.setattr("app.persona.named_persona.pack_status", lambda profile_id: "ok")
    voice = resolve_speaking_voice(lane="specialist", speaker_persona_id="enki")
    assert voice.refused is False
    assert voice.persona_id == "enki"
    assert voice.profile_id == "synthetic_command_original_v1"
    assert voice.playback[0] == pytest.approx(1.06)
    assert voice.playback[1] == pytest.approx(1)


def test_specialist_missing_pack_is_not_spoken(persona_voice, monkeypatch):
    persona_voice.named_personas.profiles["aegir"] = PersonaAppearanceSettings(specialists_auto_speak=True)
    monkeypatch.setattr(
        "app.persona.named_persona.pack_status",
        lambda profile_id: "tts_unavailable" if "chatterbox" in profile_id else "ok",
    )
    voice = resolve_speaking_voice(lane="specialist", speaker_persona_id="aegir")
    assert voice.refused is True
    assert voice.profile_id != "windows_natural_en_v1"
    assert enqueue_chat_tts("On air.", source="task_chat", lane="specialist", speaker_persona_id="aegir") == ""
    assert pending_chat_tts() == []


@pytest.mark.asyncio
async def test_neural_request_never_yields_sapi(persona_voice, monkeypatch):
    from app.workers import voice

    system_calls: list[str] = []

    async def synthesize(_text, *, engine_id, profile=None, speaker_ref="", model_dir=None, playback=None):
        if engine_id in {"system", "sapi", "windows"}:
            system_calls.append(engine_id)
            return b"RIFFsapi"
        raise TtsSynthesisError(engine_id, "tactical_aide_original_v1", "neural down")

    monkeypatch.setattr(voice, "pick_engine_for_profile", lambda _profile: "kokoro")
    monkeypatch.setattr(voice, "is_engine_available", lambda engine_id: engine_id == "kokoro")
    monkeypatch.setattr(voice, "synthesize_with_engine", synthesize)

    with pytest.raises(TtsSynthesisError):
        await speak_text("Good evening.", lane="front", model="Qwen3.5-2B")
    assert system_calls == []


@pytest.mark.asyncio
async def test_chatterbox_vram_miss_falls_back_without_loading_it(monkeypatch):
    from app.workers import voice

    settings = _settings(active="aegir", activated="chatterbox_expressive_en_v1")
    _bind(monkeypatch, settings)
    loaded: list[str] = []
    calls: list[str] = []

    def refuse_load(device):
        loaded.append(device)
        raise AssertionError("Chatterbox must not load when VRAM is tight")

    async def synthesize(_text, *, engine_id, profile=None, speaker_ref="", model_dir=None, playback=None):
        calls.append(engine_id)
        assert engine_id == "kokoro"
        return b"RIFFkokoro"

    monkeypatch.setattr("app.tts.persona_speech.chatterbox_speech_blocked", lambda: (True, "vram_tight:free_mib=128"))
    monkeypatch.setattr(voice, "pick_engine_for_profile", lambda _profile: "chatterbox")
    monkeypatch.setattr(voice, "is_engine_available", lambda engine_id: engine_id in {"chatterbox", "kokoro"})
    monkeypatch.setattr(voice, "synthesize_with_engine", synthesize)
    monkeypatch.setattr("app.tts.synthesize._cached_chatterbox_model", refuse_load)
    monkeypatch.setattr("app.tts.synthesize._load_chatterbox_model", refuse_load)

    result = await speak_text("On air.", lane="worker", model="Qwen3.5-27B")
    assert result.engine_id == "kokoro"
    assert result.profile_id == "chatterbox_expressive_en_v1"
    assert calls == ["kokoro"]
    assert loaded == []
    spoken = [item for item in recent_speech_trace() if item["path"] == "persona_speech.speak_text"]
    assert spoken[-1]["persona_id"] == "aegir"
    assert spoken[-1]["actual_engine"] == "kokoro"


@pytest.mark.asyncio
async def test_speak_text_refuses_a_missing_specialist_pack(persona_voice, monkeypatch):
    persona_voice.named_personas.profiles["maia"] = PersonaAppearanceSettings(specialists_auto_speak=True)
    monkeypatch.setattr("app.persona.named_persona.pack_status", lambda _profile_id: "install_required")
    with pytest.raises(SpeechRefused):
        await speak_text("Hello.", lane="specialist", speaker_persona_id="maia", model="maia-copy")


def test_vram_probe_failure_blocks_chatterbox_rather_than_guessing(monkeypatch):
    def broken():
        raise RuntimeError("no nvidia")

    monkeypatch.setattr("app.hardware.detect_hardware", broken)
    blocked, reason = chatterbox_speech_blocked()
    assert blocked is True
    assert "vram_probe_failed" in reason
