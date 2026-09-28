from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppSettings, load_settings, save_settings
from app.tts.engines import (
    engine_availability,
    engine_chain_for_profile,
    is_engine_available,
    primary_tts_backend,
    resolve_engine_id,
)
from app.tts.pocket_tts_adapter import (
    PocketTtsAdapter,
    is_pocket_tts_available,
    pocket_tts_adapter,
    pocket_tts_runtime_state,
)
from app.tts.synthesize import synthesize_with_engine
from app.tts.voicestudio_adapter import (
    VoiceStudioAdapter,
    is_voicestudio_available,
    voicestudio_adapter,
    voicestudio_probe_endpoint,
    voicestudio_runtime_state,
)
from app.voice_profiles.catalog import reload_catalog
from app.workers.voice import stt_backend, stt_install_hint, voice_status


def test_voicestudio_adapter_availability_and_state(monkeypatch):
    monkeypatch.setattr("app.tts.voicestudio_adapter.voicestudio_probe_endpoint", lambda timeout=2.0: False)
    assert is_voicestudio_available() is False
    state = voicestudio_runtime_state()
    assert state.engine_id == "voicestudio"
    assert state.ready is False

    monkeypatch.setattr("app.tts.voicestudio_adapter.voicestudio_probe_endpoint", lambda timeout=2.0: True)
    assert is_voicestudio_available() is True


def test_voicestudio_adapter_synthesize(monkeypatch):
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")

    fake_wav = b"RIFF" + (b"\0" * 40)

    class FakeResponse:
        status = 200

        def read(self):
            return fake_wav

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=30.0: FakeResponse(),
    )

    audio = adapter.synthesize("Hello world", voice="test_voice", speed=1.0)
    assert audio == fake_wav


def test_voicestudio_adapter_transcribe(monkeypatch):
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")

    class FakeResponse:
        status = 200

        def read(self):
            return json.dumps({"text": "Jarvis online"}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=60.0: FakeResponse(),
    )

    text = adapter.transcribe(b"RIFF\0\0\0\0")
    assert text == "Jarvis online"


def test_pocket_tts_adapter_state_and_availability(monkeypatch):
    monkeypatch.setattr("app.tts.pocket_tts_adapter.pocket_tts_package_ready", lambda: False)
    assert is_pocket_tts_available() is False
    state = pocket_tts_adapter.reset()
    assert state.engine_id == "pocket_tts"
    assert state.ready is False

    monkeypatch.setattr("app.tts.pocket_tts_adapter.pocket_tts_package_ready", lambda: True)
    assert is_pocket_tts_available() is True


def test_engines_recognize_voicestudio_and_pocket_tts(monkeypatch):
    monkeypatch.setattr("app.tts.engines.is_voicestudio_available", lambda: True)
    monkeypatch.setattr("app.tts.engines.is_pocket_tts_available", lambda: True)

    assert is_engine_available("voicestudio") is True
    assert is_engine_available("voice_studio") is True
    assert is_engine_available("pocket_tts") is True
    assert is_engine_available("pocket-tts") is True

    avail = engine_availability()
    assert "voicestudio" in avail
    assert "pocket_tts" in avail
    assert avail["voicestudio"] is True
    assert avail["pocket_tts"] is True


def test_stt_backend_selection(monkeypatch, jarvis_env):
    monkeypatch.setattr("app.workers.voice.is_voicestudio_available", lambda: True)
    monkeypatch.setenv("JARVIS_STT_BACKEND", "voicestudio")
    assert stt_backend() == "voicestudio"
    assert "VoiceStudio" in stt_install_hint("voicestudio")

    monkeypatch.setenv("JARVIS_STT_BACKEND", "faster-whisper")
    monkeypatch.setattr("app.workers.voice._module_available", lambda name: name == "faster_whisper")
    assert stt_backend() == "faster-whisper"


def test_voice_profiles_include_new_alternatives():
    reload_catalog()
    catalog = reload_catalog()
    vs_profile = catalog.get("voicestudio_clone_en_v1")
    assert vs_profile is not None
    assert vs_profile.tts.resolved_engine_id() == "voicestudio"

    pt_profile = catalog.get("pocket_tts_alba_en_v1")
    assert pt_profile is not None
    assert pt_profile.tts.resolved_engine_id() == "pocket_tts"
