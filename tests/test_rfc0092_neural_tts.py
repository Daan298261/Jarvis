from __future__ import annotations

import json

import pytest

from app.config import save_settings
from app.tts.engines import engine_chain_for_profile
from app.tts.synthesize import TtsSynthesisError, synthesize_with_engine
from app.voice_profiles.catalog import (
    DEFAULT_VOICE_PROFILE_ID,
    WINDOWS_NATURAL_VOICE_PROFILE_ID,
    get_active_voice_profile_id,
    reload_catalog,
)


@pytest.mark.asyncio
async def test_kokoro_failure_never_silently_returns_system_audio(monkeypatch):
    profile = reload_catalog().get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    system_calls: list[str] = []

    async def fail_kokoro(*_args, **_kwargs):
        raise RuntimeError("warm start failed")

    async def system_synth(text, **_kwargs):
        system_calls.append(text)
        return b"RIFFsystem"

    monkeypatch.setattr("app.tts.synthesize._synthesize_kokoro", fail_kokoro)
    monkeypatch.setattr("app.tts.synthesize._synthesize_system", system_synth)

    with pytest.raises(TtsSynthesisError, match="warm start failed") as raised:
        await synthesize_with_engine("Hello", engine_id="kokoro", profile=profile)

    assert raised.value.engine_id == "kokoro"
    assert raised.value.profile_id == DEFAULT_VOICE_PROFILE_ID
    assert system_calls == []


@pytest.mark.asyncio
async def test_unknown_engine_does_not_silently_return_system_audio(monkeypatch):
    profile = reload_catalog().get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    system_calls: list[str] = []

    async def system_synth(text, **_kwargs):
        system_calls.append(text)
        return b"RIFFsystem"

    monkeypatch.setattr("app.tts.synthesize._synthesize_system", system_synth)

    with pytest.raises(TtsSynthesisError, match="Unknown TTS engine"):
        await synthesize_with_engine("Hello", engine_id="orpheus", profile=profile)

    assert system_calls == []


def test_neural_profile_chains_do_not_include_system_fallback():
    catalog = reload_catalog()
    for profile_id in ("butler_original_v1", "chatterbox_expressive_en_v1"):
        profile = catalog.get(profile_id)
        assert profile is not None
        assert "system" not in engine_chain_for_profile(profile)


@pytest.mark.asyncio
async def test_chatterbox_failure_retries_kokoro_and_reports_actual_engine(monkeypatch):
    from app.workers import voice

    profile = reload_catalog().get("chatterbox_expressive_en_v1")
    assert profile is not None

    class Catalog:
        def get_available(self, profile_id):
            return profile if profile_id == profile.id else None

    calls: list[str] = []

    async def synthesize(_text, *, engine_id, **_kwargs):
        calls.append(engine_id)
        if engine_id == "chatterbox":
            raise TtsSynthesisError(engine_id, profile.id, "model failed")
        return b"RIFFkokoro"

    monkeypatch.setattr("app.voice_profiles.catalog.get_catalog", lambda: Catalog())
    monkeypatch.setattr(voice, "pick_engine_for_profile", lambda _profile: "chatterbox")
    monkeypatch.setattr(voice, "is_engine_available", lambda engine_id: engine_id in {"chatterbox", "kokoro"})
    monkeypatch.setattr(voice, "synthesize_with_engine", synthesize)

    result = await voice.synthesize_speech_result("Hello", voice_profile_id=profile.id)

    assert calls == ["chatterbox", "kokoro"]
    assert result.audio == b"RIFFkokoro"
    assert result.engine_id == "kokoro"
    assert result.profile_id == profile.id


def test_windows_profile_is_explicitly_a_baseline_system_voice():
    profile = reload_catalog().get(WINDOWS_NATURAL_VOICE_PROFILE_ID)
    assert profile is not None
    assert "SAPI" in profile.display_name
    assert profile.tts.quality_tier == "baseline"
    assert profile.tts.resolved_engine_id() == "system"


def test_existing_windows_default_migrates_once_to_kokoro(jarvis_env, monkeypatch):
    settings = jarvis_env["settings"]
    settings.voice.active_profile_id = WINDOWS_NATURAL_VOICE_PROFILE_ID
    save_settings(settings)
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.voice_profiles.catalog.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.voice_profiles.catalog.load_settings", lambda: settings)
    monkeypatch.setattr("app.voice_profiles.catalog.save_settings", lambda _settings: None)

    assert get_active_voice_profile_id() == DEFAULT_VOICE_PROFILE_ID
    marker = jarvis_env["tmp"] / ".migrated_voice_kokoro_default_v1"
    assert marker.is_file()

    settings.voice.active_profile_id = WINDOWS_NATURAL_VOICE_PROFILE_ID
    assert get_active_voice_profile_id() == WINDOWS_NATURAL_VOICE_PROFILE_ID


def test_chatterbox_pack_is_one_click_installable(monkeypatch, tmp_path):
    from app.tts import pack_install

    profile = reload_catalog().get("chatterbox_expressive_en_v1")
    assert profile is not None
    pack_dir = tmp_path / profile.id
    calls: list[bool] = []
    monkeypatch.setattr(pack_install, "_pack_dir", lambda _profile: pack_dir)
    monkeypatch.setattr(pack_install, "ensure_chatterbox_python", lambda *, force=False: calls.append(force))
    monkeypatch.setattr(pack_install, "reload_catalog", lambda: None)

    result = pack_install.install_voice_pack(profile)

    assert result.ok is True
    assert calls == [False]
    manifest = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert manifest["engine_id"] == "chatterbox"
    assert manifest["model_id"] == "chatterbox"
    assert manifest["speaker_ref"] == ""
