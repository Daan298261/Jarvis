"""Model lifecycle contracts: never mutate an unverified/occupied owner workload."""
import asyncio
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.inference import model_launch as ml, running_models as rm, ollama_runtime
from app.inference.manager import InferenceManager
from app.manager import main as manager_api


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    settings = AppSettings()
    settings.inference.auto_load = False
    manager = InferenceManager()
    monkeypatch.setattr("app.inference.manager.MANAGER", manager)
    monkeypatch.setattr(rm, "load_settings", lambda: settings)
    monkeypatch.setattr(ml, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(rm, "listener_inventory", lambda: {})
    monkeypatch.setattr(rm, "ollama_serves", lambda: [])
    monkeypatch.setattr(rm, "port_in_use", lambda port: False)
    monkeypatch.setattr(rm, "audit_control", Mock())
    monkeypatch.setattr(rm, "vram_snapshot", lambda: {"gpus": [{"free_mib": 24000}], "processes": []})
    runtime = rm.RunningModels(tmp_path / "choices.json")
    return runtime, settings, manager


@pytest.mark.parametrize("name,command,expected", [
    ("ollama.exe", [], "ollama"), ("LM Studio.exe", [], "lmstudio"),
    ("lms", [], "lmstudio"), ("llama-server.exe", [], "llama.cpp"),
    ("vllm", [], "vllm"), ("koboldcpp.exe", [], "koboldcpp"),
    ("oobabooga", [], "textgen"), ("text-generation-webui", [], "textgen"),
    ("Colibri.exe", [], "colibri"), ("sglang", [], "sglang"),
    ("python.exe", ["python", "-m", "vllm.entrypoints.openai.api_server"], "vllm"),
    ("python", ["python", "-m", "sglang.launch_server"], "sglang"),
    ("python", ["C:/oobabooga/server.py"], "textgen"),
    ("python", ["uvicorn", "app:app"], None),
    ("Cursor.exe", ["vllm.entrypoints"], None), ("Codex.exe", [], None),
    ("aider", [], None), ("Antigravity.exe", [], None),
    ("codex-rs.exe", [], None), ("ChatGPT.exe", [], None),
])
def test_process_classifier(name, command, expected):
    assert rm.process_kind(name, command) == expected


def test_arbitrary_listener_retains_identity_for_metadata_probe(monkeypatch):
    connection = SimpleNamespace(status=rm.psutil.CONN_LISTEN, pid=71,
        laddr=SimpleNamespace(ip="127.0.0.1", port=9876))
    process = Mock(pid=71)
    process.name.return_value = "python.exe"
    process.parents.return_value = []
    process.cmdline.return_value = ["python", "other-app.py"]
    process.create_time.return_value = 11
    monkeypatch.setattr(rm.psutil, "net_connections", lambda **kw: [connection])
    monkeypatch.setattr(rm.psutil, "Process", lambda pid: process)
    assert rm.listener_inventory()[9876] == {"pid": 71, "created": 11, "name": "python.exe", "kind": None, "host": "127.0.0.1"}


async def test_ollama_loaded_and_downloaded_are_distinct(monkeypatch):
    paths = []
    def handle(request):
        paths.append(request.url.path)
        assert request.method == "GET"
        return httpx.Response(200, json={"models": [
            {"name": "loaded", "size": 100, "size_vram": 80, "context_length": 2048}]
            if request.url.path == "/api/ps" else [{"name": "loaded"}, {"name": "downloaded"}]})
    mock_http(monkeypatch, handle)
    row = await rm.probe(11434, include_available=True)
    assert row["models"] == ["loaded"]
    assert [m["name"] for m in row["available_models"]] == ["loaded", "downloaded"]
    assert row["metadata"]["loaded"]["vram_bytes"] == 80
    assert row["metadata"]["loaded"]["context_size"] == 2048
    assert paths == ["/api/ps", "/api/tags"]


async def test_empty_ollama_is_a_start_target_but_not_a_use_offer(runtime, monkeypatch):
    instance, _, _ = runtime
    def handle(request):
        return httpx.Response(200, json={"models": [] if request.url.path == "/api/ps" else [{"name": "small"}]})
    mock_http(monkeypatch, handle)
    monkeypatch.setattr(rm, "KNOWN_PORTS", {11434})
    snapshot = await instance.scan(force=True)
    assert snapshot["servers"] == []
    assert snapshot["inventory"][0]["available_models"] == [{"name": "small"}]


@pytest.mark.parametrize("kind,port", [("vllm", 8000), ("sglang", 30000), ("koboldcpp", 5001),
                                       ("textgen", 5000), ("colibri", 18765), (None, 18766)])
async def test_openai_servers_extend_existing_remote_provider(runtime, monkeypatch, kind, port):
    instance, _, _ = runtime
    monkeypatch.setattr(rm, "listener_inventory", lambda: {port: {"pid": 10, "created": 1, "name": "python", "kind": kind}})
    monkeypatch.setattr(rm, "KNOWN_PORTS", set())
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "local-model"}]})
              if r.url.path == "/v1/models" else httpx.Response(404))
    snapshot = await instance.scan(force=True)
    row = next(row for row in snapshot["servers"] if row["port"] == port)
    assert row["backend"] == "remote" and not row["can_stop"]
    assert row["kind"] == (kind or "remote")


