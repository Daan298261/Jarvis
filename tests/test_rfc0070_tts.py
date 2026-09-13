from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.persona.chat_delivery import enqueue_chat_tts, pending_chat_tts, reset_chat_delivery
from app.tts.engines import engine_chain_for_profile, pick_engine_for_profile, resolve_engine_id
from app.tts.speak_filter import filter_text_for_speech
from app.voice_profiles.catalog import DEFAULT_VOICE_PROFILE_ID, reload_catalog
from app.voice_profiles.schema import VoiceProfile, VoiceProfilePersonaHooks, VoiceProfileTTS


@pytest.fixture(autouse=True)
def _reset_delivery():
    reset_chat_delivery()
    yield
    reset_chat_delivery()


def test_default_butler_profile_uses_kokoro_engine():
    reload_catalog()
    catalog = reload_catalog()
    profile = catalog.get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    assert profile.tts.resolved_engine_id() == "kokoro"
    assert profile.tts.speaker_ref == "bm_daniel"
    assert profile.tts.speaking_rate == pytest.approx(0.96)
    assert (Path("voice_packs/butler_original_v1/pack.json")).is_file()


def test_speak_filter_strips_urls_code_and_plan_boards():
    raw = (
        "Very well, sir.\n"
        "PLAN: do secret things\n"
        "See https://example.com/docs\n"
        "```python\nprint('no')\n```\n"
        "Shall I continue?"
    )
    filtered = filter_text_for_speech(raw, source="owner_chat")
    assert "https://" not in filtered
    assert "print" not in filtered
    assert "PLAN:" not in filtered
    assert "Shall I continue?" in filtered


def test_speak_filter_allows_think_aloud_source():
    line = "One moment while I consult the archives."
    assert filter_text_for_speech(line, source="think_aloud") == line


def test_speak_filter_strips_final_reply_reasoning_and_markdown_residue():
    raw = (
        "Final reply: Very well, sir.\n"
        "Reasoning: I considered three options.\n"
        "See [the docs](https://example.com/x) for detail.\n"
        "WORKING STATE: scratch notes\n"
        "Shall I proceed?"
    )
    filtered = filter_text_for_speech(raw, source="chat")
    assert "Final reply:" not in filtered
    assert "Reasoning:" not in filtered
    assert "https://" not in filtered
    assert "WORKING STATE" not in filtered
    assert "the docs" in filtered
    assert "Shall I proceed?" in filtered


def test_kokoro_is_selectable_before_weights_are_staged(monkeypatch):
    from app.tts.engines import is_kokoro_available

    monkeypatch.setattr("app.tts.engines.kokoro_python_ready", lambda: True)
    assert is_kokoro_available() is True


def test_tts_modules_import_without_circular_import():
    import importlib

    importlib.import_module("app.tts.synthesize")
    importlib.import_module("app.workers.voice")


def test_speak_filter_strips_bold_weather_for_owner_chat():
    raw = "Today: **18** to **11** degrees, partly cloudy."
    filtered = filter_text_for_speech(raw, source="owner_chat", user_prompt="weather?")
    assert "**" not in filtered
    assert "eighteen" in filtered
    assert "eleven" in filtered


def test_enqueue_chat_tts_skips_non_speakable_content():
    item_id = enqueue_chat_tts("PLAN: hidden\nhttps://x.test", source="task_chat")
    assert item_id == ""
    assert pending_chat_tts() == []


def test_engine_chain_prefers_chatterbox_then_kokoro():
    profile = VoiceProfile(
        id="chatterbox_expressive_en_v1",
        archetype="british_butler",
        display_name="Household butler (expressive)",
        license="original",
        tts=VoiceProfileTTS(engine_id="chatterbox", engine_hint="chatterbox"),
        persona_hooks=VoiceProfilePersonaHooks(),
    )
    chain = engine_chain_for_profile(profile)
    assert chain[:2] == ["chatterbox", "kokoro"]


def test_resolve_engine_id_alias():
    tts = VoiceProfileTTS(engine_hint="kokoro")
    assert resolve_engine_id(tts) == "kokoro"


