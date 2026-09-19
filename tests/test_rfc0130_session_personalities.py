from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, save_settings
from app.main import app
from app.persona.pack import build_persona_instructions
from app.persona.session_personality import (
    detect_personality_switch_intent,
    get_active_personality_id,
    set_active_personality,
)


@pytest.fixture
def personality_env(jarvis_env, monkeypatch):
    settings: AppSettings = jarvis_env["settings"]
    settings.session_personality.active_id = "default"
    save_settings(settings)
    yield jarvis_env
    settings.session_personality.active_id = "default"
    save_settings(settings)


def test_detect_coding_intent():
    assert detect_personality_switch_intent("Please start a coding session") == "coding"
    assert detect_personality_switch_intent("switch to research mode") == "research"
    assert detect_personality_switch_intent("hello there") is None


def test_set_active_persists(personality_env):
    pack = set_active_personality("coding")
    assert pack.id == "coding"
    assert get_active_personality_id() == "coding"


def test_persona_pack_includes_addendum(personality_env):
    set_active_personality("research")
    text = build_persona_instructions()
    assert "Session mode: research" in text


def test_personality_api_get_and_post(personality_env):
    client = TestClient(app)
    get_res = client.get("/api/personality")
    assert get_res.status_code == 200
    body = get_res.json()
    assert body["active_id"] == "default"
    assert len(body["personalities"]) >= 4

    post_res = client.post("/api/personality", json={"personality_id": "coding"})
    assert post_res.status_code == 200
    assert post_res.json()["active_id"] == "coding"

    settings_res = client.put("/api/settings", json={"session_personality_active_id": "concise"})
    assert settings_res.status_code == 200
    assert settings_res.json()["session_personality"]["active_id"] == "concise"


def test_owner_chat_intent_short_circuit(personality_env):
    from app.persona import owner_chat

    async def _collect():
        events = []
        async for event in owner_chat.stream_owner_chat("start a coding session"):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    kinds = [e.get("type") for e in events]
    assert "done" in kinds
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("personality", {}).get("id") == "coding"
    assert get_active_personality_id() == "coding"
    assert "coding" in (done.get("text") or "").lower()