@pytest.mark.parametrize("bad", [{"models": "bad"}, {"models": [None, 1, {}]}, {"models": [{"name": 7}]}])
async def test_malformed_download_inventory_does_not_hide_loaded(monkeypatch, bad):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"models": [{"name": "loaded"}]} if r.url.path == "/api/ps" else bad))
    result = await rm.probe(11434, include_available=True)
    assert result["models"] == ["loaded"] and result["available_models"] == []


async def test_duplicate_serves_and_editor_ports_are_visible_or_excluded(runtime, monkeypatch):
    instance, _, _ = runtime
    monkeypatch.setattr(rm, "ollama_serves", lambda: [{"pid": 2}, {"pid": 3}])
    monkeypatch.setattr(rm, "listener_inventory", lambda: {8000: {"excluded": True}})
    probe = AsyncMock(return_value=None)
    monkeypatch.setattr(rm, "probe", probe)
    snapshot = await instance.scan(force=True)
    assert "Competing" in snapshot["diagnostics"][0]
    assert 8000 not in [call.args[0] for call in probe.call_args_list]


async def test_llama_props_are_external_and_stoppable(runtime, monkeypatch):
    instance, _, _ = runtime
    def handle(r):
        return httpx.Response(200, json={
            "/v1/models": {"data": [{"id": "alias"}]},
            "/props": {"model_path": "model.gguf", "total_slots": 1, "model_alias": "alias",
                       "default_generation_settings": {"n_ctx": 8192}},
            "/health": {"status": "ok"},
        }.get(r.url.path, {}))
    mock_http(monkeypatch, handle)
    monkeypatch.setattr(rm, "KNOWN_PORTS", {8080})
    monkeypatch.setattr(rm, "listener_inventory", lambda: {8080: {"pid": 8, "created": 1, "name": "llama-server.exe"}})
    row = (await instance.scan(force=True))["servers"][0]
    assert row["backend"] == "llama.cpp" and row["can_stop"]
    assert row["owner"] == "external"
    assert row["metadata"]["alias"]["context_size"] == 8192


@pytest.mark.parametrize("kv,factor", [("f16", 1), ("server", 1), ("q8_0", .53125), ("q4_0", .28125)])
def test_vram_estimate_includes_weights_kv_workspace(kv, factor):
    profile = {"context_size": 32768, "context_ceiling": 65536, "weight_mib": 12000, "kv_mib_per_1k_f16": 128}
    report = ml.budget_check(profile, ml.ModelStart(profile_id="x", kv_cache=kv), {"gpus": [{"free_mib": 16000}]})
    assert report["estimated_mib"] == round(12000 + 32 * 128 * factor + 1024)
    assert report["requires_confirmation"] == (report["estimated_mib"] > 16000)


def test_unknown_vram_and_context_ceiling_fail_closed():
    p = dict(ml.BUILTIN_LAUNCH_PROFILES[0])
    assert ml.budget_check(p, ml.ModelStart(profile_id="x"), {})["requires_confirmation"]
    with pytest.raises(ValueError, match="ceiling"):
        ml.budget_check(p, ml.ModelStart(profile_id="x", context_size=131072), {})


def test_nvidia_parser_handles_wddm_and_malformed_rows(monkeypatch):
    monkeypatch.setattr(ml.shutil, "which", lambda name: "smi")
    def run(args, **kw):
        assert kw["timeout"] == 3
        output = '0, GPU-1, RTX, 16384, 4096, 12288\nmalformed' if "--query-gpu=" in args[1] else 'GPU-1, 42, owner-model, [N/A]\nGPU-1, 43, second, 512\nbad'
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(ml.subprocess, "run", run)
    result = ml.vram_snapshot()
    assert result["gpus"][0]["free_mib"] == 12288
    assert result["processes"][0]["used_mib"] is None
    assert result["processes"][1]["used_mib"] == 512


def test_duplicate_server_guard_refuses_spawn_for_occupied_port(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="duplicate"):
        ollama_runtime._start_server("127.0.0.1", 11434)
    spawn.assert_not_called()


def test_duplicate_server_guard_refuses_spawn_for_existing_serve(monkeypatch):
    monkeypatch.setattr(rm, "port_in_use", lambda p: False)
    monkeypatch.setattr(rm, "ollama_serves", lambda: [{"pid": 1}])
    spawn = Mock()
    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="duplicate"):
        ollama_runtime._start_server("127.0.0.1", 11434)
    spawn.assert_not_called()


