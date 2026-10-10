from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.mobile import connectivity
from test_companion_pairing import companion_env, owner_headers


def test_pair_intent_prepares_qr_without_detected_device(companion_env, monkeypatch):
    manager = connectivity.CONNECTIVITY
    snapshot = {}

    async def prepare():
        snapshot.update(endpoints=["https://192.168.1.9:4781"], server_pin="a" * 64)

    prepare_mock = AsyncMock(side_effect=prepare)
    monkeypatch.setattr(manager, "prepare_pairing", prepare_mock)
    monkeypatch.setattr(manager, "snapshot", lambda: snapshot)
    client = companion_env["client"]
    headers = owner_headers(companion_env["owner_key"])
    assert client.get("/api/mobile/manage/devices", headers=headers).json() == []
    response = client.post("/api/mobile/manage/pairing-codes", headers=headers,
                           json={"prepare_connection": True})
    assert response.status_code == 200
    prepare_mock.assert_awaited_once()
    payload = response.json()
    assert payload["qr"] == {"endpoint": "https://192.168.1.9:4781", "server_pin": "a" * 64,
                             "code": payload["code"], "endpoints": ["https://192.168.1.9:4781"]}
    previous = payload["code"]
    regenerated = client.post("/api/mobile/manage/pairing-codes/regenerate", headers=headers,
                              json={"prepare_connection": True})
    assert regenerated.status_code == 200
    assert regenerated.json()["qr"]["code"] != previous
    assert client.get("/api/mobile/manage/devices", headers=headers).json() == []


@pytest.mark.asyncio
async def test_prepare_pairing_preserves_wan_config_and_does_not_discover_devices(monkeypatch):
    manager = connectivity.Connectivity()
    config = {"enabled": True, "remote": True, "wan_method": "ssh_reverse"}
    monkeypatch.setattr(manager, "config", lambda: config)
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: False)

    async def listen():
        manager.report(endpoints=["https://192.168.1.9:4781"], server_pin="b" * 64)

    monkeypatch.setattr(manager, "snapshot", lambda: manager.state)
    monkeypatch.setattr(manager, "ensure_gateway_listening", AsyncMock(side_effect=listen))
    wan = AsyncMock()
    monkeypatch.setattr(manager, "apply_remote", wan)
    payload = await manager.prepare_pairing()
    assert payload["server_pin"] == "b" * 64
    assert config["remote"] is True
    wan.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_respects_security_cooldown_and_reports_no_network(monkeypatch):
    manager = connectivity.Connectivity()
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: True)
    listen = AsyncMock()
    monkeypatch.setattr(manager, "ensure_gateway_listening", listen)
    with pytest.raises(HTTPException, match="security cooldown"):
        await manager.prepare_pairing()
    listen.assert_not_awaited()
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: False)
    monkeypatch.setattr(manager, "snapshot", lambda: {})
    monkeypatch.setattr(manager, "config", lambda: {"enabled": True})
    with pytest.raises(HTTPException, match="Wi-Fi or Ethernet"):
        await manager.prepare_pairing()


def test_failed_preparation_does_not_issue_pairing_code(companion_env, monkeypatch):
    monkeypatch.setattr(connectivity.CONNECTIVITY, "prepare_pairing",
                        AsyncMock(side_effect=HTTPException(409, "Connect Wi-Fi first")))
    client = companion_env["client"]
    headers = owner_headers(companion_env["owner_key"])
    response = client.post("/api/mobile/manage/pairing-codes", headers=headers,
                           json={"prepare_connection": True})
    assert response.status_code == 409
    assert client.get("/api/mobile/manage/pairing-codes/status", headers=headers).json()["active"] is False
