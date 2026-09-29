from __future__ import annotations

from app.tts import voicestudio_supervisor as vs


def test_voicestudio_wanted_when_stt_pref(monkeypatch):
    class Voice:
        voicestudio_autostart = False
        stt_backend = "voicestudio"

    class Settings:
        voice = Voice()
        tts = type("T", (), {"engine": "auto"})()

    monkeypatch.setattr(vs, "load_settings", lambda: Settings())
    assert vs._voicestudio_wanted() is True


def test_voicestudio_not_wanted_when_disabled(monkeypatch):
    class Voice:
        voicestudio_autostart = False
        stt_backend = "auto"

    class Settings:
        voice = Voice()
        tts = type("T", (), {"engine": "auto"})()

    monkeypatch.setattr(vs, "load_settings", lambda: Settings())
    assert vs._voicestudio_wanted() is False
