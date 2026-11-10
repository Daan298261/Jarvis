"""#690 x #691: a model the Model Manager (RFC-0247) starts is an ANZU load in the one ledger (``LOADED``).

Start records it exactly once, lifts an Unload hold (an explicit Load) and takes its keep-alive / TTL from
``keep_alive.py`` (no ``server`` choice: CoS ruling); Unload-all (200 / 207 / 409) and the idle timer release it;
a Manager Stop removes it from the ledger; ``bgm-ingest-9b`` is never started.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import httpx
import psutil
import pytest

from app.config import AppSettings
from app.inference import keep_warm_release, model_launch as ml, running_models as rm
from app.inference.idle_unload import IdleUnload
from app.inference.keep_alive import request_extras
from app.inference.loaded_models import LLAMA_SERVER, LMSTUDIO, LOADED, OLLAMA
from app.inference.manager import MANAGER
from tests.test_keep_warm_idle_unload import (  # noqa: F401  (clean_state is an autouse fixture)
    FOREIGN, FakeServers, api_client, clean_state, settings_with, write_settings,
)

MODEL = "qwen3.5:4b"
REAL_CLIENT = httpx.AsyncClient


def mock_http(monkeypatch, handler):
    """Requests the running-models module builds go to ``handler``; a client given its own transport keeps it."""
    monkeypatch.setattr(rm.httpx, "AsyncClient",
                        lambda **kw: REAL_CLIENT(**{"transport": httpx.MockTransport(handler), **kw}))


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A RunningModels with one launch profile; discovery and VRAM are stubbed, the ledger and helpers are real."""
    settings = AppSettings()
    settings.inference.auto_load = False
    instance = rm.RunningModels(tmp_path / "choices.json")
    profile = dict(ml.BUILTIN_LAUNCH_PROFILES[0], id="p", model=MODEL, weight_mib=300, context_size=2048)
    monkeypatch.setattr(rm, "load_settings", lambda: settings)
    monkeypatch.setattr(rm, "audit_control", Mock())
    monkeypatch.setattr(rm, "port_in_use", lambda port: True)
    monkeypatch.setattr(rm, "vram_snapshot", lambda: {"gpus": [{"free_mib": 24000}], "processes": []})
    monkeypatch.setattr(rm, "RUNNING_MODELS", instance)
    monkeypatch.setattr(instance, "profiles", AsyncMock(return_value={"profiles": [profile]}))
    monkeypatch.setattr(instance, "scan", AsyncMock(return_value={"servers": []}))
    monkeypatch.setattr(instance, "_wait_server", AsyncMock(return_value={}))
    instance.inventory = [{"port": 11434, "backend": "ollama", "endpoint": "http://127.0.0.1:11434",
                           "available_models": [{"name": MODEL}]}]
    return instance, profile


def ollama_posts(monkeypatch) -> list[dict]:
    posts: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})
    mock_http(monkeypatch, handle)
    return posts


async def test_an_ollama_model_started_by_the_manager_is_in_the_ledger_once_and_unload_all_releases_it(manager, monkeypatch):
    instance, _ = manager
    posts = ollama_posts(monkeypatch)
    MANAGER.state.manually_unloaded = True  # the owner pressed Unload earlier
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True, context_size=4096))
    assert posts == [{"model": MODEL, "prompt": "", "stream": False, "options": {"num_ctx": 4096}, "keep_alive": "300s"}]
    assert MANAGER.state.manually_unloaded is False, "an owner Start is an explicit Load: it lifts the Unload hold"
    [entry] = LOADED.entries()
    assert (entry.backend, entry.model, entry.port, entry.idle_policy) == (OLLAMA, MODEL, 11434, True)

    # Starting it again, and the owner's Use attaching to it, never add a second entry.
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    MANAGER.state.backend, MANAGER.state.remote_model, MANAGER.state.loaded = OLLAMA, MODEL, True
    MANAGER._register_loaded(attach=True)
    assert len(LOADED.entries()) == 1
    MANAGER.state.loaded = False

    servers = FakeServers(ollama=[MODEL, FOREIGN]).install(monkeypatch)
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 200, response.text
    assert [(r["model"], r["verified"]) for r in response.json()["results"]] == [(MODEL, True)]
    assert servers.ollama == [FOREIGN] and LOADED.entries() == []
    async with api_client() as client:  # nothing left that ANZU loaded: 409, nothing attempted
        assert (await client.post("/api/model/unload-all")).status_code == 409


