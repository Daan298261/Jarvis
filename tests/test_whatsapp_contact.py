from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app
from app.mobile import store


@pytest.fixture
def contact_env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        auth_required=True,
        auth_token="jarvis_pk_wa_contact_owner",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    return {"client": TestClient(app), "headers": {"X-Jarvis-Key": settings.auth_token}}


def test_integrations_whatsapp_contact_unavailable(contact_env, monkeypatch):
    class FakeWA:
        def status(self):
            return {"paired": False, "state": "idle"}

    monkeypatch.setattr("app.api.integrations.WHATSAPP_PAIRING", FakeWA())
    response = contact_env["client"].get("/api/integrations/whatsapp/contact", headers=contact_env["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "WhatsApp" in body["reason"]


def test_integrations_whatsapp_contact_available(contact_env, monkeypatch):
    class FakeWA:
        def status(self):
            return {"paired": True, "state": "connected"}

    async def fake_contact():
        return {
            "available": True,
            "display_name": "Jarvis",
            "account_name": "Owner",
            "phone_e164": "+15551234567",
            "phone_digits": "15551234567",
            "chat_id": "15551234567@c.us",
            "wa_me_url": "https://wa.me/15551234567?text=Hi%20Jarvis",
            "note": "Message this chat to talk to Jarvis.",
        }

    monkeypatch.setattr("app.api.integrations.WHATSAPP_PAIRING", FakeWA())
    monkeypatch.setattr("app.integrations.whatsapp_bridge.jarvis_whatsapp_contact", fake_contact)
    response = contact_env["client"].get("/api/integrations/whatsapp/contact", headers=contact_env["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["phone_digits"] == "15551234567"
    assert body["display_name"] == "Jarvis"
