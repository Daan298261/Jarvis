import asyncio
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import AppSettings
from app.inference import node_inventory as ni, running_models as rm


def test_processes_group_children_without_reading_private_arguments(monkeypatch):
    def processes(attrs):
        assert attrs == ["pid", "ppid", "name", "create_time"]
        return [NS(info=dict(pid=pid, ppid=parent, name=name, create_time=1)) for pid, parent, name in
                [(1, 0, "Codex.exe"), (2, 1, "Codex.exe"), (3, 2, "Codex.exe"),
                 (4, 0, "Codex.exe"), (5, 0, "Cursor.exe"), (6, 0, "unrelated.exe")]]
    monkeypatch.setattr(ni.psutil, "process_iter", processes)
    monkeypatch.setattr(ni.psutil, "net_connections", lambda **kw: [])
    rows = ni.process_inventory()["programs"]
    assert [(row["name"], row["pid"], row["process_count"]) for row in rows] == [("Codex", 1, 3), ("Codex", 4, 1), ("Cursor", 5, 1)]


def test_listener_access_failure_is_partial_not_empty_success(monkeypatch):
    monkeypatch.setattr(ni.psutil, "process_iter", lambda attrs: [])
    def denied(**kw):
        raise ni.psutil.AccessDenied()
    monkeypatch.setattr(ni.psutil, "net_connections", denied)
    assert "unavailable" in ni.process_inventory()["warnings"][0]


def test_ollama_internal_worker_is_grouped_and_flagged(monkeypatch):
    monkeypatch.setattr(ni.psutil, "process_iter", lambda attrs: [
        NS(info={"pid": 1, "ppid": 0, "name": "ollama.exe"}), NS(info={"pid": 2, "ppid": 1, "name": "llama-server.exe"})])
    monkeypatch.setattr(ni.psutil, "net_connections", lambda **kw: [NS(status=ni.psutil.CONN_LISTEN, pid=2,
        laddr=NS(ip="127.0.0.1", port=3001))])
    result = ni.process_inventory()
    assert [(item["name"], item["process_count"]) for item in result["programs"]] == [("Ollama", 2)]
    assert result["listeners"][3001]["internal_worker"]


@pytest.mark.parametrize("payload", ["[]", "broken", "null", '{"node_id":"node-7"}'])
def test_node_identity_does_not_create_or_repair_identity(tmp_path, monkeypatch, payload):
    path = tmp_path / "identity.json"
    path.write_text(payload)
    monkeypatch.setattr("app.swarm.nodes.identity_path", lambda: path)
    assert ni.node_identity()["id"] == ("node-7" if "node-7" in payload else None)
    assert path.read_text() == payload


@pytest.fixture
def inventory(monkeypatch):
    settings = AppSettings()
    settings.inference.host = "127.0.0.1"
    settings.inference.port = 1234
    settings.front_responder.port = 8089
    manager = NS(state=NS(port=1234, loaded=True, manages_process=False, pid=None, remote_model="worker"), provider=NS(model="worker"))
    front = NS(_decision=NS(healthy=True, endpoint="http://127.0.0.1:8089/v1"), _backend=NS(pid=12), model_id=lambda settings: "front")
    monkeypatch.setattr("app.inference.manager.MANAGER", manager)
    monkeypatch.setattr("app.inference.front_runtime.FRONT_RUNTIME", front)
    monkeypatch.setattr(ni, "load_settings", lambda: settings)
    monkeypatch.setattr(ni, "node_identity", lambda: {"id": "node", "hostname": "test", "scope": "portal_node"})
    monkeypatch.setattr(ni, "process_inventory", lambda: {"programs": [{"name": "Codex"}], "warnings": [], "listeners": {
        8089: {"name": "llama.cpp", "pid": 12}, 1234: {"name": "LM Studio", "pid": 13}}})
    monkeypatch.setattr(ni, "KNOWN_PORTS", {8000})
    return ni.NodeInventory(), settings, manager


async def test_includes_front_worker_other_instances_and_unverified_servers(inventory, monkeypatch):
    service, settings, manager = inventory
    async def probe(port, **kw):
        assert kw["include_embeddings"]
        if port == 8089:
            return {"models": ["front"], "backend": "remote"}
        if port == 1234:
            return {"models": ["worker", "second", "embed"], "backend": "lmstudio", "verified_loaded": True,
                    "source": "lmstudio_loaded_instances", "metadata": {"second": {"model_key": "worker"}}}
        return {"models": ["downloaded"], "backend": "remote", "verified_loaded": False}
    monkeypatch.setattr(ni, "probe", probe)
    result = await service.scan()
    rows = {row["model"]: row for row in result["models"]}
    assert rows["worker"]["active"] and rows["worker"]["roles"] == ["Worker"]
    assert rows["front"]["roles"] == ["Front"] and rows["front"]["verified_loaded"]
    assert rows["second"]["verified_loaded"] and rows["embed"]["verified_loaded"]
    assert not rows["second"]["active"]
    assert not rows["downloaded"]["verified_loaded"]
    assert len({row["id"] for row in rows.values()}) == 5
    assert result["read_only"] and "Browser-only" in result["coverage"]