async def test_unload_all_reaches_a_manager_started_ollama_on_a_non_default_port_and_reports_207_per_model(manager, monkeypatch):
    instance, profile = manager
    profile["port"] = 11500
    instance.inventory = [{"port": 11500, "backend": "ollama", "endpoint": "http://127.0.0.1:11500",
                           "available_models": [{"name": MODEL}]}]
    ollama_posts(monkeypatch)
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    resident = {11500: [MODEL]}
    stuck = {"value": True}

    def handler(request: httpx.Request) -> httpx.Response:
        port, path = request.url.port, request.url.path
        if port not in resident:
            raise httpx.ConnectError("refused", request=request)
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": n} for n in resident[port]]})
        body = json.loads(request.content)
        assert body["keep_alive"] == 0 and body["model"] == MODEL
        if not stuck["value"]:
            resident[port].remove(MODEL)
        return httpx.Response(200, json={"done": True})
    monkeypatch.setattr(keep_warm_release, "_client", lambda key="": httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    async with api_client() as client:
        first = await client.post("/api/model/unload-all")
        assert first.status_code == 207
        assert [(r["model"], r["verified"]) for r in first.json()["results"]] == [(MODEL, False)]
        assert len(LOADED.entries()) == 1, "a failed release keeps its one entry"
        stuck["value"] = False
        second = await client.post("/api/model/unload-all")
    assert second.status_code == 200 and resident[11500] == [] and LOADED.entries() == []


@pytest.mark.parametrize("keep_warm,expected", [(False, "300s"), (True, "-1")])
async def test_start_sends_the_keep_warm_value_and_the_idle_timer_releases_only_ollama_lm_studio_starts(
        manager, monkeypatch, tmp_path, keep_warm, expected):
    """CoS ruling: no ``server`` keep-alive choice; Start always sends the Keep warm value, and a started Ollama
    model idles out like any ANZU load. A Manager-spawned llama-server (no per-turn clock) never does."""
    instance, _ = manager
    write_settings(tmp_path, keep_warm=keep_warm)
    posts = ollama_posts(monkeypatch)
    await instance.start_model(ml.ModelStart.model_validate({"profile_id": "p", "confirm": True, "keep_alive": "server"}))
    assert posts[0]["keep_alive"] == expected
    assert request_extras("http://127.0.0.1:11434/v1", MODEL) == {"keep_alive": expected}
    LOADED.record(LLAMA_SERVER, "/models/m.gguf", port=8080, idle_policy=False)

    released: list = []

    async def release(source, targets=None):
        released.append(targets)
        return {"ok": True, "refused": False, "results": []}
    timer = IdleUnload(registry=LOADED, settings=lambda: settings_with(False), release=release,
                       busy=lambda: False, leased=lambda: False)
    for entry in LOADED.entries():
        entry.last_use -= 10_000
    assert (await timer.tick())["action"] == "released"
    assert released == [[(OLLAMA, MODEL)]]


async def test_an_lm_studio_start_gets_the_helper_ttl_and_unload_all_releases_it(manager, monkeypatch):
    instance, profile = manager
    profile.update(backend="lmstudio", port=1234, model="qwen-a")
    instance.inventory = [{"port": 1234, "backend": "lmstudio"}]
    run = AsyncMock()
    monkeypatch.setattr(rm, "run_lms", run)
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    assert run.call_args.args[0] == ["load", "qwen-a", "--context-length", "2048", "-y", "--ttl", "300"]
    [entry] = LOADED.entries()
    assert (entry.backend, entry.model, entry.idle_policy) == (LMSTUDIO, "qwen-a", True)
    servers = FakeServers(lmstudio=["qwen-a", FOREIGN]).install(monkeypatch)
    result = await keep_warm_release.release_models("manual")
    assert result["ok"] and servers.lmstudio == [FOREIGN] and LOADED.entries() == []


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_a_manager_started_llama_server_is_stopped_by_unload_all_and_proven_gone(manager, monkeypatch, tmp_path):
    instance, profile = manager
    port = free_port()
    fake = tmp_path / "llama-server"  # a real process named llama-server that listens on the port
    os.symlink(sys.executable, fake)
    profile.update(backend="llama.cpp", port=port, binary=str(fake), model=str(tmp_path / "m.gguf"), n_cpu_moe=None)
    instance.inventory = []
    monkeypatch.setattr(rm, "port_in_use", lambda p: False)
    monkeypatch.setattr("app.config.logs_dir", lambda: tmp_path)
    real_popen = subprocess.Popen
    script = f"import socket,time; s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(120)"
    monkeypatch.setattr(rm.subprocess, "Popen", lambda args, **kw: real_popen([args[0], "-c", script], **kw))
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    pid = instance._launched[port]["pid"]
    try:
        for _ in range(100):  # wait until it listens
            if any(c.laddr.port == port for c in psutil.Process(pid).net_connections(kind="tcp")):
                break
            await asyncio.sleep(0.05)
        [entry] = LOADED.entries()
        assert (entry.backend, entry.port, entry.idle_policy) == (LLAMA_SERVER, port, False)
        result = await keep_warm_release.release_models("manual")
    finally:
        if psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
            psutil.Process(pid).kill()
    assert result["ok"] is True, result
    assert [(r["via"], r["verified"]) for r in result["results"]] == [("model_manager_stop", True)]
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    assert LOADED.entries() == [] and instance._launched == {}


async def test_a_manager_stop_removes_the_model_from_the_ledger(manager, monkeypatch):
    instance, _ = manager
    ollama_posts(monkeypatch)
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    row = {"id": "a" * 24, "port": 11434, "backend": "ollama", "model": MODEL, "process": None, "busy": False,
           "can_stop": True, "active": False, "base_url": "http://127.0.0.1:11434/v1", "source": "ollama_ps"}
    instance.rows = [row]
    servers = FakeServers(ollama=[MODEL])
    mock_http(monkeypatch, servers.handler)
    await instance.decide(row["id"], "stop")
    assert servers.unload_requests() == [{"model": MODEL, "keep_alive": 0}]
    assert LOADED.entries() == []


async def test_unload_native_itself_drops_only_its_own_ledger_entry(manager, monkeypatch):
    """The offline stop (core down) calls only unload_native, so the ledger drop lives there, not in decide()."""
    instance, _ = manager
    ollama_posts(monkeypatch)
    await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    LOADED.record(LMSTUDIO, "other-model", port=1234)
    servers = FakeServers(ollama=[MODEL])
    mock_http(monkeypatch, servers.handler)
    await rm.unload_native({"backend": "ollama", "port": 11434, "model": MODEL,
                            "base_url": "http://127.0.0.1:11434/v1"})
    assert servers.unload_requests() == [{"model": MODEL, "keep_alive": 0}]
    assert [(e.backend, e.model) for e in LOADED.entries()] == [(LMSTUDIO, "other-model")]


@pytest.mark.parametrize("backend,port", [("ollama", 11434), ("lmstudio", 1234)])
async def test_use_on_the_studio_model_refuses_like_stop_and_loads_nothing(manager, monkeypatch, backend, port):
    """CoS (#688 comment 6761525875): Use on bgm-ingest-9b would point ANZU at it and load it. It is refused with the
    same 409 shape as the guarded Stop / Replace / Start, before any scan, load, ledger entry or backend call."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import model as model_api

    instance, _ = manager
    calls: list[str] = []
    mock_http(monkeypatch, lambda request: calls.append(str(request.url)) or httpx.Response(200, json={}))
    load = AsyncMock()
    monkeypatch.setattr(MANAGER, "load", load)
    monkeypatch.setattr(model_api, "RUNNING_MODELS", instance)
    monkeypatch.setattr(model_api, "audit_control", Mock())
    MANAGER.state.manually_unloaded = True
    row = {"id": "b" * 24, "port": port, "backend": backend, "model": FOREIGN, "process": None, "busy": False,
           "can_stop": True, "active": False, "base_url": f"http://127.0.0.1:{port}/v1", "choice": None}
    instance.rows = [row]
    app = FastAPI()
    app.include_router(model_api.router)
    with TestClient(app) as client:
        use = client.post(f"/api/model/running/{row['id']}/choice", json={"action": "use"})
        instance.scan.assert_not_called()  # refused before discovery runs again
        stop = client.post(f"/api/model/running/{row['id']}/choice", json={"action": "stop", "confirm": True})
    assert (use.status_code, use.json()) == (409, {"detail": "ANZU never uses this model"})
    assert stop.status_code == 409 and stop.json().keys() == use.json().keys()  # the same refusal shape as Stop
    load.assert_not_called()
    assert calls == [] and LOADED.entries() == []
    assert MANAGER.state.manually_unloaded is True, "a refused Use is not an explicit Load"
    assert rm.load_settings().inference.remote_model != FOREIGN


async def test_discovery_never_reconnects_or_offers_the_studio_model(manager, monkeypatch):
    """A saved "use" choice (or the settings) naming bgm-ingest-9b never auto-loads it, and the chat never offers it."""
    instance, _ = manager
    settings = rm.load_settings()
    settings.inference.auto_load = True
    settings.inference.backend, settings.inference.host = "ollama", "127.0.0.1"
    settings.inference.port, settings.inference.remote_model = 11434, FOREIGN
    load, publish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(MANAGER, "load", load)
    monkeypatch.setattr("app.persona.chat_delivery.publish_owner_text", publish)
    MANAGER.state.loaded = MANAGER.state.loading = False
    instance.rows = [
        {"id": "c" * 24, "port": 11434, "backend": "ollama", "model": FOREIGN, "choice": "use", "busy": False},
        {"id": "d" * 24, "port": 1234, "backend": "lmstudio", "model": FOREIGN, "choice": None, "busy": False},
    ]
    task = asyncio.create_task(instance._poll())
    try:
        for _ in range(100):
            if instance.scan.await_count:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)  # the rest of the iteration, up to its 20 s sleep
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert instance.scan.await_count == 1 and instance.error == ""
    load.assert_not_called()
    publish.assert_not_called()


async def test_the_studio_model_is_never_offered_or_started(manager, monkeypatch):
    instance, profile = manager
    profile["model"] = FOREIGN
    launch = AsyncMock()
    monkeypatch.setattr(instance, "_launch_profile", launch)
    with pytest.raises(ValueError, match="never starts"):
        await instance.start_model(ml.ModelStart(profile_id="p", confirm=True))
    launch.assert_not_called()
    assert LOADED.entries() == []
    offered = ml.launch_profiles([{"backend": "ollama", "port": 11434, "available_models": [{"name": FOREIGN}, {"name": MODEL}]}])
    assert FOREIGN not in {p["model"] for p in offered} and MODEL in {p["model"] for p in offered}
    with pytest.raises(ValueError, match="never stops"):
        await rm.unload_native({"backend": "ollama", "port": 11434, "model": FOREIGN})


# --- CoS owner-pin ruling: a model the owner pinned (not ANZU) keeps "-1" and never idles out ----------------------

PINNED_AT = "2319-02-20T03:37:31+01:00"  # how keep_alive -1 / OLLAMA_KEEP_ALIVE=-1 shows on /api/ps
NORMAL_AT = "2026-11-10T06:20:00+01:00"


async def test_an_owner_pinned_model_seen_on_discovery_keeps_minus_one_on_every_request(tmp_path, monkeypatch):
    from app.inference import keep_alive

    settings = AppSettings()
    monkeypatch.setattr(rm, "load_settings", lambda: settings)
    monkeypatch.setattr(rm, "listener_inventory", lambda: {})
    monkeypatch.setattr(rm, "ollama_serves", lambda: [])
    monkeypatch.setattr(rm, "ollama_diagnostics", lambda serves, listener: [])
    monkeypatch.setattr(rm, "KNOWN_PORTS", {11434})
    ps = {"models": [{"name": "owner-pinned:9b", "expires_at": PINNED_AT}, {"name": "owner-plain:4b", "expires_at": NORMAL_AT}]}
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port != 11434:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=ps if request.url.path == "/api/ps" else {"models": []})
    mock_http(monkeypatch, handler)
    await rm.RunningModels(tmp_path / "choices.json").scan(force=True)  # #691 discovery reads /api/ps

    base = "http://127.0.0.1:11434/v1"
    assert request_extras(base, "owner-pinned:9b") == {"keep_alive": "-1"}, "never reset the owner's pin to 300s"
    assert request_extras(base, "owner-plain:4b") == {"keep_alive": "300s"}
    assert keep_alive.ollama_body("owner-pinned:9b", {"prompt": ""})["keep_alive"] == "-1"  # native touch / warm
    assert keep_alive.ollama_body("owner-pinned:9b", release=True)["keep_alive"] == 0  # an owner Unload still frees it

    ps["models"] = [{"name": "owner-plain:4b", "expires_at": NORMAL_AT}]  # the owner unloaded it: the pin is gone
    keep_alive.note_ollama_ps(11434, ps["models"])
    assert request_extras(base, "owner-pinned:9b") == {"keep_alive": "300s"}


async def test_a_model_anzu_pinned_with_keep_warm_is_not_an_owner_pin():
    from app.inference import keep_alive

    LOADED.record(OLLAMA, MODEL)  # ANZU loaded it; Keep warm ON made /api/ps show it pinned
    keep_alive.note_ollama_ps(11434, [{"name": MODEL, "expires_at": PINNED_AT}])
    assert not keep_alive.owner_pinned(MODEL)
    assert request_extras("http://127.0.0.1:11434/v1", MODEL) == {"keep_alive": "300s"}  # Keep warm now off


async def test_the_v1_touch_restates_an_owner_pin_and_the_idle_timer_never_releases_it(monkeypatch):
    from app.inference import keep_alive

    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "owner-pinned:9b", "expires_at": PINNED_AT}]})
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})
    monkeypatch.setattr(keep_alive.httpx, "AsyncClient",
                        lambda **kw: REAL_CLIENT(**{"transport": httpx.MockTransport(handler), **kw}))
    assert await keep_alive.touch_ollama_if_resident("http://127.0.0.1:11434/v1", "owner-pinned:9b") is True
    assert posts == [{"model": "owner-pinned:9b", "prompt": "", "stream": False, "keep_alive": "-1"}]

    # The owner then Uses it (an explicit attach records it): Unload-all may release it, the idle timer may not.
    LOADED.record(OLLAMA, "owner-pinned:9b")
    released: list = []

    async def release(source, targets=None):
        released.append(targets)
        return {"ok": True, "refused": False, "results": []}
    timer = IdleUnload(registry=LOADED, settings=lambda: settings_with(False), release=release,
                       busy=lambda: False, leased=lambda: False)
    for entry in LOADED.entries():
        entry.last_use -= 10_000
    assert (await timer.tick())["reason"] == "active" and released == []
