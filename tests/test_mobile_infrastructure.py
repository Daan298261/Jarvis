import json

import httpx
import pytest

from app.mobile import infrastructure, store


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "JARVIS_RELAY_URL",
        "JARVIS_RELAY_CREDENTIAL",
        "JARVIS_RELAY_ENDPOINT",
        "JARVIS_PUSH_URL",
        "JARVIS_PUSH_CREDENTIAL",
        "JARVIS_TURN_URL",
        "JARVIS_TURN_SECRET",
        "JARVIS_FIREBASE_CLIENT_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)


def test_readiness_all_false_when_unset(clean_env):
    assert infrastructure.infrastructure_readiness() == {
        "relay_agent_configured": False,
        "relay_endpoint_configured": False,
        "relay_hostname_present": False,
        "push_configured": False,
        "turn_configured": False,
        "firebase_client_config_configured": False,
    }


def test_relay_agent_requires_https_and_credential(clean_env, monkeypatch):
    monkeypatch.setenv("JARVIS_RELAY_URL", "https://relay.example.com")
    assert infrastructure.infrastructure_readiness()["relay_agent_configured"] is False
    monkeypatch.setenv("JARVIS_RELAY_CREDENTIAL", "secret")
    assert infrastructure.infrastructure_readiness()["relay_agent_configured"] is True
    monkeypatch.setenv("JARVIS_RELAY_URL", "http://relay.example.com")
    assert infrastructure.infrastructure_readiness()["relay_agent_configured"] is False


def test_relay_endpoint_and_hostname(clean_env, monkeypatch):
    monkeypatch.setenv("JARVIS_RELAY_ENDPOINT", "https://relay.example.com:15001")
    ready = infrastructure.infrastructure_readiness()
    assert ready["relay_endpoint_configured"] is True
    assert ready["relay_hostname_present"] is True


def test_push_requires_https_and_credential(clean_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PUSH_URL", "https://relay.example.com/v1/push")
    assert infrastructure.infrastructure_readiness()["push_configured"] is False
    monkeypatch.setenv("JARVIS_PUSH_CREDENTIAL", "token")
    assert infrastructure.infrastructure_readiness()["push_configured"] is True
    monkeypatch.setenv("JARVIS_PUSH_URL", "https://relay.example.com/v1/push?x=1")
    assert infrastructure.infrastructure_readiness()["push_configured"] is False


def test_turn_requires_url_and_secret(clean_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TURN_URL", "turn:turn.example.com:3478")
    assert infrastructure.infrastructure_readiness()["turn_configured"] is False
    monkeypatch.setenv("JARVIS_TURN_SECRET", "shared-secret")
    assert infrastructure.infrastructure_readiness()["turn_configured"] is True


def test_firebase_client_config_validates_public_json(tmp_path, clean_env, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"app_id": "1", "api_key": "k", "project_id": "p", "sender_id": "s"}))
    monkeypatch.setenv("JARVIS_FIREBASE_CLIENT_CONFIG", str(path))
    assert infrastructure.infrastructure_readiness()["firebase_client_config_configured"] is True


def test_firebase_rejects_admin_style_or_missing_keys(tmp_path, clean_env, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text('{"type": "service_account"}')
    monkeypatch.setenv("JARVIS_FIREBASE_CLIENT_CONFIG", str(path))
    assert infrastructure.infrastructure_readiness()["firebase_client_config_configured"] is False


@pytest.mark.asyncio
async def test_infrastructure_endpoint_requires_owner_key(clean_env, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    from app.api.companion import owner_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(owner_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 123)),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/api/mobile/manage/infrastructure")
    assert response.status_code in (401, 403)


def test_infrastructure_endpoint_returns_booleans_only(clean_env, monkeypatch):
    from app.api.companion import infrastructure_status

    monkeypatch.setenv("JARVIS_RELAY_URL", "https://relay.example.com")
    monkeypatch.setenv("JARVIS_RELAY_CREDENTIAL", "do-not-leak")
    body = infrastructure_status()
    assert body["relay_agent_configured"] is True
    assert "do-not-leak" not in str(body)