async def test_ambiguous_model_key_does_not_mark_two_instances_active(inventory, monkeypatch):
    service, _, _ = inventory
    monkeypatch.setattr(ni, "probe", AsyncMock(return_value={"models": ["a", "b"], "backend": "lmstudio", "verified_loaded": True,
        "metadata": {"a": {"model_key": "worker"}, "b": {"model_key": "worker"}}}))
    result = await service.scan()
    assert not any(row["active"] for row in result["models"])


async def test_saved_selection_does_not_override_provider_actually_in_use(inventory, monkeypatch):
    service, _, manager = inventory
    manager.state.remote_model = "saved-9B"
    monkeypatch.setattr(ni, "probe", AsyncMock(return_value={"models": ["worker", "saved-9B"], "backend": "lmstudio", "verified_loaded": True}))
    rows = (await service.scan())["models"]
    assert [row["model"] for row in rows if row["active"]] == ["worker"]


async def test_scan_caches_force_refresh_and_keeps_probe_setup_off_portal_loop(inventory, monkeypatch):
    service, settings, _ = inventory
    main_thread = threading.get_ident()
    calls = []
    def blocking_settings():
        assert threading.get_ident() != main_thread
        time.sleep(.025)
        return settings
    async def probe(port, **kw):
        assert threading.get_ident() != main_thread
        calls.append(port)
        time.sleep(.025)
        return None
    monkeypatch.setattr(ni, "load_settings", blocking_settings)
    monkeypatch.setattr(ni, "probe", probe)
    task = asyncio.create_task(service.scan())
    ticks = 0
    while not task.done():
        ticks += 1
        await asyncio.sleep(.005)
    assert ticks > 3
    first = await task
    count = len(calls)
    assert await service.scan() is first
    assert len(calls) == count
    await service.scan(force=True)
    assert len(calls) == count * 2


async def test_remote_credentials_never_sent_to_local_discovery(inventory, monkeypatch):
    service, settings, _ = inventory
    settings.inference.host = "remote.example"
    settings.inference.api_key = "secret"
    probe = AsyncMock(return_value=None)
    monkeypatch.setattr(ni, "probe", probe)
    await service.scan()
    assert all(call.kwargs["api_key"] == "" for call in probe.call_args_list)


async def test_native_metadata_preserves_multiple_instances_and_embedding_inventory(monkeypatch):
    client_type = httpx.AsyncClient
    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "advertised"}]})
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": [
                {"type": "llm", "key": "qwen3.8-9b", "params_string": "9B", "quantization": {"name": "Q8"},
                 "loaded_instances": [{"id": "one", "config": {"context_length": 8192}}, {"id": "two"}]},
                {"type": "llm", "key": "unloaded", "loaded_instances": []},
                {"type": "embedding", "key": "embedding", "loaded_instances": [{"id": "embed"}]}]})
        return httpx.Response(404)
    monkeypatch.setattr(rm.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    result = await rm.probe(1234, include_embeddings=True)
    assert result["models"] == ["one", "two", "embed"]
    assert result["verified_loaded"]
    assert result["metadata"]["one"]["parameters"] == "9B"
    assert result["metadata"]["one"]["context_size"] == 8192
    assert (await rm.probe(1234))["models"] == ["one", "two"]


async def test_generic_openai_listing_is_never_verified_loaded(monkeypatch):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(rm.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "downloaded"}]}) if request.url.path == "/v1/models" else httpx.Response(404)), **kw))
    assert not (await rm.probe(8000))["verified_loaded"]
    with pytest.raises(ValueError, match="loopback"):
        await rm.probe(8000, host="remote.example")


@pytest.mark.parametrize("healthy", [True, False])
async def test_llama_native_properties_require_ready_health(monkeypatch, healthy):
    client_type = httpx.AsyncClient
    def handle(request):
        bodies = {"/v1/models": {"data": [{"id": "front"}, {"id": "advertised-only"}]},
            "/props": {"model_path": "C:\\models\\Qwen3.5-2B-Q4.gguf", "model_alias": "front", "total_slots": 1,
                       "default_generation_settings": {"n_ctx": 4096}}, "/health": {"status": "ok" if healthy else "loading model"}}
        return httpx.Response(200, json=bodies[request.url.path]) if request.url.path in bodies else httpx.Response(404)
    monkeypatch.setattr(rm.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    result = await rm.probe(8089, include_embeddings=True)
    assert result["verified_loaded"] is healthy
    if healthy:
        assert result["models"] == ["front"]
        assert result["metadata"]["front"]["display_name"] == "Qwen3.5-2B-Q4.gguf"
        assert result["metadata"]["front"]["context_size"] == 4096


async def test_inventory_route_refresh_is_read_only(monkeypatch):
    from app.api.model import node_ai_inventory
    scan = AsyncMock(return_value={"read_only": True})
    monkeypatch.setattr(ni.NODE_INVENTORY, "scan", scan)
    assert await node_ai_inventory(refresh=True) == {"read_only": True}
    scan.assert_awaited_once_with(force=True)