@pytest.fixture
def startable(runtime, monkeypatch):
    instance, settings, manager = runtime
    profile = dict(ml.BUILTIN_LAUNCH_PROFILES[0], id="small", model="small", weight_mib=300, context_size=2048)
    monkeypatch.setattr(instance, "profiles", AsyncMock(return_value={"profiles": [profile]}))
    monkeypatch.setattr(instance, "scan", AsyncMock(return_value={"servers": []}))
    return instance, settings, manager, profile


async def test_start_confirmation_and_busy_lease_block_launch(startable, monkeypatch):
    instance, _, manager, _ = startable
    launch = AsyncMock()
    monkeypatch.setattr(instance, "_launch_profile", launch)
    with pytest.raises(ValueError, match="confirmation"):
        await instance.start_model(ml.ModelStart(profile_id="small"))
    async with manager._request_lease.shared():
        with pytest.raises(ValueError, match="answering"):
            await instance.start_model(ml.ModelStart(profile_id="small", confirm=True))
    launch.assert_not_called()


async def test_start_budget_preview_does_not_mutate_and_requires_override(startable, monkeypatch):
    instance, _, _, _ = startable
    launch = AsyncMock()
    monkeypatch.setattr(instance, "_launch_profile", launch)
    monkeypatch.setattr(rm, "vram_snapshot", lambda: {"gpus": [{"free_mib": 100}]})
    preview = await instance.start_model(ml.ModelStart(profile_id="small"), preview=True)
    assert preview["requires_confirmation"]
    launch.assert_not_called()
    with pytest.raises(ValueError, match="confirm_over_budget"):
        await instance.start_model(ml.ModelStart(profile_id="small", confirm=True))
    await instance.start_model(ml.ModelStart(profile_id="small", confirm=True, confirm_over_budget=True))
    launch.assert_awaited_once()


async def test_start_reuses_ollama_with_empty_prompt_and_idle_policy(startable, monkeypatch):
    instance, _, _, profile = startable
    instance.inventory = [{"port": 11434, "backend": "ollama", "endpoint": "http://127.0.0.1:11434",
                           "available_models": [{"name": "small"}]}]
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    spawn = Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr(ollama_runtime, "_start_server", spawn)
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    posts = []
    def handle(r):
        posts.append(json.loads(r.content))
        return httpx.Response(200, json={"done": True})
    mock_http(monkeypatch, handle)
    await instance.start_model(ml.ModelStart(profile_id="small", confirm=True, context_size=4096))
    assert posts == [{"model": "small", "prompt": "", "stream": False, "keep_alive": "300s", "options": {"num_ctx": 4096}}]
    spawn.assert_not_called()


async def test_ollama_option_changes_require_owner_restart(startable, monkeypatch):
    instance, _, _, profile = startable
    instance.inventory = [{"port": 11434, "backend": "ollama", "available_models": [{"name": "small"}]}]
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    with pytest.raises(ValueError, match="restart required"):
        await instance._launch_profile(profile, ml.ModelStart(profile_id="small", kv_cache="q8_0"), 2048)


async def test_missing_model_never_pulls_or_loads_something_else(startable, monkeypatch):
    instance, _, _, profile = startable
    instance.inventory = [{"port": 11434, "backend": "ollama", "available_models": [{"name": "owners-model"}]}]
    with pytest.raises(ValueError, match="not downloaded"):
        await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 2048)


async def test_new_ollama_receives_only_server_options(startable, monkeypatch):
    instance, _, _, profile = startable
    spawn = Mock()
    monkeypatch.setattr(ollama_runtime, "_start_server", spawn)
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={"available_models": [{"name": "small"}], "endpoint": "http://127.0.0.1:11434"}))
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"done": True}))
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small", kv_cache="q4_0", flash_attention="on"), 2048)
    spawn.assert_called_once_with("127.0.0.1", 11434, env_overrides={"OLLAMA_KV_CACHE_TYPE": "q4_0", "OLLAMA_FLASH_ATTENTION": "1"})


async def test_lms_starts_only_when_down_and_passes_context_ttl(startable, monkeypatch):
    instance, _, _, profile = startable
    profile.update(backend="lmstudio", port=1234)
    run = AsyncMock()
    monkeypatch.setattr(rm, "run_lms", run)
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 8192)
    assert [c.args[0] for c in run.call_args_list] == [["server", "start", "--port", "1234"],
        ["load", "small", "--context-length", "8192", "-y", "--ttl", "300"]]
    run.reset_mock()
    instance.inventory = [{"port": 1234, "backend": "lmstudio"}]
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 8192)
    assert run.call_count == 1 and run.call_args.args[0][0] == "load"


