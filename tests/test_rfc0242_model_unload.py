import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.config import AppSettings
from app.inference.manager import InferenceManager
from app.inference import model_release


def settings(backend="lmstudio", host="127.0.0.1"):
    result = AppSettings()
    result.inference.backend = backend
    result.inference.host = host
    result.inference.port = 1234 if backend == "lmstudio" else 11434
    return result


def mock_runtime(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(model_release.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))


@pytest.mark.asyncio
async def test_lmstudio_unloads_exact_selected_instance_and_preserves_other_model(monkeypatch):
    loaded = {"qwen-27b": ["instance-27"], "qwen-9b": ["instance-9"]}
    posts = []

    def handler(request):
        if request.method == "POST":
            assert request.url.path == "/api/v1/models/unload"
            body = json.loads(request.content)
            posts.append(body)
            assert body == {"instance_id": "instance-27"}
            loaded["qwen-27b"] = []
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"models": [
            {"key": key, "type": "llm", "loaded_instances": [{"id": ident} for ident in ids]}
            for key, ids in loaded.items()
        ]})

    mock_runtime(monkeypatch, handler)
    await model_release.release_external_model(settings(), "lmstudio", "qwen-27b")
    assert posts == [{"instance_id": "instance-27"}]
    assert loaded["qwen-9b"] == ["instance-9"]


@pytest.mark.asyncio
async def test_success_response_is_insufficient_if_instance_still_loaded(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"models": [{"key": "qwen", "type": "llm", "loaded_instances": [{"id": "still-here"}]}]})

    mock_runtime(monkeypatch, handler)
    monkeypatch.setattr(model_release.asyncio, "sleep", AsyncMock())
    with pytest.raises(RuntimeError, match="still loaded"):
        await model_release.release_external_model(settings(), "lmstudio", "qwen")


@pytest.mark.asyncio
async def test_malformed_inventory_never_confirms_unload(monkeypatch):
    mock_runtime(monkeypatch, lambda request: httpx.Response(200, json={"models": [{"key": "qwen", "type": "llm", "loaded_instances": [{}]}]}))
    with pytest.raises(RuntimeError, match="invalid loaded model instance"):
        await model_release.release_external_model(settings(), "lmstudio", "qwen")


@pytest.mark.asyncio
async def test_verified_external_release_pauses_manager_and_clears_active_identity(monkeypatch):
    manager = InferenceManager()
    manager.state.loaded = True
    manager.provider = SimpleNamespace(model="qwen-27b")
    manager.backend = SimpleNamespace(settings=settings(), name="lmstudio", manages_process=False, stop=AsyncMock())
    release = AsyncMock()
    monkeypatch.setattr(model_release, "release_external_model", release)
    await manager.unload(release_external=True)
    assert release.await_args.args[1:] == ("lmstudio", "qwen-27b")
    assert not manager.state.loaded and manager.state.manually_unloaded
    assert manager.provider is None
    assert manager.live_state_overlay()["active_model"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend,host", [("lmstudio", "192.168.1.5"), ("vllm", "127.0.0.1")])
async def test_remote_or_unsupported_runtime_never_gets_an_unload_request(backend, host, monkeypatch):
    mock_runtime(monkeypatch, lambda request: pytest.fail("Unexpected runtime request"))
    with pytest.raises(RuntimeError):
        await model_release.release_external_model(settings(backend, host), backend, "qwen")


@pytest.mark.asyncio
async def test_ollama_releases_selected_model_without_loading_another(monkeypatch):
    loaded = ["qwen:latest", "other:latest"]

    def handler(request):
        if request.method == "POST":
            assert json.loads(request.content) == {"model": "qwen:latest", "keep_alive": 0, "stream": False}
            loaded.remove("qwen:latest")
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"models": [{"name": name} for name in loaded]})

    mock_runtime(monkeypatch, handler)
    await model_release.release_external_model(settings("ollama"), "ollama", "qwen")
    assert loaded == ["other:latest"]


@pytest.mark.asyncio
async def test_failed_unload_keeps_manager_loaded_and_does_not_pause(monkeypatch):
    manager = InferenceManager()
    manager.state.loaded = True
    manager.provider = SimpleNamespace(model="qwen-27b")
    manager.backend = SimpleNamespace(settings=settings(), name="lmstudio", manages_process=False, stop=AsyncMock())
    monkeypatch.setattr(model_release, "release_external_model", AsyncMock(side_effect=RuntimeError("still loaded")))
    with pytest.raises(RuntimeError, match="still loaded"):
        await manager.unload(release_external=True)
    assert manager.state.loaded and manager.provider.model == "qwen-27b"
    assert not manager.state.manually_unloaded
    manager.backend.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_managed_unload_stops_process_and_blocks_automatic_reload(monkeypatch):
    manager = InferenceManager()
    manager.state.loaded = True
    manager.backend = SimpleNamespace(manages_process=True, stop=AsyncMock())
    await manager.unload(release_external=True)
    manager.backend.stop.assert_awaited_once()
    assert not manager.state.loaded and manager.state.manually_unloaded
    assert manager.live_state_overlay()["active_model"] is None
    with pytest.raises(RuntimeError, match="manually unloaded"):
        await manager.load(settings())

    async def fake_load(*args, **kwargs):
        manager.state.loaded = True
        return manager.state

    monkeypatch.setattr(manager, "_load_locked", fake_load)
    await manager.load(settings(), manual_resume=True)
    assert manager.state.loaded and not manager.state.manually_unloaded


@pytest.mark.asyncio
async def test_unload_endpoint_refuses_while_answering(monkeypatch):
    from app.api import model
    manager = InferenceManager()
    monkeypatch.setattr(model, "MANAGER", manager)
    async with manager._request_lease.shared():
        with pytest.raises(HTTPException) as error:
            await model.unload_model()
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_unload_endpoint_returns_authoritative_unloaded_snapshot(monkeypatch):
    from app.api import model
    from app.inference import hotswap
    manager = InferenceManager()
    manager.state.loaded = True
    manager.backend = SimpleNamespace(manages_process=True, stop=AsyncMock())
    monkeypatch.setattr(model, "MANAGER", manager)
    monkeypatch.setattr(hotswap, "MANAGER", manager)
    result = await model.unload_model()
    assert result["loaded"] is False
    assert result["active_model"] is None
    assert result["manually_unloaded"] is True
    assert result["healthy"] is False


@pytest.mark.asyncio
async def test_lmstudio_activation_does_not_claim_downloaded_model_is_loaded(jarvis_env, monkeypatch):
    from app.inference import hotswap
    from app.inference.runtime_profiles import create_runtime_profile
    effective = settings()
    effective.inference.remote_model = "qwen-9b"
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    profile = create_runtime_profile(name="verify-native-load", model="qwen-9b", provider="lmstudio", endpoint="127.0.0.1:1234", is_local=True)
    monkeypatch.setattr(hotswap, "apply_runtime_profile_to_settings", AsyncMock(return_value=effective))
    ensure = AsyncMock(return_value={"ok": False, "detail": "Selected 9B model did not load"})
    monkeypatch.setattr("app.inference.lmstudio_server.ensure_local_lmstudio", ensure)
    load = AsyncMock()
    monkeypatch.setattr(hotswap.MANAGER, "load", load)
    save = []
    monkeypatch.setattr(hotswap, "save_settings", save.append)
    with pytest.raises(RuntimeError, match="9B model did not load"):
        await hotswap.activate_runtime_profile(profile)
    assert ensure.await_args.kwargs["model"] == "qwen-9b"
    load.assert_not_awaited()
    assert not save
