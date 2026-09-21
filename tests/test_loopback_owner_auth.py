from app.auth import is_local_owner_host
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app


def test_loopback_aliases():
    assert is_local_owner_host("127.0.0.1")
    assert is_local_owner_host("::1")
    assert is_local_owner_host("localhost")
    assert is_local_owner_host("::ffff:127.0.0.1")
    assert not is_local_owner_host("192.168.1.20")
    assert not is_local_owner_host("testclient")


def _auth_settings(tmp):
    return AppSettings(
        allowed_directories=[str(tmp)],
        auth_required=True,
        lan_access=True,
        auth_token="jarvis_pk_loopback_test_key",
    )


@pytest.mark.asyncio
async def test_loopback_owner_can_read_catalog_without_key(jarvis_env, monkeypatch, tmp_path):
    settings = _auth_settings(tmp_path)
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        res = await client.get("/api/modules/catalog/cybersecurity")
        assert res.status_code == 200
        module = res.json().get("module") or res.json()
        assert module["id"] == "cybersecurity"
        model = await client.get("/api/model")
        assert model.status_code == 200


def test_non_loopback_still_requires_key(jarvis_env, monkeypatch, tmp_path):
    settings = _auth_settings(tmp_path)
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    client = TestClient(app)
    denied = client.get("/api/modules/catalog/cybersecurity")
    assert denied.status_code == 401
    allowed = client.get(
        "/api/modules/catalog/cybersecurity",
        headers={"X-Jarvis-Key": "jarvis_pk_loopback_test_key"},
    )
    assert allowed.status_code == 200
