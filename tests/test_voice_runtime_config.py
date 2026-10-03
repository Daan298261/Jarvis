from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppSettings, VoiceSettings, save_settings
from app.tts.voice_runtime_config import resolved_faster_whisper_model, voicestudio_base_url


def test_voicestudio_base_url_reads_settings(jarvis_env, monkeypatch):
    monkeypatch.delenv("JARVIS_VOICESTUDIO_URL", raising=False)
    monkeypatch.delenv("VOICESTUDIO_URL", raising=False)
    settings: AppSettings = jarvis_env["settings"]
    settings.voice = VoiceSettings(voicestudio_url="http://127.0.0.1:3999")
    save_settings(settings)
    assert voicestudio_base_url() == "http://127.0.0.1:3999"


def test_resolved_faster_whisper_model_uses_marker(jarvis_env, monkeypatch):
    monkeypatch.delenv("JARVIS_WHISPER_MODEL", raising=False)
    settings: AppSettings = jarvis_env["settings"]
    settings.voice = VoiceSettings(whisper_model="")
    save_settings(settings)
    tmp: Path = jarvis_env["tmp"]
    whisper_root = tmp / "models" / "whisper"
    base_dir = whisper_root / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "config.json").write_text("{}", encoding="utf-8")
    marker = whisper_root / ".jarvis_faster_whisper_dir"
    marker.write_text(str(base_dir), encoding="utf-8")
    monkeypatch.setattr("app.config.models_dir", lambda: tmp / "models")
    assert resolved_faster_whisper_model() == str(base_dir)


def test_resolved_faster_whisper_model_prefers_settings_path(jarvis_env, monkeypatch):
    monkeypatch.delenv("JARVIS_WHISPER_MODEL", raising=False)
    tmp: Path = jarvis_env["tmp"]
    custom = tmp / "custom-whisper"
    custom.mkdir()
    settings: AppSettings = jarvis_env["settings"]
    settings.voice = VoiceSettings(whisper_model=str(custom))
    save_settings(settings)
    assert resolved_faster_whisper_model() == str(custom)
