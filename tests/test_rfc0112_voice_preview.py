from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import HTTPException

from app.voice_profiles.catalog import DEFAULT_VOICE_PROFILE_ID, reload_catalog
from app.workers.voice import SynthesizedSpeech


def _available_profile():
    profile = reload_catalog().get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    return profile.model_copy(update={"available": True})


def _patch_preview_catalog(monkeypatch, profile) -> None:
    class Catalog:
        def get(self, profile_id):
            return profile if profile_id == profile.id else None

        def list_profiles(self, _active_id):
            return [profile]

    monkeypatch.setattr("app.api.voice_profiles.get_catalog", lambda: Catalog())
    monkeypatch.setattr("app.api.voice_profiles.get_active_voice_profile_id", lambda: profile.id)


@pytest.mark.asyncio
async def test_preview_uses_exact_profile_and_returns_identity_headers(monkeypatch):
    from app.api.voice_profiles import preview_voice_profile

    profile = _available_profile()
    _patch_preview_catalog(monkeypatch, profile)
    observed = {}

    async def synthesize(text, *, voice_profile_id=None, exact_profile=False):
        observed.update(
            text=text,
            voice_profile_id=voice_profile_id,
            exact_profile=exact_profile,
        )
        return SynthesizedSpeech(
            audio=b"RIFF" + (b"\0" * 64),
            engine_id="kokoro",
            profile_id=profile.id,
            model_id="kokoro-82m",
            speaker_ref=profile.tts.speaker_ref,
            requested_engine_id="kokoro",
        )

    monkeypatch.setattr("app.api.voice_profiles.synthesize_speech_result", synthesize)

    response = await preview_voice_profile(profile.id)

    assert observed == {
        "text": profile.sample_utterance,
        "voice_profile_id": profile.id,
        "exact_profile": True,
    }
    assert response.media_type == "audio/wav"
    assert response.headers["X-Jarvis-TTS-Engine"] == "kokoro"
    assert response.headers["X-Jarvis-Voice-Profile"] == profile.id
    assert response.headers["X-Jarvis-TTS-Model"] == "kokoro-82m"
    assert response.headers["X-Jarvis-TTS-Voice"] == profile.tts.speaker_ref


@pytest.mark.asyncio
async def test_preview_preserves_synthesis_failure_as_503(monkeypatch):
    from app.api.voice_profiles import preview_voice_profile

    profile = _available_profile()
    _patch_preview_catalog(monkeypatch, profile)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("Kokoro model assets could not be loaded")

    monkeypatch.setattr("app.api.voice_profiles.synthesize_speech_result", fail)

    with pytest.raises(HTTPException) as raised:
        await preview_voice_profile(profile.id)

    assert raised.value.status_code == 503
    assert "Kokoro model assets" in raised.value.detail


@pytest.mark.asyncio
async def test_exact_profile_does_not_try_kokoro_after_chatterbox_failure(monkeypatch):
    from app.tts.synthesize import TtsSynthesisError
    from app.workers import voice

    profile = reload_catalog().get("chatterbox_expressive_en_v1")
    assert profile is not None

    class Catalog:
        def get_available(self, profile_id):
            return profile if profile_id == profile.id else None

    calls = []

    async def synthesize(_text, *, engine_id, **_kwargs):
        calls.append(engine_id)
        if engine_id == "chatterbox":
            raise TtsSynthesisError(engine_id, profile.id, "expressive runtime failed")
        return b"RIFF" + (b"\0" * 64)

    monkeypatch.setattr("app.voice_profiles.catalog.get_catalog", lambda: Catalog())
    monkeypatch.setattr(voice, "synthesize_with_engine", synthesize)

    with pytest.raises(TtsSynthesisError, match="expressive runtime failed"):
        await voice.synthesize_speech_result(
            "Hello",
            voice_profile_id=profile.id,
            exact_profile=True,
        )

    assert calls == ["chatterbox"]


def test_chatterbox_readiness_requires_working_perth_watermarker(monkeypatch):
    from app.tts import engines

    fake_perth = ModuleType("perth")
    fake_perth.PerthImplicitWatermarker = None
    monkeypatch.setitem(sys.modules, "perth", fake_perth)
    monkeypatch.setattr(engines, "_module_available", lambda name: name == "chatterbox")
    assert engines.is_chatterbox_available() is False

    fake_perth.PerthImplicitWatermarker = type("Watermarker", (), {})
    assert engines.is_chatterbox_available() is True


def test_chatterbox_repair_pins_compatible_runtime_and_reloads_perth(monkeypatch):
    from app.tts import pack_install

    calls = []
    fake_perth = ModuleType("perth")
    fake_perth.PerthImplicitWatermarker = None
    monkeypatch.setitem(sys.modules, "perth", fake_perth)
    monkeypatch.setattr(pack_install, "is_chatterbox_available", lambda: "perth" not in sys.modules)
    monkeypatch.setattr(
        pack_install.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or type("Completed", (), {"returncode": 0})(),
    )

    pack_install.ensure_chatterbox_python(force=True)

    assert "setuptools==80.9.0" in calls[0]
    assert "chatterbox-tts==0.1.7" in calls[0]
    assert "perth" not in sys.modules


def test_frontend_preview_preserves_errors_and_playback_failure():
    root = Path(__file__).resolve().parents[1]
    preview = (root / "frontend/src/tts/voiceProfiles.ts").read_text(encoding="utf-8")
    picker = (root / "frontend/src/tts/VoiceProfilePicker.tsx").read_text(encoding="utf-8")

    assert "err.status !== 404 && err.status !== 405" in preview
    assert "audio.onerror = () => reject" in preview
    assert "audio.play().catch(() => reject" in preview
    assert "finally" in preview and "URL.revokeObjectURL(url)" in preview
    assert "Preview is not available for this voice yet." not in picker
    assert "result.error" in picker
