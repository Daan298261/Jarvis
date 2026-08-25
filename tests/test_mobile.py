from fastapi.testclient import TestClient

from app.api.mobile import mobile_snapshot
from app.config import AppSettings
from app.main import app


def test_mobile_snapshot_does_not_include_private_key():
    info = mobile_snapshot()
    blob = str(info).lower()
    assert "jarvis_pk_" not in blob
    assert "auth_token" not in blob
    assert info["client"] == "android-pwa"
    assert info["urls"]["local"].startswith("http://127.0.0.1:")
    assert "/phone" in info["urls"]["phone"]
    assert "install" in info["pairing"]


def test_mobile_endpoint_is_open_when_auth_required(jarvis_env, monkeypatch):
    settings = AppSettings(
        allowed_directories=[str(jarvis_env["tmp"])],
        auth_required=True,
        auth_token="jarvis_pk_mobile_test",
        lan_access=True,
        bind_port=4780,
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    monkeypatch.setattr("app.api.mobile.load_settings", lambda: settings)

    client = TestClient(app)
    res = client.get("/api/mobile")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "Jarvis"
    assert "jarvis_pk_mobile_test" not in str(body)
    assert client.get("/api/tasks").status_code == 401
