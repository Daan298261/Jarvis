import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.config import AppSettings
from app.inference import running_models as rm
from app.inference.manager import InferenceManager


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(rm.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("status,body", [(404, {}), (401, {"data": [{"id": "qwen"}]}),
    (302, {"data": [{"id": "qwen"}]}), (200, {"ok": True}), (200, {"data": []}),
    (200, {"data": "not a list"}), (200, [])])
async def test_unrelated_or_failed_servers_are_not_models(monkeypatch, status, body):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=body))
    assert await rm.probe(1234) is None


async def test_valid_server_uses_metadata_only(monkeypatch):
    paths = []
    def handle(request):
        paths.append(request.url.path)
        assert request.method == "GET"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "qwen-coder"}]}) if request.url.path == "/v1/models" else httpx.Response(404)
    mock_http(monkeypatch, handle)
    assert (await rm.probe(1235))["models"] == ["qwen-coder"]
    assert "/v1/chat/completions" not in paths


async def test_ollama_empty_loaded_inventory_does_not_offer_downloads(monkeypatch):
    def handle(request):
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": []})
    mock_http(monkeypatch, handle)
    assert await rm.probe(11434) is None


async def test_ollama_offers_only_loaded_models(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"models": [{"name": "coder:latest"}]}))
    result = await rm.probe(11434)
    assert result["backend"] == "ollama"
    assert result["models"] == ["coder:latest"]


async def test_lmstudio_filters_unloaded_models(monkeypatch):
    def handle(request):
        if request.url.path == "/api/ps":
            return httpx.Response(404)
        if request.url.path == "/api/v0/models":
            return httpx.Response(200, json={"data": [{"id": "coder", "state": "loaded"},
                {"id": "downloaded", "state": "not-loaded"}]})
        return httpx.Response(200, json={"data": [{"id": "downloaded"}, {"id": "coder"}]})
    mock_http(monkeypatch, handle)
    assert (await rm.probe(1234))["models"] == ["coder"]


async def test_modern_lmstudio_filters_embeddings_and_exposes_instance_unload(monkeypatch):
    def handle(request):
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": [
                {"type": "llm", "key": "coder", "loaded_instances": [{"id": "coder-instance"}]},
                {"type": "llm", "key": "unloaded", "loaded_instances": []},
                {"type": "embedding", "key": "embedding", "loaded_instances": [{"id": "embed"}]},
            ]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "coder-instance"}]})
        return httpx.Response(404)
    mock_http(monkeypatch, handle)
    result = await rm.probe(1234)
    assert result["backend"] == "lmstudio"
    assert result["models"] == result["instance_ids"] == ["coder-instance"]


async def test_probe_total_deadline(monkeypatch):
    async def handle(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"data": [{"id": "qwen"}]})
    mock_http(monkeypatch, handle)
    assert await asyncio.wait_for(rm.probe(1234), timeout=3) is None


@pytest.fixture
def service(tmp_path, monkeypatch):
    settings = AppSettings()
    settings.inference.auto_load = False
    manager = InferenceManager()
    monkeypatch.setattr("app.inference.manager.MANAGER", manager)
    monkeypatch.setattr(rm, "load_settings", lambda: settings)
    monkeypatch.setattr(rm, "listener_inventory", lambda: {})
    async def probe(port, **kw):
        if port == 1235:
            return {"port": port, "backend": "remote", "models": ["coder"]}
    monkeypatch.setattr(rm, "probe", probe)
    return rm.RunningModels(tmp_path / "choices.json"), settings, manager


async def test_choices_survive_restarts_and_model_changes(service, monkeypatch):
    runtime, settings, manager = service
    await runtime.scan()
    row = runtime.rows[0]
    await runtime.decide(row["id"], "leave")
    restarted = rm.RunningModels(runtime.path)
    await restarted.scan()
    assert restarted.rows[0]["choice"] == "leave"
    async def changed(port, **kw):
        return {"port": port, "backend": "remote", "models": ["new-coder"]} if port == 1235 else None
    monkeypatch.setattr(rm, "probe", changed)
    await runtime.scan(force=True)
    assert runtime.rows[0]["choice"] is None