def test_one_click_install_unlocks_stub_profile(jarvis_env, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.tts.pack_install.ensure_kokoro_runtime", lambda **_: tmp_path / "models" / "tts" / "kokoro-82m")
    monkeypatch.setattr("app.tts.pack_install.ensure_kokoro_weights", lambda **_: tmp_path / "models" / "tts" / "kokoro-82m")
    monkeypatch.setattr(
        "app.tts.engines.is_kokoro_available",
        lambda **_: True,
    )
    monkeypatch.setattr(
        "app.tts.engines.is_engine_available",
        lambda engine_id: engine_id in {"kokoro", "system"},
    )
    reload_catalog()
    client = TestClient(app)
    before = client.get("/api/voice-profiles").json()
    stub = next(item for item in before["profiles"] if item["id"] == "tactical_aide_original_v1")
    assert stub["available"] is False

    installed = client.post("/api/voice-profiles/tactical_aide_original_v1/install")
    assert installed.status_code == 200
    assert installed.json()["installed"] is True

    after = client.get("/api/voice-profiles").json()
    unlocked = next(item for item in after["profiles"] if item["id"] == "tactical_aide_original_v1")
    assert unlocked["available"] is True
    manifest = Path("voice_packs/tactical_aide_original_v1/pack.json")
    assert manifest.is_file()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["engine_id"] == "kokoro"
    try:
        manifest.unlink(missing_ok=True)
    finally:
        reload_catalog()


@pytest.mark.asyncio
async def test_synthesize_routes_through_picked_engine(monkeypatch):
    from app.workers import voice as voice_worker

    reload_catalog()
    catalog = reload_catalog()
    profile = catalog.get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None

    async def fake_synth(text, *, engine_id, profile=None, speaker_ref="", model_dir=None):
        assert engine_id == "kokoro"
        assert speaker_ref == "bm_daniel"
        return b"RIFF"

    monkeypatch.setattr("app.workers.voice.pick_engine_for_profile", lambda _p: "kokoro")
    monkeypatch.setattr(voice_worker, "synthesize_with_engine", fake_synth)

    wav = await voice_worker.synthesize_speech("Hello")
    assert wav == b"RIFF"


@pytest.mark.asyncio
async def test_kokoro_receives_profile_speaking_rate(monkeypatch):
    import numpy as np

    from app.tts.synthesize import synthesize_with_engine

    reload_catalog()
    profile = reload_catalog().get(DEFAULT_VOICE_PROFILE_ID)
    assert profile is not None
    observed: dict[str, float] = {}

    class FakePipeline:
        def __call__(self, text, *, voice, speed):
            assert text == "Ready when you are."
            assert voice == "bm_daniel"
            observed["speed"] = speed
            yield None, None, np.zeros(16, dtype=np.float32)

    monkeypatch.setattr("app.tts.synthesize.kokoro_python_ready", lambda: True)
    monkeypatch.setattr("app.tts.synthesize.kokoro_weights_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.tts.synthesize.get_kokoro_pipeline", lambda *_: FakePipeline())

    wav = await synthesize_with_engine(
        "Ready when you are.",
        engine_id="kokoro",
        profile=profile,
    )

    assert observed["speed"] == pytest.approx(0.96)
    assert wav.startswith(b"RIFF")


def test_ensure_kokoro_python_skips_pip_when_ready(monkeypatch):
    from app.tts import pack_install

    calls: list[list[str]] = []
    monkeypatch.setattr(pack_install, "kokoro_python_ready", lambda: True)
    monkeypatch.setattr(
        pack_install.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(list(args[0])) or type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})(),
    )
    pack_install.ensure_kokoro_python()
    assert calls == []


def test_ensure_kokoro_python_installs_without_user_facing_pip(monkeypatch):
    from app.tts import pack_install

    monkeypatch.setattr(pack_install, "kokoro_python_ready", lambda: False)
    observed: dict[str, list[str]] = {}

    class Result:
        returncode = 0
        stderr = ""
        stdout = "ok"

    def fake_run(command, **kwargs):
        observed["command"] = list(command)
        return Result()

    monkeypatch.setattr(pack_install.subprocess, "run", fake_run)
    ready = {"n": 0}

    def after_install():
        ready["n"] += 1
        return ready["n"] > 1

    monkeypatch.setattr(pack_install, "kokoro_python_ready", after_install)
    pack_install.ensure_kokoro_python()
    assert "pip" in observed["command"]
    assert "kokoro>=0.9.2" in observed["command"]
    assert pack_install.KOKORO_RUNTIME_ERROR.lower().find("pip") == -1


def test_ensure_kokoro_runtime_prepares_python_and_weights(monkeypatch, tmp_path):
    from app.tts import pack_install

    steps: list[str] = []
    monkeypatch.setattr(pack_install, "ensure_kokoro_python", lambda **_: steps.append("python"))
    monkeypatch.setattr(pack_install, "ensure_kokoro_weights", lambda **_: steps.append("weights") or tmp_path)
    assert pack_install.ensure_kokoro_runtime() == tmp_path
    assert steps == ["python", "weights"]
