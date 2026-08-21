import pytest
from fastapi.testclient import TestClient

from app.auth import generate_private_key, get_effective_private_key, verify_key
from app.config import AppSettings, load_settings, save_settings
from app.main import app


def test_private_key_generation_and_verification(jarvis_env):
    key = generate_private_key()
    assert key.startswith("jarvis_pk_")
    assert verify_key(key, key) is True
    assert verify_key("wrong_key", key) is False


def test_api_requires_private_key_when_configured(jarvis_env, monkeypatch):
    test_key = "jarvis_pk_test1234567890abcdef"
    settings = AppSettings(
        allowed_directories=[str(jarvis_env["tmp"])],
        auth_required=True,
        auth_token=test_key,
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    client = TestClient(app)

    # 1. Without auth -> 401
    res = client.get("/api/tasks")
    assert res.status_code == 401

    # 2. With invalid header -> 401
    res = client.get("/api/tasks", headers={"X-Jarvis-Key": "wrong"})
    assert res.status_code == 401

    # 3. With valid X-Jarvis-Key -> 200
    res = client.get("/api/tasks", headers={"X-Jarvis-Key": test_key})
    assert res.status_code == 200

    # 4. With valid Bearer token -> 200
    res = client.get("/api/tasks", headers={"Authorization": f"Bearer {test_key}"})
    assert res.status_code == 200

    # 5. With valid query param -> 200
    res = client.get(f"/api/tasks?key={test_key}")
    assert res.status_code == 200


def test_health_and_auth_status_open_when_auth_required(jarvis_env, monkeypatch):
    test_key = "jarvis_pk_secure_key"
    settings = AppSettings(
        allowed_directories=[str(jarvis_env["tmp"])],
        auth_required=True,
        auth_token=test_key,
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").status_code == 200