async def test_llama_spawn_is_loopback_with_cache_flash_and_moe(startable, monkeypatch, tmp_path):
    instance, _, _, profile = startable
    profile.update(backend="llama.cpp", port=8080, binary="llama-server", model="35b.gguf", n_cpu_moe=32)
    monkeypatch.setattr("app.config.logs_dir", lambda: tmp_path)
    spawn = Mock(return_value=SimpleNamespace(pid=41))
    monkeypatch.setattr(rm.subprocess, "Popen", spawn)
    monkeypatch.setattr(rm.psutil, "Process", lambda p: SimpleNamespace(create_time=lambda: 1))
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small", kv_cache="q4_0", n_cpu_moe=20), 131072)
    args = spawn.call_args.args[0]
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--cache-type-k") + 1] == "q4_0"
    assert args[args.index("--n-cpu-moe") + 1] == "20"
    assert instance._launched[8080] == {"pid": 41, "created": 1}


@pytest.mark.parametrize("backend", ["ollama", "lmstudio", "llama.cpp"])
async def test_occupied_unidentified_port_never_spawns(startable, monkeypatch, backend):
    instance, _, _, profile = startable
    profile["backend"] = backend
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    with pytest.raises(ValueError, match="already in use"):
        await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 2048)


@pytest.mark.parametrize("backend,source", [("ollama", "ollama_ps"), ("lmstudio", "lmstudio_loaded_instances"), ("lmstudio", "lmstudio_v0_loaded")])
async def test_native_unload_and_verification(monkeypatch, backend, source):
    requests = []
    def handle(r):
        requests.append(r)
        return httpx.Response(200, json={"models": []} if "v0" not in source else {"data": []})
    mock_http(monkeypatch, handle)
    run = AsyncMock()
    monkeypatch.setattr(rm, "run_lms", run)
    row = {"port": 11434 if backend == "ollama" else 1234, "backend": backend, "model": "small",
           "source": source, "instance_ids": ["small"] if "instances" in source else []}
    await rm.unload_native(row)
    assert requests[-1].method == "GET"
    if backend == "ollama":
        assert json.loads(requests[0].content) == {"model": "small", "keep_alive": 0}
    elif "v0" in source:
        run.assert_awaited_once_with(["unload", "small"])
    else:
        assert json.loads(requests[0].content) == {"instance_id": "small"}


def test_verified_llama_escalates_only_after_timeout(monkeypatch):
    process = Mock()
    process.name.return_value = "llama-server.exe"
    process.create_time.return_value = 1
    process.net_connections.return_value = [SimpleNamespace(status=rm.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=8080))]
    process.wait.side_effect = [rm.psutil.TimeoutExpired(5), None]
    monkeypatch.setattr(rm.psutil, "Process", lambda p: process)
    rm.stop_listener({"port": 8080, "process": {"pid": 42, "created": 1, "name": "llama-server.exe"}})
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


async def test_start_api_requires_confirmation(monkeypatch):
    from app.api import model
    app = FastAPI()
    app.include_router(model.router)
    start = AsyncMock()
    monkeypatch.setattr(model.RUNNING_MODELS, "start_model", start)
    with TestClient(app) as client:
        assert client.post("/api/model/running/start", json={"profile_id": "small"}).status_code == 400
    start.assert_not_called()


@pytest.fixture
def manager_client(tmp_path, monkeypatch):
    monkeypatch.setattr(manager_api, "_root", lambda: tmp_path)
    client = TestClient(manager_api.app)
    session = client.get("/api/manager/v1/session").json()
    return client, {session["header"]: session["token"]}


@pytest.mark.parametrize("path,body", [("scan", {}), ("start", {"profile_id": "small", "confirm": True}),
    ("start/preview", {"profile_id": "small"}), ("a" * 24 + "/choice", {"action": "stop", "confirm": True})])
def test_manager_model_controls_require_token(manager_client, monkeypatch, path, body):
    client, headers = manager_client
    core = AsyncMock()
    monkeypatch.setattr(manager_api, "_model_core", core)
    assert client.post("/api/manager/v1/models/" + path, json=body).status_code == 403
    core.assert_not_called()


def test_manager_start_requires_confirmation(manager_client, monkeypatch):
    client, headers = manager_client
    core = AsyncMock()
    monkeypatch.setattr(manager_api, "_model_core", core)
    assert client.post("/api/manager/v1/models/start", json={"profile_id": "small"}, headers=headers).status_code == 400
    core.assert_not_called()


def test_manager_proxy_and_offline_start_refusal(manager_client, monkeypatch):
    client, headers = manager_client
    core = AsyncMock(return_value={"servers": []})
    monkeypatch.setattr(manager_api, "_model_core", core)
    assert client.get("/api/manager/v1/models").json()["core_available"]
    result = client.post("/api/manager/v1/models/start", json={"profile_id": "small", "confirm": True}, headers=headers)
    assert result.status_code == 200
    assert core.call_args.args[:2] == ("POST", "/start")
    core.return_value = None
    assert client.post("/api/manager/v1/models/start", json={"profile_id": "small", "confirm": True}, headers=headers).status_code == 409


