"""RFC-0242 "Reconciliation with #690": the contract closers, one named test per row (and the guard coverage)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.agent.loop import AGENT
from app.config import AppSettings
from app.inference import keep_alive, keep_warm_release
from app.inference.idle_unload import IDLE_UNLOAD, IdleUnload, warm_blocked
from app.inference.loaded_models import LMSTUDIO, LOADED, OLLAMA, LoadedModels
from app.inference.manager import MANAGER
from tests.test_keep_warm_idle_unload import (  # noqa: F401  (clean_state is an autouse fixture)
    ANZU_OLLAMA, FOREIGN, FakeClock, FakeServers, api_client, clean_state, make_timer, settings_with, write_settings,
)


# --- rows 1 and 2: 207 with per-model rows (never 502); a running pipeline is cancelled visibly -------------------

async def test_unload_all_partial_failure_returns_207_with_per_model_results(monkeypatch):
    FakeServers(ollama=["stuck:1b"], ollama_ignores_unload=True, lmstudio=["qwen-a"]).install(monkeypatch)
    LOADED.record(OLLAMA, "stuck:1b")
    LOADED.record(LMSTUDIO, "qwen-a")
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 207 and response.status_code != 502
    rows = {row["model"]: row for row in response.json()["results"]}
    assert rows["stuck:1b"]["verified"] is False and rows["stuck:1b"]["error"]
    assert rows["qwen-a"]["verified"] is True
    assert MANAGER.state.manually_unloaded is False


async def test_unload_all_cancels_pipeline_instead_of_refusing_for_task(monkeypatch, tmp_path):
    """A running task (a pipeline) is not a 409: it is cancelled visibly and the models are then released."""
    from app.db import session as session_mod
    from app.db.models import Task

    await session_mod.configure_database(path=tmp_path / "jarvis.db")
    await session_mod.init_db()
    async with session_mod.SessionLocal() as session:
        session.add(Task(id="pipeline-1", title="t", prompt="p", status="running", stage="working"))
        await session.commit()
    servers = FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    events: list[tuple] = []

    async def publish(task_id, kind, title, *args, **kwargs):
        events.append((task_id, kind, title))

    monkeypatch.setattr("app.agent.loop.BUS.publish", publish)
    holding_lease = asyncio.Event()

    async def pipeline():  # a task that holds the engine lease while it runs, like a model request
        async with MANAGER._request_lease.shared():
            holding_lease.set()
            await asyncio.sleep(60)

    runner = asyncio.create_task(pipeline())
    AGENT._tasks["pipeline-1"] = runner
    await holding_lease.wait()
    try:
        async with api_client() as client:
            response = await client.post("/api/model/unload-all")
    finally:
        AGENT._tasks.pop("pipeline-1", None)
        AGENT._cancel.discard("pipeline-1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cancelled_tasks"] == ["pipeline-1"] and runner.cancelled()
    assert ("pipeline-1", "cancelled", "Cancelled: the owner pressed Unload model.") in events
    assert servers.ollama == [] and MANAGER.state.manually_unloaded is True
    async with session_mod.SessionLocal() as session:
        row = await session.get(Task, "pipeline-1")
    assert (row.status, row.stage) == ("cancelled", "cancelled")  # visible in the task list


async def test_unload_all_still_returns_409_for_a_model_request_that_is_not_a_task(monkeypatch):
    FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    async with api_client() as client:
        async with MANAGER._request_lease.shared():
            response = await client.post("/api/model/unload-all")
    assert response.status_code == 409 and "answering a request" in response.json()["detail"]
    assert MANAGER.state.manually_unloaded is False


async def test_nothing_to_unload_never_cancels_tasks(monkeypatch):
    FakeServers().install(monkeypatch)
    cancelled: list[str] = []

    async def cancel(reason):
        cancelled.append(reason)
        return []

    monkeypatch.setattr(IDLE_UNLOAD, "_busy", lambda: True)
    monkeypatch.setattr(IDLE_UNLOAD, "_cancel_tasks", cancel)
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 409 and cancelled == []


# --- rows 3 and 7: ledger ownership and the per-model idle clock -------------------------------------------------

async def test_owner_started_instance_never_enters_the_ledger_without_an_anzu_load(monkeypatch):
    """A model the owner started and ANZU merely attached to / chatted with is foreign: never idle-unloaded."""
    servers = FakeServers(ollama=["owner-started:7b"]).install(monkeypatch)
    clock = FakeClock()
    monkeypatch.setattr(LOADED, "_clock", clock)
    MANAGER.state.backend, MANAGER.state.loaded, MANAGER.state.remote_model = OLLAMA, True, "owner-started:7b"
    MANAGER.provider = type("P", (), {"model": "owner-started:7b"})()
    MANAGER._register_loaded()          # an attach (discovery / reconnect / chat) records nothing ...
    MANAGER._mark_used()                # ... and a turn that used it creates no entry either
    assert LOADED.entries() == []
    clock.now += 10_000
    timer = IdleUnload(registry=LOADED, settings=lambda: settings_with(False), busy=lambda: False,
                       leased=lambda: False)
    assert (await timer.tick())["reason"] == "active"
    assert servers.mutating() == [] and servers.ollama == ["owner-started:7b"]
    # An explicit owner Load of it IS an ANZU load: only then does it enter the ledger and idle-unload.
    IDLE_UNLOAD.explicit_load()
    MANAGER._register_loaded(attach=IDLE_UNLOAD.consume_explicit_load())
    assert LOADED.match(OLLAMA, ["owner-started:7b"]) is not None
    assert IDLE_UNLOAD.consume_explicit_load() is False  # the window is single-use


async def test_front_only_turn_resets_only_the_front_clock(monkeypatch):
    from app.agent import front_responder
    from app.inference.loaded_models import FRONT, LLAMA_SERVER, WORKER

    clock = FakeClock()
    monkeypatch.setattr(LOADED, "_clock", clock)
    LOADED.record(LLAMA_SERVER, WORKER)
    LOADED.record(LLAMA_SERVER, FRONT)
    clock.now += 250
    monkeypatch.setattr("app.engine_mode.model_enabled", lambda app: True)

    def stop(*args, **kwargs):
        raise RuntimeError("stop after the front entry")

    monkeypatch.setattr(front_responder, "front_lane_config", stop)
    with pytest.raises(RuntimeError, match="stop after the front"):
        await front_responder.generate_front_reply("hello", settings=AppSettings())
    idle = {entry.key[1]: LOADED.idle_for(entry) for entry in LOADED.entries()}
    assert idle[FRONT] == 0 and idle[WORKER] == 250  # the main model's clock was NOT reset by a front-only turn


# --- rows 8 and 10: manually_unloaded fails closed; a non-owner release leaves no stuck hold ----------------------

async def test_reflex_only_turn_does_not_clear_manually_unloaded():
    MANAGER.state.manually_unloaded = True
    reflex = IdleUnload(registry=LoadedModels(), settings=lambda: AppSettings(engine_mode="reflex_only"))
    reflex.touch()  # a reflex-only turn loads no model
    assert MANAGER.state.manually_unloaded is True
    broken = IdleUnload(registry=LoadedModels(), settings=lambda: 1 / 0)
    broken.touch()  # unreadable settings: unknown means closed
    assert MANAGER.state.manually_unloaded is True
    hybrid = IdleUnload(registry=LoadedModels(), settings=lambda: AppSettings(engine_mode="hybrid"))
    hybrid.touch()  # a real owner turn that can use a model
    assert MANAGER.state.manually_unloaded is False
    MANAGER.state.manually_unloaded = True
    reflex.explicit_load()  # an explicit Load clears it in every engine mode
    assert MANAGER.state.manually_unloaded is False


async def test_background_task_runner_never_clears_manually_unloaded():
    MANAGER.state.manually_unloaded = True

    async def turn():
        return None

    runner = AGENT._start_runner("queue-watcher-task", turn())  # queue_watcher / intake start tasks this way
    await runner
    AGENT._tasks.pop("queue-watcher-task", None)
    assert MANAGER.state.manually_unloaded is True


async def test_respawn_clears_hold_but_never_manually_unloaded():
    timer = IdleUnload(registry=LoadedModels(), settings=lambda: AppSettings())
    MANAGER.state.manually_unloaded = True
    timer.held = True
    timer.clear_hold()
    assert timer.held is False and MANAGER.state.manually_unloaded is True
    assert timer.background_blocked() is True  # still closed for the owner's Unload


async def test_a_non_owner_release_leaves_no_hold_behind(monkeypatch):
    FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    LOADED.record(OLLAMA, "qwen3:8b")
    IDLE_UNLOAD.held = False
    result = await keep_warm_release.release_models("idle", [(OLLAMA, "qwen3:8b")])
    assert result["released_count"] == 1
    assert IDLE_UNLOAD.held is False and MANAGER.state.manually_unloaded is False
    assert warm_blocked() is False
    LOADED.record(OLLAMA, "qwen3:8b")
    FakeServers(ollama=["qwen3:8b"]).install(monkeypatch)
    await keep_warm_release.release_models("manual")
    assert IDLE_UNLOAD.held is True  # an owner Unload does hold background starters off


# --- row 11 -----------------------------------------------------------------------------------------------------

async def test_tick_defers_for_engine_leases_as_well_as_agent_tasks():
    clock = FakeClock()
    registry = LoadedModels(clock)
    registry.record(OLLAMA, "qwen3:8b")
    calls: list = []

    async def release(source, targets=None):
        calls.append(source)
        return {"ok": True, "refused": False, "results": []}

    state = {"lease": True}
    timer = IdleUnload(registry=registry, settings=lambda: settings_with(False), release=release,
                       busy=lambda: False, leased=lambda: state["lease"])
    clock.now += 1000
    assert await timer.tick() == {"action": "skipped", "reason": "engine_leased"} and calls == []
    state["lease"] = False
    assert (await timer.tick())["action"] == "released" and calls == ["idle"]


async def test_tick_sees_the_real_manager_lease():
    """No injected callable: a held shared lease on MANAGER makes the real default defer."""
    assert IDLE_UNLOAD.engine_leased() is False
    async with MANAGER._request_lease.shared():
        assert IDLE_UNLOAD.engine_leased() is True


async def test_unload_with_nothing_loaded_returns_409_reason_and_sets_no_flag(monkeypatch):
    FakeServers().install(monkeypatch)
    async with api_client() as client:
        response = await client.post("/api/model/unload-all")
    assert response.status_code == 409
    assert "Nothing to unload" in response.text
    assert MANAGER.state.manually_unloaded is False and IDLE_UNLOAD.held is False


# --- rows 4, 5 and 9 ---------------------------------------------------------------------------------------------

async def test_every_ollama_request_path_sets_keep_alive_except_the_studio_model(monkeypatch, tmp_path):
    """On the wire: a /v1 chat for ANY Ollama model (in the ledger or not) carries keep_alive; the studio model never."""
    from openai import AsyncOpenAI

    from app.providers.base import ModelProvider
    from tests.test_keep_warm_idle_unload import write_settings

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        sent.append(_json.loads(request.content))
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "hi"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    from app.providers.base import ChatMessage

    for keep_warm, expected in ((False, "300s"), (True, "-1")):
        write_settings(tmp_path, keep_warm=keep_warm)
        for model in ("never-loaded-by-anzu:7b", ANZU_OLLAMA, FOREIGN):
            provider = ModelProvider("http://127.0.0.1:11434/v1", model=model)
            provider.client = AsyncOpenAI(base_url="http://127.0.0.1:11434/v1", api_key="x",
                                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            sent.clear()
            await provider.chat([ChatMessage(role="user", content="hello")])
            body = sent[-1]
            if model == FOREIGN:
                assert "keep_alive" not in body  # bgm-ingest-9b is the one exception
            else:
                assert body["keep_alive"] == expected, model
    assert LOADED.entries() == []  # sending keep_alive recorded nothing: it restates the policy only


async def test_ollama_v1_turn_is_followed_by_a_keep_alive_touch_only_if_resident(monkeypatch, tmp_path):
    from tests.test_keep_warm_idle_unload import write_settings

    servers = FakeServers(ollama=["owner-started:7b"]).install(monkeypatch)
    real = httpx.AsyncClient
    monkeypatch.setattr(keep_alive.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(servers.handler), **kw))
    write_settings(tmp_path, keep_warm=False)
    base = "http://127.0.0.1:11434/v1"
    assert await keep_alive.touch_ollama_if_resident(base, "owner-started:7b") is True  # resident, not in the ledger
    posts = [body for _p, method, path, body in servers.requests if method == "POST"]
    assert posts == [{"model": "owner-started:7b", "prompt": "", "stream": False, "keep_alive": "300s"}]
    servers.requests.clear()
    assert await keep_alive.touch_ollama_if_resident(base, "not-resident:1b") is False  # never loads anything
    assert [r for r in servers.requests if r[1] == "POST"] == []
    assert await keep_alive.touch_ollama_if_resident("http://10.0.0.9:11434/v1", "owner-started:7b") is False


async def test_name_guard_is_a_second_layer_even_when_the_ledger_lists_bgm_ingest_9b(monkeypatch):
    servers = FakeServers(ollama=[FOREIGN, ANZU_OLLAMA], lmstudio=[FOREIGN]).install(monkeypatch)
    LOADED.record(OLLAMA, FOREIGN)
    LOADED.record(LMSTUDIO, FOREIGN)
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    # a registry-style or path-style id does not slip through
    for variant in (FOREIGN, FOREIGN + ":latest", "hf.co/acme/" + FOREIGN, "acme/" + FOREIGN):
        assert keep_alive.is_denied(variant)
        assert keep_alive.request_extras("http://127.0.0.1:11434/v1", variant) == {}
        assert keep_alive.lmstudio_ttl_seconds(model=variant) is None
    result = await keep_warm_release.release_models("manual")
    assert FOREIGN in servers.ollama and FOREIGN in servers.lmstudio and result["ok"] is True
    # the discovery stop / replace path (closing the process or unloading) refuses it as well
    from app.inference.running_models import RUNNING_MODELS

    row = {"id": "r1", "model": FOREIGN, "backend": "ollama", "port": 11434, "process": "p", "can_stop": True,
           "busy": False, "active": False}
    monkeypatch.setattr(RUNNING_MODELS, "rows", [row])

    async def scan(force=False):
        return RUNNING_MODELS.snapshot()

    monkeypatch.setattr(RUNNING_MODELS, "scan", scan)
    for action in ("stop", "replace"):
        with pytest.raises(ValueError, match="never stops"):
            await RUNNING_MODELS.decide("r1", action)
    # growing / restoring an LM Studio instance with that identifier is refused too
    from app.inference.lmstudio_context import grow_local_instance

    settings = settings_with(False, backend="lmstudio", host="127.0.0.1", port=1234)
    assert await grow_local_instance(settings, 32768, FOREIGN) is None
