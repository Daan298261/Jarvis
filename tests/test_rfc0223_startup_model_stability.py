import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import AppSettings
from app.inference import backends, hotswap, manager as manager_module
from app.inference.manager import InferenceManager
from app.inference.runtime_profiles import RuntimeProfile


@pytest.fixture
def remote(monkeypatch):
    settings = AppSettings(inference={"backend": "remote", "port": 1235, "remote_model": "chosen"})
    manager = InferenceManager()
    probe = AsyncMock(return_value={"ok": True, "models": ["chosen", "other"], "n_ctx": 4096})
    monkeypatch.setattr(manager_module, "probe_remote_server", probe)
    monkeypatch.setattr(manager, "refresh_resources", AsyncMock())
    return manager, settings, probe


async def test_identical_remote_load_reuses_provider_even_with_smaller_live_context(remote):
    manager, settings, probe = remote
    await manager.load(settings)
    provider = manager.provider
    await manager.load(settings)
    assert manager.provider is provider
    assert probe.await_count == 1


@pytest.mark.parametrize("change", ["model", "port", "host", "force"])
async def test_endpoint_changes_and_force_do_not_reuse_old_provider(remote, change):
    manager, settings, probe = remote
    await manager.load(settings)
    provider = manager.provider
    updated = settings.model_copy(deep=True)
    if change == "model":
        updated.inference.remote_model = "other"
    elif change == "port":
        updated.inference.port = 1236
    elif change == "host":
        updated.inference.host = "localhost"
    await manager.load(updated, force=change == "force")
    assert manager.provider is not provider
    assert probe.await_count == 2
    assert manager.provider.model == updated.inference.remote_model


@pytest.mark.parametrize("cancel", [False, True])
async def test_load_failure_clears_loading_state_and_stale_provider(remote, monkeypatch, cancel):
    manager, settings, probe = remote
    error = asyncio.CancelledError() if cancel else RuntimeError("server failed")
    probe.side_effect = error
    with pytest.raises(type(error)):
        await manager.load(settings)
    assert not manager.state.loading
    assert not manager.state.loaded
    assert manager.provider is None
    assert manager.state.last_error


async def test_successful_custom_runtime_persists_path_and_restores_after_restart(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    settings = AppSettings()
    monkeypatch.setattr(hotswap, "load_settings", lambda: settings)
    monkeypatch.setattr(hotswap, "save_settings", config.save_settings)
    load = AsyncMock()
    monkeypatch.setattr(hotswap.MANAGER, "load", load)
    runtime = RuntimeProfile.from_dict({"id":"custom", "name":"custom", "provider":"llama.cpp", "gguf_path":str(tmp_path / "owner.gguf"), "context_limit":8192})
    await hotswap.activate_runtime_profile(runtime)
    restored = config.load_settings()
    assert restored.inference.gguf_path == runtime.gguf_path
    assert restored.inference.context_size == 8192
    profile = InferenceManager()._active_profile(restored)
    assert profile.absolute_path == runtime.gguf_path


async def test_failed_activation_does_not_replace_saved_selection(monkeypatch):
    settings = AppSettings(inference={"profile": "quality"})
    saved = []
    monkeypatch.setattr(hotswap, "load_settings", lambda: settings)
    monkeypatch.setattr(hotswap, "save_settings", saved.append)
    monkeypatch.setattr(hotswap.MANAGER, "load", AsyncMock(side_effect=RuntimeError("failed")))
    runtime = RuntimeProfile.from_dict({"id":"bad", "name":"bad", "provider":"llama.cpp", "model_profile":"fast"})
    with pytest.raises(RuntimeError):
        await hotswap.activate_runtime_profile(runtime)
    assert saved == []
    assert settings.inference.profile == "quality"


@pytest.mark.parametrize("status", [301, 401, 404, 503])
async def test_probe_rejects_error_and_redirect_responses(monkeypatch, status):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(backends.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"detail": "unavailable"})), **kw))
    result = await backends.probe_remote_server("127.0.0.1", 1235, retry=False)
    assert not result["ok"]


async def test_optional_startup_step_does_not_delay_event_loop(monkeypatch):
    from app import main
    entered = asyncio.Event()
    release = asyncio.Event()
    async def optional():
        entered.set()
        await release.wait()
    main._start_optional_step("test_optional", optional)
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert main._startup_tasks
    release.set()
    await asyncio.gather(*main._startup_tasks)


async def test_lmstudio_native_inventory_excludes_downloaded_models(monkeypatch):
    from app.inference import lmstudio_server as server
    client_type = httpx.AsyncClient
    body = {"models": [
        {"key": "downloaded", "type": "llm", "loaded_instances": []},
        {"key": "chosen", "type": "llm", "loaded_instances": [{"id": "chosen-instance"}]},
        {"key": "embed", "type": "embedding", "loaded_instances": [{"id": "embed-instance"}]},
    ]}
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kw))
    assert await server._loaded_model_ids("127.0.0.1", 1234) == {"chosen", "chosen-instance"}


@pytest.mark.parametrize("already_loaded", [False, True])
async def test_lmstudio_autoload_loads_saved_download_only_when_needed(monkeypatch, already_loaded):
    from types import SimpleNamespace
    from app.inference import lmstudio_server as server
    monkeypatch.setattr(server, "probe_remote_server", AsyncMock(return_value={"ok": True, "models": ["chosen"]}))
    inventory = AsyncMock(side_effect=[{"chosen"} if already_loaded else set(), {"chosen"}])
    monkeypatch.setattr(server, "_loaded_model_ids", inventory)
    monkeypatch.setattr(server, "lmstudio_cli", lambda: "lms")
    monkeypatch.setattr(server, "lmstudio_app_path", lambda: None)
    commands = []
    def cli(args, timeout):
        commands.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(server, "_run_cli", cli)
    result = await server.ensure_local_lmstudio(host="127.0.0.1", port=1234, model="chosen", context_size=8192)
    assert result["ok"]
    assert commands == ([] if already_loaded else [["lms", "load", "chosen", "-c", "8192", "-y"]])


def test_repeated_discovery_uses_bounded_cache(tmp_path, monkeypatch):
    from app.inference import qwen38_local as discovery
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(discovery, "_PATH_CACHE", None)
    monkeypatch.setattr(discovery, "models_dir", lambda: tmp_path)
    monkeypatch.setattr(discovery, "_lmstudio_root", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(discovery, "_scan_owner_gguf_paths", lambda: calls.append(1) or [tmp_path / "chosen.gguf"])
    assert discovery._owner_gguf_paths() == discovery._owner_gguf_paths()
    assert calls == [1]


async def test_model_catalog_scan_keeps_api_event_loop_available(monkeypatch):
    import threading
    from app.api import lmstudio
    entered = threading.Event()
    release = threading.Event()
    def slow_catalog(**kwargs):
        entered.set()
        release.wait(timeout=2)
        return {"profiles": []}
    monkeypatch.setattr(lmstudio, "build_catalog", slow_catalog)
    task = asyncio.create_task(lmstudio.get_catalog())
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
        assert not task.done()
        await asyncio.wait_for(asyncio.sleep(0), timeout=.1)
    finally:
        release.set()
        await task