async def test_scan_skips_managed_worker_front_and_caches(service, monkeypatch):
    runtime, settings, manager = service
    manager.state.manages_process = True
    manager.state.pid = 1
    manager.state.port = 8088
    settings.front_responder.port = 1234
    probe = AsyncMock(return_value=None)
    monkeypatch.setattr(rm, "probe", probe)
    await runtime.scan()
    ports = [call.args[0] for call in probe.call_args_list]
    assert 1234 not in ports and 8088 not in ports
    count = probe.call_count
    await runtime.scan()
    assert probe.call_count == count


async def test_use_no_gguf_required_and_preserves_history(service, monkeypatch):
    runtime, settings, manager = service
    settings.inference.api_key = "another-servers-key"
    save = Mock()
    monkeypatch.setattr(rm, "save_settings", save)
    monkeypatch.setattr(manager, "refresh_resources", AsyncMock())
    monkeypatch.setattr("app.inference.manager.probe_remote_server", AsyncMock(return_value={
        "ok": True, "models": ["coder"], "n_ctx": 4096,
    }))
    from app.persona import owner_chat
    rebind = Mock()
    monkeypatch.setattr(owner_chat, "rebind_owner_conversations_after_hotswap", rebind)
    await runtime.scan()
    await runtime.decide(runtime.rows[0]["id"], "use")
    chosen = save.call_args.args[0]
    assert chosen.inference.backend == "remote"
    assert chosen.inference.port == 1235
    assert chosen.inference.remote_model == "coder"
    assert chosen.inference.api_key == ""
    assert manager.provider.model == "coder"
    assert manager.state.loaded
    assert not manager.state.manages_process
    assert rebind.call_count == 1
    assert runtime.choices()[runtime.rows[0]["id"]] == "use"


async def test_failed_use_is_not_remembered(service, monkeypatch):
    runtime, settings, manager = service
    monkeypatch.setattr(manager, "load", AsyncMock(side_effect=RuntimeError("unavailable")))
    await runtime.scan()
    with pytest.raises(RuntimeError, match="unavailable"):
        await runtime.decide(runtime.rows[0]["id"], "use")
    assert not runtime.choices()
    assert manager.provider is None


async def test_stale_server_and_inflight_request_block_choices(service, monkeypatch):
    runtime, settings, manager = service
    await runtime.scan()
    identifier = runtime.rows[0]["id"]
    async with manager._request_lease.shared():
        with pytest.raises(ValueError, match="answering"):
            await runtime.decide(identifier, "use")
    monkeypatch.setattr(rm, "probe", AsyncMock(return_value=None))
    with pytest.raises(ValueError, match="changed"):
        await runtime.decide(identifier, "use")


async def test_unknown_server_cannot_be_killed(service):
    runtime, settings, manager = service
    await runtime.scan()
    with pytest.raises(ValueError, match="safe stop"):
        await runtime.decide(runtime.rows[0]["id"], "stop")


async def test_external_busy_model_blocks_use(service, monkeypatch):
    runtime, settings, manager = service
    async def busy(port, **kw):
        return {"port": port, "backend": "remote", "models": ["coder"], "busy": True} if port == 1235 else None
    monkeypatch.setattr(rm, "probe", busy)
    await runtime.scan()
    with pytest.raises(ValueError, match="Another client"):
        await runtime.decide(runtime.rows[0]["id"], "use")


def test_inventory_excludes_ollama_internal_worker(monkeypatch):
    connection = SimpleNamespace(status=rm.psutil.CONN_LISTEN, pid=42,
                                 laddr=SimpleNamespace(ip="127.0.0.1", port=2661))
    process = Mock()
    process.name.return_value = "llama-server.exe"
    parent = Mock()
    parent.name.return_value = "ollama.exe"
    process.parents.return_value = [parent]
    monkeypatch.setattr(rm.psutil, "net_connections", lambda **kw: [connection])
    monkeypatch.setattr(rm.psutil, "Process", lambda pid: process)
    assert rm.listener_inventory() == {}


