from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app
from app.mobile import apk_delivery, store


@pytest.fixture
def apk_env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    (tmp_path / "mobile" / "builds").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        auth_required=True,
        auth_token="jarvis_pk_apk_send_owner",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    job_id = "11111111-1111-1111-1111-111111111111"
    apk = tmp_path / "mobile" / "builds" / "JarvisCompanion.apk"
    apk.write_bytes(b"apk-bytes")
    with store.database() as db:
        store.put(
            db,
            "build",
            job_id,
            {
                "id": job_id,
                "state": "completed",
                "activity": "Signed APK ready",
                "result": {"filename": "JarvisCompanion.apk", "sha256": "abc"},
                "started_at": 1,
                "updated_at": 1,
                "heartbeat_at": 1,
                "stale": False,
            },
        )
    return {
        "client": TestClient(app),
        "headers": {"X-Jarvis-Key": settings.auth_token},
        "job_id": job_id,
    }


def test_send_email_requires_gmail(apk_env, monkeypatch):
    monkeypatch.setattr(apk_delivery, "email_status", lambda: {"configured": False, "email": "", "full_name": ""})
    response = apk_env["client"].post(
        f"/api/mobile/manage/builds/{apk_env['job_id']}/send/email",
        headers=apk_env["headers"],
        json={},
    )
    assert response.status_code == 400
    assert "Gmail" in response.json()["detail"]


def test_send_email_success(apk_env, monkeypatch, tmp_path):
    config = tmp_path / "email.toml"
    config.write_text(
        """
[[accounts]]
email = "owner@example.com"
full_name = "Owner"
password = "abcdefghijklmnop"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        apk_delivery,
        "email_status",
        lambda: {"configured": True, "email": "owner@example.com", "full_name": "Owner"},
    )
    monkeypatch.setattr(apk_delivery, "email_config_path", lambda: config)

    sent: dict = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, email, password):
            sent["login"] = (email, password)

        def send_message(self, message):
            sent["to"] = message["To"]
            attachments = list(message.iter_attachments())
            sent["attachments"] = len(attachments)
            sent["payload"] = attachments[0].get_content() if attachments else b""

    monkeypatch.setattr(apk_delivery.smtplib, "SMTP_SSL", FakeSMTP)

    response = apk_env["client"].post(
        f"/api/mobile/manage/builds/{apk_env['job_id']}/send/email",
        headers=apk_env["headers"],
        json={"to": "phone@example.com"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["channel"] == "email"
    assert body["to"] == "phone@example.com"
    assert sent["login"][0] == "owner@example.com"
    assert sent["to"] == "phone@example.com"
    assert sent["attachments"] == 1
    assert sent["payload"] == b"apk-bytes"


def test_send_whatsapp_requires_pairing(apk_env, monkeypatch):
    class FakeWA:
        def status(self):
            return {"paired": False, "state": "idle"}

    monkeypatch.setattr(apk_delivery, "WHATSAPP_PAIRING", FakeWA())
    response = apk_env["client"].post(
        f"/api/mobile/manage/builds/{apk_env['job_id']}/send/whatsapp",
        headers=apk_env["headers"],
        json={},
    )
    assert response.status_code == 400
    assert "WhatsApp" in response.json()["detail"]


def test_send_whatsapp_not_implemented_when_paired(apk_env, monkeypatch):
    class FakeWA:
        def status(self):
            return {"paired": True, "state": "connected"}

    monkeypatch.setattr(apk_delivery, "WHATSAPP_PAIRING", FakeWA())
    response = apk_env["client"].post(
        f"/api/mobile/manage/builds/{apk_env['job_id']}/send/whatsapp",
        headers=apk_env["headers"],
        json={},
    )
    assert response.status_code == 501
    assert "Download to Desktop" in response.json()["detail"]
