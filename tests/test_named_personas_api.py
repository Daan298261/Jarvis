"""Named persona API: apply flag, default, and pin."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import AppSettings
from app.main import app


@pytest.fixture
def persona_api_env(monkeypatch):
    box = {"settings": AppSettings()}
    monkeypatch.setattr("app.config.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.config.save_settings", lambda updated: box.__setitem__("settings", updated))
    monkeypatch.setattr("app.persona.named_persona.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.persona.named_persona.save_settings", lambda updated: box.__setitem__("settings", updated))
    settings = box["settings"]

    def ok_status(_profile_id: str) -> str:
        return "ok"

    def fake_set(profile_id: str):
        settings.voice.active_profile_id = profile_id
        return type("Item", (), {"id": profile_id})()

    monkeypatch.setattr("app.persona.named_persona.pack_status", ok_status)
    monkeypatch.setattr("app.persona.named_persona.set_active_voice_profile_id", fake_set)
    monkeypatch.setattr("app.voice_profiles.catalog.set_active_voice_profile_id", fake_set)
    return settings


@pytest.mark.asyncio
async def test_appearance_update_does_not_reapply_active(persona_api_env):
    settings: AppSettings = persona_api_env
    settings.named_personas.active_id = "anzu"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/named-personas",
            json={"id": "anzu", "apply": False, "appearance": {"pitch": 2}},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["active"]["id"] == "anzu"
    anzu = next(row for row in body["personas"] if row["id"] == "anzu")
    assert anzu["appearance"]["pitch"] == 2


@pytest.mark.asyncio
async def test_default_and_pin_in_one_request(persona_api_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/named-personas",
            json={"id": "umi", "apply": False, "set_as_default": True, "pin": True},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["default_id"] == "umi"
    assert body["pinned_ids"][0] == "umi"