@pytest.mark.parametrize("changed", ["pid_identity", "listener", "name"])
def test_stop_refuses_reused_pid_or_changed_listener(monkeypatch, changed):
    process = Mock()
    process.create_time.return_value = 2 if changed == "pid_identity" else 1
    process.name.return_value = "aider.exe" if changed == "name" else "llama-server.exe"
    process.net_connections.return_value = [] if changed == "listener" else [SimpleNamespace(
        status=rm.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=1235))]
    monkeypatch.setattr(rm.psutil, "Process", lambda pid: process)
    with pytest.raises(ValueError, match="changed"):
        rm.stop_listener({"port": 1235, "process": {"pid": 42, "created": 1, "name": "llama-server.exe"}})
    process.terminate.assert_not_called()


def test_stop_targets_one_verified_server(monkeypatch):
    process = Mock()
    process.create_time.return_value = 1
    process.name.return_value = "llama-server.exe"
    process.net_connections.return_value = [SimpleNamespace(status=rm.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=1235))]
    monkeypatch.setattr(rm.psutil, "Process", lambda pid: process)
    rm.stop_listener({"port": 1235, "process": {"pid": 42, "created": 1, "name": "llama-server.exe"}})
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)


async def test_stop_api_requires_confirmation(monkeypatch):
    from fastapi import FastAPI
    from app.api.model import router
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/model/running/abc/choice", json={"action": "stop"})
    assert response.status_code == 400


@pytest.mark.parametrize("body", [{"models": [{"name": "coder"}]}, {"ok": True}])
async def test_unload_verification_refuses_loaded_or_unknown_state(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        with pytest.raises(ValueError, match="replacement was not attempted"):
            await rm.verify_unloaded(client, {"port": 11434, "backend": "ollama", "model": "coder"})


async def test_optional_native_failures_do_not_hide_valid_openai_server(monkeypatch):
    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "coder"}]})
        return httpx.Response(200, text="unrelated HTML page")
    mock_http(monkeypatch, handle)
    assert (await rm.probe(1234))["models"] == ["coder"]


@pytest.mark.parametrize("approved", [True, False])
async def test_background_reconnect_requires_existing_owner_choice(service, monkeypatch, approved):
    runtime, settings, manager = service
    await runtime.scan()
    row = runtime.rows[0]
    row["choice"] = "use" if approved else None
    settings.inference.backend = "remote"
    settings.inference.port = row["port"]
    settings.inference.remote_model = row["model"]
    runtime._notified.add(row["id"])
    monkeypatch.setattr(runtime, "scan", AsyncMock())
    load = AsyncMock()
    monkeypatch.setattr(manager, "load", load)
    async def finish(_seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(rm.asyncio, "sleep", finish)
    with pytest.raises(asyncio.CancelledError):
        await runtime._poll()
    assert load.call_count == int(approved)


async def test_new_offer_is_announced_once_on_front_voice_lane(service, monkeypatch):
    runtime, settings, manager = service
    await runtime.scan()
    monkeypatch.setattr(runtime, "scan", AsyncMock())
    from app.persona import chat_delivery
    publish = AsyncMock()
    monkeypatch.setattr(chat_delivery, "publish_owner_text", publish)
    count = 0
    async def finish(_seconds):
        nonlocal count
        count += 1
        if count == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(rm.asyncio, "sleep", finish)
    with pytest.raises(asyncio.CancelledError):
        await runtime._poll()
    assert publish.call_count == 1
    assert publish.call_args.kwargs["lane"] == "front"


async def test_startup_waits_for_owner_choice_before_loading_worker(service, monkeypatch):
    runtime, settings, manager = service
    from app import main
    monkeypatch.setattr(rm, "RUNNING_MODELS", runtime)
    monkeypatch.setattr(main, "MANAGER", manager)
    load = AsyncMock()
    monkeypatch.setattr(manager, "load", load)
    await main._autoload_model(settings)
    load.assert_not_called()