@pytest.mark.parametrize("core_process,occupied,expected", [(False, False, 200), (True, False, 409), (False, True, 409)])
def test_manager_offline_stop_only_after_proving_core_absent(manager_client, monkeypatch, core_process, occupied, expected):
    client, headers = manager_client
    monkeypatch.setattr(manager_api, "_model_core", AsyncMock(return_value=None))
    monkeypatch.setattr(manager_api, "_managed_process_running", lambda: core_process)
    monkeypatch.setattr(rm, "port_in_use", lambda p: occupied)
    stop = AsyncMock(return_value={"servers": []})
    monkeypatch.setattr(rm.RUNNING_MODELS, "stop_offline", stop)
    response = client.post("/api/manager/v1/models/" + "a" * 24 + "/choice", json={"action": "stop", "confirm": True}, headers=headers)
    assert response.status_code == expected
    assert stop.call_count == (expected == 200)


async def test_manager_rejects_remote_clients_without_discovery():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=manager_api.app, client=("192.0.2.10", 1234)), base_url="http://manager") as client:
        assert (await client.get("/api/manager/v1/models")).status_code == 403


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("late"), httpx.ConnectTimeout("late")])
async def test_core_timeouts_never_enable_offline_fallback(monkeypatch, failure):
    mock_http(monkeypatch, lambda r: (_ for _ in ()).throw(failure))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await manager_api._model_core("GET", "")
    assert exc.value.status_code == 503


def test_local_profiles_reuse_configured_data_and_hide_missing_moe(runtime, monkeypatch, tmp_path):
    monkeypatch.setattr("app.inference.runtime_profiles.list_runtime_profiles", lambda: [])
    config = [{"id": "moe", "backend": "llama.cpp", "model": str(tmp_path / "missing.gguf"), "binary": str(tmp_path / "missing.exe"), "port": 8080}]
    (tmp_path / "model-launch-profiles.json").write_text(json.dumps(config))
    profiles = ml.launch_profiles([{"backend": "ollama", "port": 11434, "available_models": [{"name": "small", "size": 500 * 1024**2}]}])
    assert not any(p["id"] == "moe" for p in profiles)
    small = next(p for p in profiles if p["model"] == "small")
    assert small["weight_mib"] == 500
    assert small["server_restart_required_for_options"]


@pytest.mark.parametrize("core_absent,busy,backend,allowed", [(True, False, "ollama", True),
    (False, False, "ollama", False), (True, True, "ollama", False),
    (True, False, "remote", False), (True, False, "lmstudio", True)])
async def test_offline_service_revalidates_core_and_only_unloads_native(runtime, monkeypatch, core_absent, busy, backend, allowed):
    instance, _, _ = runtime
    instance.rows = [{"id": "a", "backend": backend, "model": "small", "port": 11434, "busy": busy, "process": {"pid": 1}}]
    monkeypatch.setattr(instance, "scan", AsyncMock(return_value={"servers": []}))
    unload = AsyncMock()
    monkeypatch.setattr(rm, "unload_native", unload)
    absent = AsyncMock(return_value=core_absent)
    if allowed:
        await instance.stop_offline("a", confirm=True, core_absent=absent)
    else:
        with pytest.raises(ValueError):
            await instance.stop_offline("a", confirm=True, core_absent=absent)
    assert unload.call_count == allowed


async def test_stale_offline_identity_never_unloads(runtime, monkeypatch):
    instance, _, _ = runtime
    instance.rows = [{"id": "a", "process": {"pid": 1}}]
    async def changed(**kw):
        instance.rows = [{"id": "a", "process": {"pid": 2}}]
    monkeypatch.setattr(instance, "scan", changed)
    unload = AsyncMock()
    monkeypatch.setattr(rm, "unload_native", unload)
    with pytest.raises(ValueError, match="changed"):
        await instance.stop_offline("a", confirm=True, core_absent=AsyncMock(return_value=True))
    unload.assert_not_called()


def test_pid_identity_rechecked_before_kill(monkeypatch):
    process = Mock()
    process.name.return_value = "llama-server.exe"
    process.create_time.side_effect = [1, 2]
    process.net_connections.return_value = [SimpleNamespace(status=rm.psutil.CONN_LISTEN, laddr=SimpleNamespace(port=8080))]
    process.wait.side_effect = rm.psutil.TimeoutExpired(5)
    monkeypatch.setattr(rm.psutil, "Process", lambda p: process)
    with pytest.raises(ValueError, match="changed"):
        rm.stop_listener({"port": 8080, "process": {"pid": 42, "created": 1, "name": "llama-server.exe"}})
    process.kill.assert_not_called()


async def test_builtin_ollama_name_accepts_latest_tag(startable, monkeypatch):
    instance, _, _, profile = startable
    instance.inventory = [{"backend": "ollama", "port": 11434, "endpoint": "http://127.0.0.1:11434",
                           "available_models": [{"name": "small:latest"}]}]
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"done": True}))
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 2048)


