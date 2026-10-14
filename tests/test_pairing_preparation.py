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
async def test_prepare_pairing_preserves_remote_config_and_does_not_discover_devices(monkeypatch):
    manager = connectivity.Connectivity()
    config = {"enabled": True, "remote": True, "remote_explicit": True, "tailscale": True, "rfc0215_migrated": True}
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


@pytest.mark.asyncio
async def test_ready_lan_qr_does_not_wait_for_remote_setup_lock(monkeypatch):
    import asyncio
    manager = connectivity.Connectivity()
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: False)
    monkeypatch.setattr(manager, "config", lambda: {"enabled": True, "remote": True})
    monkeypatch.setattr(manager, "snapshot", lambda: manager.state)
    manager.report(local_verified=True, endpoints=["https://192.168.1.9:4781"], server_pin="b" * 64)
    manager.server_task = asyncio.create_task(asyncio.sleep(60))
    listen = AsyncMock()
    monkeypatch.setattr(manager, "ensure_gateway_listening", listen)
    await manager.lock.acquire()
    try:
        result = await asyncio.wait_for(manager.prepare_pairing(), 0.2)
        assert result["server_pin"] == "b" * 64
        assert manager.lock.locked()  # The background owner still owns the lock.
        listen.assert_not_awaited()
    finally:
        manager.lock.release()
        manager.server_task.cancel()
        await asyncio.gather(manager.server_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unready_gateway_lock_returns_bounded_retry_error(monkeypatch):
    manager = connectivity.Connectivity()
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: False)
    monkeypatch.setattr(manager, "config", lambda: {"enabled": True})
    monkeypatch.setattr(manager, "snapshot", lambda: {})
    monkeypatch.setattr(connectivity, "PAIRING_LOCK_TIMEOUT_SECONDS", 0.01)
    await manager.lock.acquire()
    try:
        with pytest.raises(HTTPException) as error:
            await manager.prepare_pairing()
        assert error.value.status_code == 409
        assert "still starting" in error.value.detail
        assert manager.lock.locked()
    finally:
        manager.lock.release()


@pytest.mark.asyncio
async def test_gateway_timeout_cancels_preparation_and_releases_lock(monkeypatch):
    import asyncio
    manager = connectivity.Connectivity()
    monkeypatch.setattr(connectivity.GUARD, "cooldown_active", lambda: False)
    monkeypatch.setattr(manager, "config", lambda: {"enabled": True})
    monkeypatch.setattr(manager, "snapshot", lambda: {})
    monkeypatch.setattr(connectivity, "PAIRING_GATEWAY_TIMEOUT_SECONDS", 0.01)
    cancelled = asyncio.Event()
    async def hang():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
    monkeypatch.setattr(manager, "ensure_gateway_listening", hang)
    with pytest.raises(HTTPException) as error:
        await manager.prepare_pairing()
    assert error.value.status_code == 504
    assert cancelled.is_set()
    assert not manager.lock.locked()
