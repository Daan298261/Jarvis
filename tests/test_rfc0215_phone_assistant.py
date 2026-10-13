from __future__ import annotations
import time
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException, FastAPI
from httpx import AsyncClient, ASGITransport
from app.mobile import store, phone_setup, phone_tools


@pytest.fixture
def phone_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def test_router_consent_is_independent_and_revocable(phone_env):
    with pytest.raises(HTTPException):
        phone_setup.approve_router("192.168.1.1", False, True)
    with pytest.raises(HTTPException):
        phone_setup.approve_router("8.8.8.8", True, True, True)
    consent = phone_setup.approve_router("192.168.1.1", True, True)
    phone_setup.require_router_approval(consent["id"], consent["router"])
    with pytest.raises(HTTPException, match="Separate explicit"):
        phone_setup.require_router_approval(consent["id"], consent["router"], red=True)
    with pytest.raises(HTTPException):
        phone_setup.require_router_approval(consent["id"], "192.168.1.2")
    consent["revoked"] = True
    with store.database() as db:
        store.put(db, "router_setup_approval", consent["id"], consent)
    with pytest.raises(HTTPException):
        phone_setup.require_router_approval(consent["id"], consent["router"])


@pytest.mark.asyncio
async def test_unapproved_red_never_calls_model(phone_env, monkeypatch):
    import httpx
    client = AsyncMock()
    monkeypatch.setattr(httpx, "AsyncClient", client)
    consent = phone_setup.approve_router("192.168.1.1", True, True)
    with pytest.raises(HTTPException):
        await phone_setup.router_advice(consent["id"], consent["router"], "Help", red=True)
    client.assert_not_called()
    ordinary = await phone_setup.router_advice(consent["id"], consent["router"], "Help")
    assert not ordinary["red_model_used"]
    client.assert_not_called()


def test_overlay_peers_cannot_auto_enroll():
    from app.mobile.gateway import _private_client
    from app.mobile.identity import client_may_lan_enroll
    for address in ("100.100.100.100", "fd7a:115c:a1e0::1"):
        assert not _private_client(address)
        assert not client_may_lan_enroll(address)
    assert _private_client("192.168.1.9")


def test_tool_queue_scoped_to_active_phone_and_once_only(phone_env):
    with store.database() as db:
        store.put(db, "device", "a", {"id": "a", "status": "active"})
        store.put(db, "device", "b", {"id": "b", "status": "revoked"})
    command = {"action": "read", "package": "com.example.app"}
    with pytest.raises(HTTPException):
        phone_tools.enqueue("b", command)
    item = phone_tools.enqueue("a", command)
    assert phone_tools.pending("b") == []
    with pytest.raises(HTTPException):
        phone_tools.finish("b", item["id"], {"ok": True})
    phone_tools.finish("a", item["id"], {"ok": False, "error": "declined"})
    assert phone_tools.pending("a") == []
    with pytest.raises(HTTPException):
        phone_tools.finish("a", item["id"], {"ok": True})


@pytest.mark.asyncio
async def test_tailscale_setup_never_maps_router(phone_env, monkeypatch):
    from app.mobile.connectivity import Connectivity
    connection = Connectivity()
    connection.identity = {"server_pin": "a" * 64}
    monkeypatch.setattr(connection, "release_mapping", AsyncMock())
    monkeypatch.setattr(connection, "ensure_gateway_listening", AsyncMock())
    monkeypatch.setattr(connection, "cover_phone_dial_hosts", AsyncMock())
    monkeypatch.setattr("app.mobile.connectivity.lan_hosts", lambda: ["192.168.1.2"])
    monkeypatch.setattr(phone_setup, "tailscale_status", lambda: {
        "available": True, "endpoints": ["https://100.100.100.1:4781"], "message": "Ready"})
    router = AsyncMock()
    monkeypatch.setattr("app.mobile.connectivity.router_candidate", router)
    await connection.apply_remote({"enabled": True, "remote": True, "connection_mode": "tailscale"})
    router.assert_not_called()
    assert "https://100.100.100.1:4781" in connection.state["endpoints"]
    assert connection.state["wan_path"] == "tailscale"
    assert not connection.state.get("remote_verified")


def test_connection_evidence_invalidated_when_endpoint_changes(phone_env):
    from app.mobile.connectivity import Connectivity
    connection = Connectivity()
    endpoint = "https://100.100.100.1:4781"
    connection.report(endpoints=[endpoint], phone_verification={"endpoint": endpoint, "verified_at": time.time()})
    assert connection.snapshot()["phone_verified"]
    connection.report(endpoints=["https://100.100.100.2:4781"])
    assert not connection.snapshot()["phone_verified"]


@pytest.mark.asyncio
async def test_setup_routes_are_owner_only_and_results_are_device_scoped(phone_env, monkeypatch):
    from app.config import AppSettings
    monkeypatch.setattr("app.auth.load_settings", lambda: AppSettings(auth_token="jarvis_pk_test_owner"))
    from app.api.companion import owner_router, router
    app = FastAPI()
    app.include_router(owner_router); app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app, client=("198.51.100.9", 40000)), base_url="http://test") as client:
        for path in ("/api/mobile/manage/phone-setup", "/api/companion/phone-tools"):
            assert (await client.get(path)).status_code in (401, 403)


def test_small_pack_catalog_retains_existing_models():
    from app.mobile.companion_offline import COMPANION_PACK_CATALOG
    by_id = {item["id"]: item for item in COMPANION_PACK_CATALOG}
    assert "qwen3.5-2b-heretic-q4" in by_id
    assert "qwen3.5-4b-abliterated-q4" in by_id
    assert by_id["qwen3-0.6b-abliterated-q4"]["min_ram_mb"] < by_id["qwen3-1.7b-abliterated-q4"]["min_ram_mb"]
    assert sum(bool(item["recommended"]) for item in by_id.values()) == 1