async def test_llama_failed_readiness_cleans_up_only_its_own_child(startable, monkeypatch, tmp_path):
    instance, _, _, profile = startable
    profile.update(backend="llama.cpp", port=8080, binary="llama-server", model="small.gguf")
    process = Mock(pid=41)
    process.poll.return_value = None
    monkeypatch.setattr("app.config.logs_dir", lambda: tmp_path)
    monkeypatch.setattr(rm.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(rm.psutil, "Process", lambda p: SimpleNamespace(create_time=lambda: 1))
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(side_effect=ValueError("not ready")))
    with pytest.raises(ValueError, match="not ready"):
        await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 2048)
    process.terminate.assert_called_once()
    assert not instance._launched


async def test_discovery_keeps_health_event_loop_responsive(runtime, monkeypatch):
    instance, _, _ = runtime
    entered, release = __import__("threading").Event(), __import__("threading").Event()
    def inventory():
        entered.set()
        release.wait(timeout=2)
        return {}
    monkeypatch.setattr(rm, "listener_inventory", inventory)
    monkeypatch.setattr(rm, "probe", AsyncMock(return_value=None))
    scan = asyncio.create_task(instance.scan(force=True))
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait), 1)
        # A health request coroutine can return while OS enumeration remains blocked.
        assert await asyncio.wait_for(asyncio.sleep(0, result="healthy"), .2) == "healthy"
        assert not scan.done()
    finally:
        release.set()
        await scan


def test_lms_command_failure_is_reported(runtime, monkeypatch):
    monkeypatch.setattr("app.inference.lmstudio_server.lmstudio_cli", lambda: "lms")
    monkeypatch.setattr(rm.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr="model missing"))
    with pytest.raises(ValueError, match="model missing"):
        asyncio.run(rm.run_lms(["load", "missing"]))


async def test_discovered_llama_use_does_not_take_process_ownership(runtime, monkeypatch):
    instance, _, manager = runtime
    monkeypatch.setattr(rm, "probe", AsyncMock(return_value={"port": 8080, "backend": "llama.cpp", "models": ["small"]}))
    monkeypatch.setattr(rm, "KNOWN_PORTS", {8080})
    monkeypatch.setattr(rm, "save_settings", Mock())
    monkeypatch.setattr(manager, "refresh_resources", AsyncMock())
    monkeypatch.setattr("app.inference.manager.probe_remote_server", AsyncMock(return_value={"ok": True, "models": ["small"], "n_ctx": 4096}))
    monkeypatch.setattr("app.persona.owner_chat.rebind_owner_conversations_after_hotswap", Mock())
    await instance.scan(force=True)
    await instance.decide(instance.rows[0]["id"], "use")
    assert rm.save_settings.call_args.args[0].inference.backend == "remote"
    assert not manager.state.manages_process and manager.state.loaded


async def test_listener_coverage_is_capped_and_annotated(runtime, monkeypatch):
    instance, _, _ = runtime
    inventory = {port: {"pid": port, "name": "python", "created": 1} for port in range(20000, 20100)}
    monkeypatch.setattr(rm, "listener_inventory", lambda: inventory)
    probe = AsyncMock(return_value=None)
    monkeypatch.setattr(rm, "probe", probe)
    result = await instance.scan(force=True)
    assert probe.call_count <= 64
    assert any("capped" in line for line in result["diagnostics"])


