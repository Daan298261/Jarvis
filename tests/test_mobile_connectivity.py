import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.mobile import connectivity, store


@pytest.fixture
def network_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.delenv("JARVIS_RELAY_ENDPOINT", raising=False)


class Router:
    lanaddr = "192.168.1.12"
    def __init__(self, mapping=None):
        self.mapping = mapping
        self.added = []
        self.deleted = []
    def getspecificportmapping(self, port, protocol):
        return self.mapping
    def addportmapping(self, *args):
        self.added.append(args)
        self.mapping = (args[2], args[3], args[4], "1", "", args[6])
        return True
    def deleteportmapping(self, *args):
        self.deleted.append(args)
        self.mapping = None


def test_router_mapping_never_overwrites_or_removes_foreign_entry():
    router = Router(("192.168.1.99", 4781, "Other app"))
    with pytest.raises(ValueError):
        connectivity.map_router(router, "Jarvis-owned")
    connectivity.unmap_router(router, "Jarvis-owned")
    assert router.added == router.deleted == []


def test_router_mapping_uses_only_tls_port_and_finite_lease():
    router = Router()
    connectivity.map_router(router, "Jarvis-owned")
    assert router.added == [(4781, "TCP", router.lanaddr, 4781, "Jarvis-owned", "", 3600)]
    connectivity.map_router(router, "Jarvis-owned")
    connectivity.unmap_router(router, "Jarvis-owned")
    assert router.deleted == [(4781, "TCP")]


@pytest.mark.parametrize("value", ["http://host", "https://key@host", "https://host/api", "https://host?key=secret", "https://host#token", "https://host:0"])
def test_endpoint_rejects_insecure_or_credential_bearing_origins(value):
    with pytest.raises(ValueError):
        connectivity.origin(value)


class FakeConnection(connectivity.Connectivity):
    async def start_gateway(self, identity):
        self.opened = True
    async def stop_gateway(self):
        self.opened = False
    async def probe(self, endpoint, identity):
        if getattr(self, "probe_fails", False):
            raise RuntimeError("Device authentication unavailable")


@pytest.mark.asyncio
async def test_router_is_mapped_only_after_gateway_auth_check(network_env, monkeypatch):
    router = Router()
    monkeypatch.setattr(connectivity, "router_candidate", lambda: (router, "8.8.8.8"))
    connection = FakeConnection()
    connection.probe_fails = True
    result = await connection.configure(True, True)
    assert result["state"] == "failed"
    assert not router.added
    assert not connection.opened
    connection.probe_fails = False
    result = await connection.configure(True, True)
    assert result["state"] == "ready"
    assert result["local_verified"]
    assert not result["remote_verified"]  # A lease does not prove WAN connectivity.
    assert result["endpoints"] == ["https://192.168.1.12:4781", "https://8.8.8.8:4781"]
    result = await connection.configure(False, False)
    assert result["state"] == "disabled" and not result["endpoints"]
    assert router.deleted == [(4781, "TCP")]


@pytest.mark.asyncio
async def test_lan_mode_does_not_discover_router(network_env, monkeypatch):
    def forbidden():
        pytest.fail("LAN-only setup must not contact the router")
    monkeypatch.setattr(connectivity, "router_candidate", forbidden)
    result = await FakeConnection().configure(True, False)
    assert result["state"] == "ready"
    assert result["router"] == "disabled"


@pytest.mark.asyncio
async def test_router_failure_keeps_lan_available(network_env, monkeypatch):
    def unavailable():
        raise ValueError("No public IPv4; carrier NAT")
    monkeypatch.setattr(connectivity, "router_candidate", unavailable)
    result = await FakeConnection().configure(True, True)
    assert result["state"] == "ready" and result["local_verified"]
    assert "carrier NAT" in result["limitation"]
    assert result["endpoints"] == ["https://192.168.1.12:4781"]


@pytest.mark.asyncio
async def test_connection_setup_requires_owner_key_even_on_localhost(network_env):
    from app.api.companion import owner_router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(owner_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 123)), base_url="http://localhost") as client:
        assert (await client.post("/api/mobile/manage/connection", json={"enabled": True})).status_code in (401, 403)


@pytest.mark.asyncio
async def test_managed_gateway_serves_real_tls_and_shuts_down(network_env, monkeypatch):
    import socket
    import ssl
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from app import config
    upstream = FastAPI()
    @upstream.get("/api/companion/models")
    def require_auth():
        return JSONResponse({"detail": "Device credentials required"}, 401)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    monkeypatch.setattr(config, "load_settings", lambda: SimpleNamespace(bind_port=listener.getsockname()[1]))
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        monkeypatch.setattr(connectivity, "PORT", free.getsockname()[1])
    server = connectivity.EmbeddedServer(uvicorn.Config(upstream, log_level="warning"))
    running = asyncio.create_task(server.serve(sockets=[listener]))
    connection = connectivity.Connectivity()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        result = await connection.configure(True, False)
        assert result["state"] == "ready", result
        context = ssl.create_default_context(cafile=connection.identity["certificate"])
        async with httpx.AsyncClient(verify=context, trust_env=False) as client:
            base = f"https://127.0.0.1:{connectivity.PORT}"
            assert (await client.get(base + "/api/companion/models")).status_code == 401
            assert (await client.get(base + "/api/mobile/manage/devices")).status_code == 404
        await connection.configure(False, False)
        assert connection.server_task is None
    finally:
        await connection.stop_gateway()
        server.should_exit = True
        await running
