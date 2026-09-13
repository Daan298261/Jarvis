import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.systems.self_check import run_self_check


def test_self_check_endpoint_reports_core_and_voice(jarvis_env):
    client = TestClient(app)
    response = client.get("/api/system/self-check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["overall"] in {"ready", "initializing", "degraded", "blocked"}
    ids = [item["id"] for item in body["checks"]]
    assert ids == ["core", "inference", "household_voice", "speech_recognition"]
    assert body["checks"][0]["status"] == "ready"
    assert "working_order" in body
    assert "headline" in body


@pytest.mark.asyncio
async def test_self_check_degrades_voice_when_kokoro_missing(jarvis_env, monkeypatch):
    async def fake_snapshot(_settings):
        return {"loaded": True, "loading": False, "active_model": "stub", "last_error": ""}

    monkeypatch.setattr("app.systems.self_check.MANAGER.snapshot", fake_snapshot)
    monkeypatch.setattr(
        "app.systems.self_check.engine_availability",
        lambda: {"kokoro": False, "kokoro_weights": False, "system": True},
    )
    monkeypatch.setattr("app.systems.self_check.legacy_system_tts_available", lambda: True)
    monkeypatch.setattr("app.systems.self_check.voice_status", lambda: {"stt_ready": True})

    body = await run_self_check()
    voice = next(item for item in body["checks"] if item["id"] == "household_voice")
    assert voice["status"] == "degraded"
    assert body["working_order"] is True
    assert body["overall"] == "degraded"


@pytest.mark.asyncio
async def test_self_check_degrades_partial_kokoro_when_system_tts_exists(jarvis_env, monkeypatch):
    async def fake_snapshot(_settings):
        return {"loaded": True, "loading": False, "active_model": "stub", "last_error": ""}

    monkeypatch.setattr("app.systems.self_check.MANAGER.snapshot", fake_snapshot)
    monkeypatch.setattr(
        "app.systems.self_check.engine_availability",
        lambda: {"kokoro": False, "kokoro_weights": True, "system": True},
    )
    monkeypatch.setattr("app.systems.self_check.legacy_system_tts_available", lambda: True)
    monkeypatch.setattr("app.systems.self_check.voice_status", lambda: {"stt_ready": True})

    body = await run_self_check()
    voice = next(item for item in body["checks"] if item["id"] == "household_voice")
    assert voice["status"] == "degraded"
    assert body["working_order"] is True
    assert body["overall"] == "degraded"


def test_self_check_is_open_when_auth_required(jarvis_env, monkeypatch):
    from app.config import AppSettings

    settings = AppSettings(
        allowed_directories=[str(jarvis_env["tmp"])],
        auth_required=True,
        auth_token="jarvis_pk_secure_key",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    client = TestClient(app)
    assert client.get("/api/system/self-check").status_code == 200