def test_malformed_profile_weight_is_unknown_not_zero_memory(runtime, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.list_runtime_profiles", lambda: [])
    profiles = ml.launch_profiles([{"backend": "ollama", "port": 11434, "available_models": [{"name": "small", "size": "not-a-number"}]}])
    profile = next(p for p in profiles if p["model"] == "small")
    report = ml.budget_check(profile, ml.ModelStart(profile_id=profile["id"]), {"gpus": [{"free_mib": 24000}]})
    assert report["estimated_mib"] is None and report["requires_confirmation"]


async def test_existing_ollama_startup_waits_without_crashing_or_spawning(monkeypatch):
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", AsyncMock(return_value={"ok": False}))
    monkeypatch.setattr(ollama_runtime, "ollama_cli", lambda: "ollama")
    monkeypatch.setattr(ollama_runtime, "_start_server", Mock(side_effect=ollama_runtime.OllamaAlreadyRunning("already running")))
    wait = AsyncMock(return_value={"ok": True, "models": ["small"]})
    monkeypatch.setattr(ollama_runtime, "_wait_until_up", wait)
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", AsyncMock(return_value={"ok": True}))
    result = await ollama_runtime.ensure_local_ollama(host="127.0.0.1", port=11434, model="small", pull_if_missing=False)
    assert result["ok"]
    wait.assert_awaited_once()


def test_configured_lmstudio_is_startable_when_native_server_is_down(runtime, monkeypatch):
    configured = SimpleNamespace(id="studio", label="Owner studio model", provider="lmstudio",
        endpoint="127.0.0.1:1234", model="owner/model", context_limit=16384, gguf_path="")
    monkeypatch.setattr("app.inference.runtime_profiles.list_runtime_profiles", lambda: [configured])
    monkeypatch.setattr("app.inference.lmstudio_server.lmstudio_cli", lambda: "lms")
    profiles = ml.launch_profiles([])
    profile = next(p for p in profiles if p["id"] == "runtime-studio")
    assert profile["model"] == "owner/model" and profile["backend"] == "lmstudio"
    assert profile["context_size"] == 16384


# --- Tray app / duplicate-serve guard (VRPC: bare serve at boot + tray autostart retry loop) ---

@pytest.fixture
def free_port_no_ollama(monkeypatch):
    monkeypatch.setattr(rm, "port_in_use", lambda p: False)
    monkeypatch.setattr(rm, "ollama_serves", lambda: [])
    monkeypatch.setattr(ollama_runtime, "ollama_tray_running", lambda: [])
    monkeypatch.setattr(ollama_runtime, "ollama_cli", lambda: "C:/Ollama/ollama.exe")
    spawn = Mock()
    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", spawn)
    return spawn


def test_installed_tray_app_is_launched_instead_of_bare_serve(free_port_no_ollama, monkeypatch):
    monkeypatch.setattr(ollama_runtime, "ollama_tray_app", lambda: "C:/Ollama/ollama app.exe")
    assert ollama_runtime._start_server("127.0.0.1", 11434) == "tray-app"
    argv = free_port_no_ollama.call_args.args[0]
    assert argv == ["C:/Ollama/ollama app.exe"] and "serve" not in argv
    free_port_no_ollama.assert_called_once()


def test_bare_serve_only_without_tray_app_or_on_custom_port(free_port_no_ollama, monkeypatch):
    monkeypatch.setattr(ollama_runtime, "ollama_tray_app", lambda: None)
    assert ollama_runtime._start_server("127.0.0.1", 11434) == "serve"
    assert free_port_no_ollama.call_args.args[0] == ["C:/Ollama/ollama.exe", "serve"]
    free_port_no_ollama.reset_mock()
    monkeypatch.setattr(ollama_runtime, "ollama_tray_app", lambda: "C:/Ollama/ollama app.exe")
    assert ollama_runtime._start_server("127.0.0.1", 11500) == "serve"


def test_running_tray_app_means_pending_server_never_spawn(free_port_no_ollama, monkeypatch):
    monkeypatch.setattr(ollama_runtime, "ollama_tray_running", lambda: [27892])
    monkeypatch.setattr(ollama_runtime, "ollama_tray_app", lambda: "C:/Ollama/ollama app.exe")
    with pytest.raises(ollama_runtime.OllamaAlreadyRunning):
        ollama_runtime._start_server("127.0.0.1", 11434)
    free_port_no_ollama.assert_not_called()


def test_autostart_detection_is_read_only(monkeypatch, tmp_path):
    startup = tmp_path / "Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True)
    shortcut = startup / "Ollama.lnk"
    shortcut.write_bytes(b"lnk")
    (startup / "Other.lnk").write_bytes(b"x")
    monkeypatch.setattr(ollama_runtime.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    found = ollama_runtime.ollama_autostart()
    assert str(shortcut) in found and not any("Other" in f for f in found)
    assert shortcut.read_bytes() == b"lnk"


def test_port_conflict_loop_detected_from_recent_log_tail(monkeypatch, tmp_path):
    log_file = tmp_path / "server.log"
    log_file.write_text("old line\n" + "Error: listen tcp 127.0.0.1:11434: bind: Only one usage of each socket address\n" * 10)
    monkeypatch.setattr(ollama_runtime, "ollama_server_log", lambda: log_file)
    conflict = ollama_runtime.ollama_port_conflict()
    assert conflict["recent_conflicts"] == 10
    log_file.write_text("time=... msg=\"Listening on 127.0.0.1:11434\"\n")
    assert ollama_runtime.ollama_port_conflict() is None


async def test_scan_reports_tray_retry_loop_diagnostic(runtime, monkeypatch, tmp_path):
    instance, _, _ = runtime
    monkeypatch.setattr(rm, "ollama_serves", lambda: [{"pid": 2176, "created": 1.0}])
    monkeypatch.setattr(ollama_runtime, "ollama_port_conflict",
                        lambda: {"log": "server.log", "log_bytes": 68 * 1024 * 1024, "recent_conflicts": 40})
    monkeypatch.setattr(ollama_runtime, "ollama_tray_running", lambda: [27892])
    monkeypatch.setattr(ollama_runtime, "ollama_autostart", lambda: ["Startup/Ollama.lnk"])
    monkeypatch.setattr(rm, "probe", AsyncMock(return_value=None))
    result = await instance.scan(force=True)
    text = " ".join(result["diagnostics"])
    assert "2176" in text and "68 MB" in text and "will not start another server" in text


def test_pinned_keep_alive_is_detected():
    assert rm.ollama_pinned("2319-02-20T03:37:31.264628907+01:00")
    assert not rm.ollama_pinned("2026-11-10T04:05:00+01:00")
    assert not rm.ollama_pinned(None)
    assert not rm.ollama_pinned("0001-01-01T00:00:00Z")


async def test_ollama_loaded_metadata_marks_pinned(monkeypatch):
    def handle(request):
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b", "model": "qwen3.5:4b",
                "size_vram": 3079961312, "expires_at": "2319-02-20T03:37:31+01:00"}]})
        return httpx.Response(404)
    mock_http(monkeypatch, handle)
    row = await rm.probe(11434)
    assert row["metadata"]["qwen3.5:4b"]["pinned"] is True


