from __future__ import annotations

import asyncio
import json

import pytest

from app.mobile import companion_security, connectivity, gateway, store


@pytest.fixture
def network_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.delenv("JARVIS_RELAY_ENDPOINT", raising=False)


@pytest.fixture
def security_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    guard = companion_security.CompanionSecurityGuard()
    monkeypatch.setattr(companion_security, "GUARD", guard)
    return guard


@pytest.mark.asyncio
async def test_gateway_refuses_during_cooldown(security_env, monkeypatch):
    security_env._cooldown_until = __import__("time").time() + 600
    app = gateway.gateway_app("http://127.0.0.1:4780")
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://gateway") as client:
        response = await client.get("/api/companion/models")
    assert response.status_code == 503
    assert response.json()["cooldown_remaining_seconds"] > 0


@pytest.mark.asyncio
async def test_detected_hack_attempt_event_shape(security_env):
    events: list[dict] = []
    from app.events import BUS

    queue = BUS.subscribe()
    task = asyncio.create_task(security_env.report_bad_session("device-1", "192.168.1.5"))
    await task
    while not queue.empty():
        events.append(await asyncio.wait_for(queue.get(), timeout=1))
    BUS.unsubscribe(queue)
    assert events
    event = events[-1]
    assert event["kind"] == "detected-hack-attempt"
    payload = json.loads(event["detail"])
    assert payload["kind"] == "detected-hack-attempt"
    assert payload["probability"] >= 0.5
    assert payload["device_id"] == "device-1"
    assert payload["endpoint_class"] in {"lan", "forwarded", "relay", "unknown"}
    assert payload["owner_message"]
    assert "exploit" not in payload["owner_message"].lower()


@pytest.mark.asyncio
async def test_ensure_gateway_listens_without_prepare_connection(network_env, monkeypatch):
    monkeypatch.setattr(connectivity, "GUARD", companion_security.CompanionSecurityGuard())
    connection = connectivity.Connectivity()

    async def noop_probe(endpoint, identity):
        return

    monkeypatch.setattr(connection, "probe", noop_probe)
    await connection.ensure_gateway_listening()
    assert connection.server_task is not None
    assert connection.state["state"] == "listening"
    assert connection.state["local_verified"]
    await connection.stop_gateway()


@pytest.mark.asyncio
async def test_companion_models_still_401_without_pairing(network_env, monkeypatch):
    import socket
    import ssl
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    connection = connectivity.Connectivity()
    upstream = FastAPI()

    @upstream.get("/api/companion/models")
    def require_auth():
        return JSONResponse({"detail": "Device credentials required"}, 401)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    from app import config

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        monkeypatch.setattr(connectivity, "PORT", free.getsockname()[1])
    monkeypatch.setattr(config, "load_settings", lambda: __import__("types").SimpleNamespace(bind_port=port))
    server = connectivity.EmbeddedServer(uvicorn.Config(upstream, log_level="warning"))
    upstream_task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        await connection.ensure_gateway_listening()
        context = ssl.create_default_context(cafile=connection.identity["certificate"])
        import httpx

        async with httpx.AsyncClient(verify=context, trust_env=False) as client:
            response = await client.get(f"https://127.0.0.1:{connectivity.PORT}/api/companion/models")
        assert response.status_code == 401
    finally:
        await connection.stop_gateway()
        server.should_exit = True
        await upstream_task
