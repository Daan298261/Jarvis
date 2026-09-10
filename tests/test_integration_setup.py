from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import AppSettings
from app.integrations import setup as integration


def test_gmail_input_normalizes_app_password_without_exposing_it():
    result = integration.normalize_gmail_input(
        " personal ",
        " User@Gmail.com ",
        " Daan van Essen ",
        "abcd efgh ijkl mnop",
    )
    assert result == {
        "account_name": "personal",
        "email": "user@gmail.com",
        "full_name": "Daan van Essen",
        "app_password": "abcdefghijklmnop",
    }

    with pytest.raises(integration.IntegrationSetupError, match="16-character"):
        integration.normalize_gmail_input("personal", "user@gmail.com", "User", "too-short")


async def test_configure_gmail_tests_then_persists_and_redacts(monkeypatch):
    calls: list[object] = []

    def fake_test(email: str, password: str) -> None:
        calls.append(("test", email, password))

    async def fake_persist(account: dict[str, str]) -> None:
        calls.append(("persist", dict(account)))

    monkeypatch.setattr(integration, "_test_gmail_connections", fake_test)
    monkeypatch.setattr(integration, "_persist_email_account", fake_persist)
    monkeypatch.setattr(integration, "ensure_mcp_preset", lambda preset: calls.append(("preset", preset)))

    result = await integration.configure_gmail(
        "personal", "user@gmail.com", "User Name", "abcd efgh ijkl mnop"
    )

    assert result == {"configured": True, "email": "user@gmail.com", "full_name": "User Name"}
    assert "app_password" not in result
    assert calls[0] == ("test", "user@gmail.com", "abcdefghijklmnop")
    assert calls[-1] == ("preset", "email")


async def test_email_config_persistence_is_atomic(tmp_path, monkeypatch):
    root = tmp_path / "jarvis"
    helper = root / "mcp" / "email-config.mjs"
    connector = root / "mcp" / "node_modules" / "@codefuturist" / "email-mcp"
    helper.parent.mkdir(parents=True)
    connector.mkdir(parents=True)
    helper.write_text("// test helper", encoding="utf-8")
    final = tmp_path / "profile" / "config.toml"

    class FakeEmailProcess:
        returncode = 0

        async def communicate(self, payload: bytes):
            import json

            parsed = json.loads(payload)
            Path(parsed["tempPath"]).write_text("saved", encoding="utf-8")
            return b"ok", b""

    async def fake_create(*_args, **_kwargs):
        return FakeEmailProcess()

    monkeypatch.setattr(integration, "repo_root", lambda: root)
    monkeypatch.setattr(integration, "email_config_path", lambda: final)
    monkeypatch.setattr(integration, "_node_executable", lambda: "node")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    await integration._persist_email_account(
        {
            "account_name": "personal",
            "email": "user@gmail.com",
            "full_name": "User Name",
            "app_password": "abcdefghijklmnop",
        }
    )

    assert final.read_text(encoding="utf-8") == "saved"
    assert list(final.parent.glob("*.tmp")) == []


def test_email_status_never_returns_password(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[[accounts]]
name = "personal"
email = "user@gmail.com"
full_name = "User Name"
password = "secret-app-password"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(integration, "email_config_path", lambda: config)

    result = integration.email_status()
    assert result == {"configured": True, "email": "user@gmail.com", "full_name": "User Name"}
    assert "secret" not in str(result)


def test_mcp_presets_are_enabled_without_duplicates(monkeypatch):
    settings = AppSettings(
        mcp_servers=[
            {
                "id": "existing-email",
                "name": "email",
                "transport": "stdio",
                "command": "old",
                "args": [],
                "enabled": False,
            }
        ]
    )
    saved: list[AppSettings] = []
    monkeypatch.setattr(integration, "load_settings", lambda: settings)
    monkeypatch.setattr(integration, "save_settings", lambda value: saved.append(value))

    integration.ensure_mcp_preset("email")
    integration.ensure_mcp_preset("email")

    assert len(settings.mcp_servers) == 1
    assert settings.mcp_servers[0]["id"] == "existing-email"
    assert settings.mcp_servers[0]["enabled"] is True
    assert settings.mcp_servers[0]["args"][-2:] == ["email-mcp", "stdio"]
    assert len(saved) == 2


class FakeProcess:
    def __init__(self, lines: list[bytes], returncode: int = 0):
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(line)
        self.stdout.feed_eof()
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


async def test_whatsapp_pairing_state_and_marker(tmp_path, monkeypatch):
    manager = integration.WhatsAppPairingManager()
    marker = tmp_path / "jarvis-paired.json"
    enabled: list[str] = []
    monkeypatch.setattr(manager, "_paired_marker", lambda: marker)
    monkeypatch.setattr(integration, "ensure_mcp_preset", lambda preset: enabled.append(preset))
    process = FakeProcess(
        [
            b'{"state":"starting"}\n',
            b'{"state":"pairing","qr":"temporary-qr"}\n',
            b'{"state":"connected"}\n',
        ]
    )

    await manager._read_process(process)  # type: ignore[arg-type]

    assert manager.status() == {"state": "connected", "qr": "", "error": "", "paired": True}
    assert marker.is_file()
    assert enabled == ["whatsapp"]


async def test_whatsapp_cancel_terminates_process():
    manager = integration.WhatsAppPairingManager()
    process = FakeProcess([])
    process.returncode = None  # type: ignore[assignment]
    manager._process = process  # type: ignore[assignment]

    result = await manager.cancel()

    assert process.terminated is True
    assert result["state"] == "idle"
    assert result["qr"] == ""


async def test_integration_api_does_not_echo_app_password(jarvis_env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    async def fake_configure(account_name: str, email: str, full_name: str, app_password: str):
        assert app_password == "abcd efgh ijkl mnop"
        return {"configured": True, "email": email, "full_name": full_name}

    monkeypatch.setattr("app.api.integrations.configure_gmail", fake_configure)
    client = TestClient(app)
    response = client.post(
        "/api/integrations/email/configure",
        json={
            "account_name": "personal",
            "email": "user@gmail.com",
            "full_name": "User Name",
            "app_password": "abcd efgh ijkl mnop",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"]["configured"] is True
    assert "app_password" not in str(body)
    assert "abcdefghijklmnop" not in str(body)