@pytest.mark.parametrize("keep_warm,expected", [(False, "300s"), (True, "-1")])
async def test_a_saved_server_keep_alive_choice_migrates_to_the_keep_warm_policy(startable, monkeypatch, tmp_path,
                                                                                   keep_warm, expected):
    """CoS ruling (#690 x #691): Start has no ``server`` keep-alive option. A cached request or a saved launch profile
    that still carries it is migrated: every Ollama request sends the Keep warm value ("300s" off, "-1" on)."""
    from app.inference import keep_alive

    monkeypatch.setattr("app.config.settings_path", lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(json.dumps({"inference": {"keep_warm": keep_warm}}), encoding="utf-8")
    keep_alive._cache = None
    instance, _, _, profile = startable
    instance.inventory = [{"port": 11434, "backend": "ollama", "endpoint": "http://127.0.0.1:11434",
                           "available_models": [{"name": "small"}]}]
    monkeypatch.setattr(rm, "port_in_use", lambda p: True)
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    posts = []
    mock_http(monkeypatch, lambda r: posts.append(json.loads(r.content)) or httpx.Response(200, json={"done": True}))
    legacy = ml.ModelStart.model_validate({"profile_id": "small", "keep_alive": "server"})
    assert "keep_alive" not in legacy.model_dump()
    try:
        await instance._launch_profile(profile, legacy, 2048)
    finally:
        keep_alive._cache = None
    assert posts[0]["keep_alive"] == expected
    saved = [{"id": "local", "label": "x", "backend": "ollama", "model": "small", "port": 11434,
              "context_size": 2048, "context_ceiling": 4096, "keep_alive": "server", "keep_alive_options": ["server"]}]
    (tmp_path / "model-launch-profiles.json").write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr("app.inference.runtime_profiles.list_runtime_profiles", lambda: [])
    migrated = next(p for p in ml.launch_profiles([]) if p["id"] == "local")
    assert "keep_alive" not in migrated and "keep_alive_options" not in migrated


async def test_unload_of_pinned_ollama_model_sends_keep_alive_zero(monkeypatch, runtime):
    posts = []
    def handle(request):
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})
        return httpx.Response(200, json={"models": []})
    mock_http(monkeypatch, handle)
    await rm.unload_native({"backend": "ollama", "port": 11434, "model": "qwen3.5:4b",
                            "base_url": "http://127.0.0.1:11434/v1"})
    assert posts == [{"model": "qwen3.5:4b", "keep_alive": 0}]


async def test_start_adopts_tray_server_that_is_still_starting(startable, monkeypatch):
    instance, _, _, profile = startable
    monkeypatch.setattr(ollama_runtime, "_start_server",
                        Mock(side_effect=ollama_runtime.OllamaAlreadyRunning("tray starting")))
    wait = AsyncMock(return_value={"available_models": [{"name": "small"}], "endpoint": "http://127.0.0.1:11434"})
    monkeypatch.setattr(instance, "_wait_server", wait)
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"done": True}))
    await instance._launch_profile(profile, ml.ModelStart(profile_id="small"), 2048)
    assert wait.await_args_list[0].kwargs.get("timeout") == 60


def test_tray_running_but_server_owned_by_other_parent_is_explained(monkeypatch):
    monkeypatch.setattr(ollama_runtime, "ollama_tray_running", lambda: [27892])
    monkeypatch.setattr(ollama_runtime, "ollama_port_conflict", lambda: None)
    monkeypatch.setattr(ollama_runtime, "ollama_autostart", lambda: [])
    monkeypatch.setattr(rm, "_ancestor_names", lambda pid: [(12876, "python.exe"), (100, "explorer.exe")])
    notes = rm.ollama_diagnostics([], {"pid": 2176, "name": "ollama.exe"})
    assert len(notes) == 1 and "PID 2176" in notes[0] and "python.exe (PID 12876)" in notes[0]
    monkeypatch.setattr(rm, "_ancestor_names", lambda pid: [(27892, "ollama app.exe")])
    assert rm.ollama_diagnostics([], {"pid": 2176, "name": "ollama.exe"}) == []
