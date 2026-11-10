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


# --- row 6: Keep warm ON re-pins ---------------------------------------------------------------------------------

async def test_toggle_on_repins_every_loaded_anzu_model_with_minus_one(monkeypatch, tmp_path):
    from app.api import settings as settings_api
    from tests.test_keep_warm_idle_unload import write_settings

    servers = FakeServers(ollama=[ANZU_OLLAMA, "owner-started:7b", FOREIGN]).install(monkeypatch)
    write_settings(tmp_path, keep_warm=False)
    LOADED.record(OLLAMA, ANZU_OLLAMA)
    LOADED.record(OLLAMA, FOREIGN)  # even a buggy ledger entry cannot unlock the studio model
    await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=True))
    await asyncio.gather(*settings_api._IDLE_TICKS)
    posts = [body for _p, method, path, body in servers.requests if method == "POST"]
    assert posts == [{"model": ANZU_OLLAMA, "prompt": "", "stream": False, "keep_alive": "-1"}]
    # Turning it OFF never re-pins; an owner Unload blocks it; the toggle with no change does nothing.
    servers.requests.clear()
    await settings_api.update_settings(settings_api.SettingsUpdate(inference_keep_warm=True))
    await asyncio.gather(*settings_api._IDLE_TICKS)
    assert [r for r in servers.requests if r[1] == "POST"] == []
    MANAGER.state.manually_unloaded = True
    result = await keep_warm_release.repin_loaded_models()
    assert result["action"] == "skipped" and [r for r in servers.requests if r[1] == "POST"] == []


async def test_keep_warm_on_repins_lmstudio_instances_without_ttl(monkeypatch, tmp_path):
    import json
    import subprocess

    from app.inference import lmstudio_context
    from tests.test_keep_warm_idle_unload import write_settings

    write_settings(tmp_path, keep_warm=True)
    instances = {
        "qwen-a": {"identifier": "qwen-a", "modelKey": "qwen-a", "status": "idle", "queued": 0, "contextLength": 16384,
                   "maxContextLength": 32768, "ttlMs": 300000},
        "owner-lm": {"identifier": "owner-lm", "modelKey": "owner-lm", "status": "idle", "queued": 0,
                     "contextLength": 8192, "maxContextLength": 8192, "ttlMs": 3600000},
        FOREIGN: {"identifier": FOREIGN, "modelKey": FOREIGN, "status": "idle", "queued": 0, "contextLength": 8192,
                  "maxContextLength": 8192, "ttlMs": 300000},
    }
    commands: list[list[str]] = []

    def run(argv, **kwargs):
        args = [str(a) for a in argv]
        commands.append(args)
        if args[1:3] == ["ps", "--json"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(list(instances.values())), "")
        if args[1] == "unload":
            instances.pop(args[2])
        if args[1] == "load":
            instances[args[2]] = {**{"identifier": args[2], "modelKey": args[2], "status": "idle", "queued": 0,
                                     "contextLength": int(args[args.index("--context-length") + 1]),
                                     "maxContextLength": 32768}, "ttlMs": None if "--ttl" not in args else 1}
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(lmstudio_context.subprocess, "run", run)
    monkeypatch.setattr(lmstudio_context.shutil, "which", lambda name: "/bin/lms")
    LOADED.record(LMSTUDIO, "qwen-a")
    LOADED.record(LMSTUDIO, FOREIGN)
    settings = settings_with(True, backend="lmstudio", host="127.0.0.1", port=1234)
    rows = await lmstudio_context.repin_local_instances(settings, lease=MANAGER._request_lease)
    assert [(r["model"], r["verified"]) for r in rows] == [("qwen-a", True)]
    mutating = [c[1:] for c in commands if c[1] in {"unload", "load"}]
    assert mutating[0] == ["unload", "qwen-a"]
    assert mutating[1][:3] == ["load", "qwen-a", "--identifier"] and "--ttl" not in mutating[1]
    assert all("owner-lm" not in c and FOREIGN not in c for c in mutating)  # not ANZU-loaded / denied: untouched
    assert instances["qwen-a"]["ttlMs"] is None and instances["owner-lm"]["ttlMs"] == 3600000
    # An engine lease held by a running request defers the reload (the TTL stays until it finishes).
    instances["qwen-a"]["ttlMs"] = 300000
    commands.clear()
    async with MANAGER._request_lease.shared():
        rows = await lmstudio_context.repin_local_instances(settings, lease=MANAGER._request_lease)
    assert rows and rows[0]["verified"] is False and [c for c in commands if c[1] in {"unload", "load"}] == []


# --- D1 review: owner approvals, entry-point scan, persona bind -------------------------------------------------

@pytest.fixture
async def own_agent_tasks(monkeypatch):
    """The routes' AGENT with an empty runner table for this test only; whatever the test started is cancelled and
    awaited on this loop afterwards, so runners other tests left behind (on closed loops) are never touched."""
    from app.api import tasks as tasks_api

    agent = tasks_api.AGENT
    mine: dict = {}
    monkeypatch.setattr(agent, "_tasks", mine)
    yield agent
    leftovers = [task for task in mine.values() if isinstance(task, asyncio.Task)]
    for task in leftovers:
        task.cancel()
    await asyncio.gather(*leftovers, return_exceptions=True)
    mine.clear()


async def test_owner_approval_after_unload_respawns_the_model(monkeypatch, own_agent_tasks):
    """Approving a parked task after Unload is an owner act: the hold is lifted before the runner loads."""
    from types import SimpleNamespace

    from app.api import tasks as tasks_api
    from app.inference.manager import MANAGER  # resolved at call time: other tests reload app modules

    AGENT = tasks_api.AGENT

    seen: list[bool] = []

    async def confirm_task(self, task_id, approved, **kwargs):
        seen.append(MANAGER.state.manually_unloaded)  # what _run -> _guard_background_load would see
        return SimpleNamespace(id=task_id)

    async def route_confirm(task_id, approved, **kwargs):
        return await confirm_task(None, task_id, approved, **kwargs)

    # Replace the route's own AGENT: other test modules reload app modules, so patching a class is not airtight.
    monkeypatch.setattr(tasks_api, "AGENT", SimpleNamespace(confirm_task=route_confirm))
    monkeypatch.setattr(tasks_api, "_task_dict", lambda task: {"id": task.id})
    for body in (tasks_api.ContinueBody(approve=True), tasks_api.ContinueBody(grant_mode="allow_once"),
                 tasks_api.ContinueBody(approve=False)):
        MANAGER.state.manually_unloaded = True
        await tasks_api.continue_task("parked-1", body)
    assert seen == [False, False, False]


async def test_a_real_parked_task_resumes_after_unload_only_through_an_owner_approval(monkeypatch, tmp_path, own_agent_tasks):
    """End to end through AGENT.confirm_task: _run reaches the guard and the owner route is what clears it."""
    from app.api import tasks as tasks_api
    from app.db import session as session_mod
    from app.db.models import Task
    from app.inference.manager import MANAGER

    AGENT = own_agent_tasks
    await session_mod.configure_database(path=tmp_path / "jarvis.db")
    await session_mod.init_db()
    import app.agent.loop as loop_mod

    monkeypatch.setattr(loop_mod, "SessionLocal", session_mod.SessionLocal)  # names imported before the reconfigure
    monkeypatch.setattr(tasks_api, "SessionLocal", session_mod.SessionLocal)
    async with session_mod.SessionLocal() as session:
        session.add(Task(id="parked-2", title="t", prompt="p", status="running", stage="waiting",
                         waiting_for_confirmation=True, confirmation_payload="{}"))
        await session.commit()
    guard: list[bool] = []

    async def run(task_id, **kwargs):
        guard.append(MANAGER.state.manually_unloaded)

    monkeypatch.setattr(AGENT, "_run", run)
    MANAGER.state.manually_unloaded = True
    try:
        await tasks_api.continue_task("parked-2", tasks_api.ContinueBody(approve=True))
    except Exception:
        pass  # the response shape is not under test; the runner ordering is
    runner = AGENT._tasks.get("parked-2")  # only the runner this test started
    assert runner is not None
    await asyncio.gather(runner, return_exceptions=True)
    assert guard == [False]


def test_static_scan_every_owner_task_entry_point_touches_before_it_reaches_the_agent():
    """Every AGENT.create_task / continue_task / confirm_task caller either lifts the Unload hold first (an owner
    act) or is on the explicit allowlist (background starters, automatic timeouts, guest approvals)."""
    import ast

    from tests.test_keep_warm_idle_unload import BACKEND_APP, _outermost_functions, _python_files

    background = {  # (file, function): why it must NOT lift manually_unloaded
        ("agent/acp_adapter.py", None): "ACP client, not the owner's HUD",
        ("agent/intake.py", None): "intake chain",
        ("agent/queue_watcher.py", None): "queue_watcher background task",
        ("inference/live_agent_suite.py", None): "benchmark harness",
        ("api/guest_portals.py", None): "a guest's approval is not the owner's",
        ("api/reversibility.py", "pending_timeout"): "an automatic timeout is not an owner act",
    }
    methods = {"create_task", "continue_task", "confirm_task"}
    lifts = {"touch", "explicit_load"}
    owners: list[str] = []
    offenders: list[str] = []
    for name, text in _python_files():
        if name == "agent/loop.py":
            continue  # the AgentRuntime itself
        for fn in _outermost_functions(ast.parse(text)):
            agent_calls = [c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                           and c.func.attr in methods and isinstance(c.func.value, ast.Name) and c.func.value.id == "AGENT"]
            if not agent_calls:
                continue
            if (name, None) in background or (name, fn.name) in background:
                continue
            owners.append(f"{name}:{fn.name}")
            # Each call site must be dominated by a lift: an ``IDLE_UNLOAD.touch()`` / ``explicit_load()`` statement
            # earlier in the same block or in an enclosing block (so every branch, e.g. a retry path, has its own).
            parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}

            def is_lift(stmt) -> bool:
                return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr in lifts
                        and isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id == "IDLE_UNLOAD")

            def dominated(node) -> bool:
                while node in parents:
                    parent = parents[node]
                    for field in ("body", "orelse", "finalbody"):
                        block = getattr(parent, field, None)
                        if isinstance(block, list) and node in block:
                            if any(is_lift(stmt) for stmt in block[:block.index(node)]):
                                return True
                    node = parent
                return False

            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and call.lineno in agent_calls and isinstance(call.func, ast.Attribute) \
                        and call.func.attr in methods and not dominated(call):
                    offenders.append(f"{name}:{fn.name}:{call.lineno}")
    assert offenders == []
    # The scan sees the owner routes it is meant to police (a rename of AGENT would otherwise empty it).
    for expected in ("api/tasks.py:continue_task", "api/tasks.py:create_task", "api/voice.py:voice_command",
                     "api/voice.py:voice_listen", "api/workflows.py", "mobile/service.py:submit", "mobile/service.py:approve",
                     "api/reversibility.py:pending_decide", "persona/owner_chat.py"):
        assert any(owner.startswith(expected) for owner in owners), expected


async def test_persona_bind_after_unload_lifts_the_hold_before_the_prepare_step(monkeypatch):
    from types import SimpleNamespace

    from app.api import named_personas

    await_order: list[tuple[str, bool]] = []
    profile = SimpleNamespace(enabled=True, provider="ollama", endpoint="http://127.0.0.1:11434", model="persona-brain:8b")
    monkeypatch.setattr(named_personas, "resolve_persona_id", lambda raw, required=True: "veles")
    monkeypatch.setattr(named_personas, "brain_runtime_name_for_persona", lambda pid: "rt")
    monkeypatch.setattr(named_personas, "get_runtime_profile", lambda name: profile)
    monkeypatch.setattr(named_personas, "reflex_verify_brain_runtime", lambda **kw: True)

    async def prepare(**kwargs):
        await_order.append(("prepare", warm_blocked()))
        return {"ok": True}

    async def activate(profile, force=False):
        await_order.append(("activate", warm_blocked()))

    monkeypatch.setattr(named_personas, "ensure_local_ollama", prepare)
    monkeypatch.setattr(named_personas, "activate_runtime_profile", activate)
    MANAGER.state.manually_unloaded = True
    IDLE_UNLOAD.held = True
    await named_personas._maybe_activate_persona_brain("veles")
    assert await_order == [("prepare", False), ("activate", False)]  # not blocked at prepare: the bind goes through
    assert MANAGER.state.manually_unloaded is False


# --- D1 review: real-load wiring, worker clock, name guards -------------------------------------------------------

def _reset_manager():
    MANAGER.provider = None
    MANAGER.backend = None
    MANAGER.state.loaded = False
    MANAGER.state.loading = False
    MANAGER._attach_ok = False


async def _real_attach(monkeypatch, backend: str, model: str, port: int):
    """Drive the real MANAGER.load against an already running, owner-started server."""
    from app.inference import manager as manager_mod

    async def probe(*args, **kwargs):
        return {"ok": True, "models": [model]}

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(manager_mod, "probe_remote_server", probe)
    monkeypatch.setattr(MANAGER, "refresh_resources", nothing)
    _reset_manager()
    settings = settings_with(False, backend=backend, host="127.0.0.1", port=port, remote_model=model)
    await MANAGER.load(settings, force=True)
    assert MANAGER.state.loaded is True
    return settings


@pytest.mark.parametrize("backend,model,port", [("ollama", "owner-started:7b", 11434), ("lmstudio", "owner-lm", 1234)])
async def test_a_real_load_attach_never_enters_the_ledger_without_an_explicit_owner_load(monkeypatch, backend, model, port):
    """Mutant guard: _load_impl / _load_locked must not register an attach unless an explicit Load asked for it."""
    await _real_attach(monkeypatch, backend, model, port)
    assert LOADED.entries() == []  # attached to what the owner started: foreign, never idle-unloaded
    # A background starter (ensure_runtime) goes through the same path and still records nothing.
    _reset_manager()
    await _real_attach(monkeypatch, backend, model, port)
    assert LOADED.entries() == []


@pytest.mark.parametrize("backend,model,port", [("ollama", "owner-started:7b", 11434), ("lmstudio", "owner-lm", 1234)])
async def test_a_real_load_after_an_explicit_load_records_the_model(monkeypatch, backend, model, port):
    IDLE_UNLOAD.explicit_load()  # HUD / dropdown / runtime activation
    await _real_attach(monkeypatch, backend, model, port)
    assert LOADED.match(backend, [model]) is not None
    # single use: the next attach in the same context is background again and records nothing new
    LOADED.clear()
    await _real_attach(monkeypatch, backend, model, port)
    assert LOADED.entries() == []


@pytest.mark.parametrize("backend,model,port", [("ollama", "owner-started:7b", 11434), ("lmstudio", "owner-lm", 1234)])
async def test_a_real_load_that_waits_for_the_server_records_only_after_an_explicit_load(monkeypatch, backend, model, port):
    """The second _load_impl branch (server not answering at the probe, ready after backend.start) follows the same
    rule as the attach branch: only an explicit owner Load makes the model ANZU-loaded."""
    from app.inference import backends as backends_mod, manager as manager_mod

    async def probe(*args, **kwargs):
        return {"ok": False}

    async def nothing(*args, **kwargs):
        return None

    async def start(self, profile, **kwargs):
        self.last_probe = {"ok": True, "models": [model]}
        return True

    monkeypatch.setattr(manager_mod, "probe_remote_server", probe)
    monkeypatch.setattr(MANAGER, "refresh_resources", nothing)
    for cls in (backends_mod.OllamaBackend, backends_mod.LMStudioBackend):
        monkeypatch.setattr(cls, "start", start)
    settings = settings_with(False, backend=backend, host="127.0.0.1", port=port, remote_model=model)
    _reset_manager()
    await MANAGER.load(settings, force=True)
    assert MANAGER.state.loaded is True and LOADED.entries() == []
    _reset_manager()
    IDLE_UNLOAD.explicit_load()
    await MANAGER.load(settings, force=True)
    assert LOADED.match(backend, [model]) is not None
    _reset_manager()


async def test_an_explicit_load_that_never_reaches_a_load_cannot_leak_into_a_later_background_attach(monkeypatch):
    async def owner_act_that_fails_before_loading():
        IDLE_UNLOAD.explicit_load()  # e.g. the HUD click whose load request errors out before MANAGER.load runs

    await asyncio.create_task(owner_act_that_fails_before_loading())
    await _real_attach(monkeypatch, "ollama", "owner-started:7b", 11434)  # a later, separate background attach
    assert LOADED.entries() == []
    assert IDLE_UNLOAD.consume_explicit_load() is False
    # ... and an explicit Load whose load() short-circuits (already loaded, same settings) is still consumed.
    IDLE_UNLOAD.explicit_load()
    settings = settings_with(False, backend="ollama", host="127.0.0.1", port=11434, remote_model="owner-started:7b")
    await MANAGER.load(settings)  # same endpoint and profile: returns early without a new attach
    assert IDLE_UNLOAD.consume_explicit_load() is False
    _reset_manager()


async def test_worker_only_turn_resets_only_the_worker_clock_for_chat_and_chat_stream(monkeypatch):
    from types import SimpleNamespace

    from app.inference.loaded_models import FRONT, LLAMA_SERVER, WORKER

    clock = FakeClock()
    monkeypatch.setattr(LOADED, "_clock", clock)
    LOADED.record(LLAMA_SERVER, WORKER)
    LOADED.record(LLAMA_SERVER, FRONT)
    LOADED.record(OLLAMA, "other:1b")
    MANAGER.state.manages_process, MANAGER.state.loaded = True, True

    async def reply(*args, **kwargs):
        return "reply"

    async def stream(*args, **kwargs):
        yield "chunk"

    MANAGER.provider = SimpleNamespace(chat=reply, chat_stream=stream, base_url="http://127.0.0.1:8088/v1", model="w")
    monkeypatch.setattr(MANAGER, "_keep_alive_touch", lambda: reply())
    idle = lambda: {e.key[1]: LOADED.idle_for(e) for e in LOADED.entries()}  # noqa: E731
    clock.now += 250
    await MANAGER.chat([])
    assert idle() == {WORKER: 0, FRONT: 250, "other:1b": 250}
    clock.now += 10
    async for _chunk in MANAGER.chat_stream([]):
        pass
    assert idle() == {WORKER: 0, FRONT: 260, "other:1b": 260}


async def test_lm_studio_instance_load_args_and_grow_never_carry_a_ttl_or_run_for_the_studio_model(monkeypatch, tmp_path):
    from app.inference import lmstudio_context
    from tests.test_keep_warm_idle_unload import write_settings

    write_settings(tmp_path, keep_warm=False)
    LOADED.record(LMSTUDIO, FOREIGN)  # even a buggy ledger entry
    row = {"identifier": FOREIGN, "modelKey": FOREIGN, "contextLength": 8192, "ttlMs": 300000}
    args = lmstudio_context.instance_load_args(row, key=FOREIGN, identifier=FOREIGN, context_length=8192)
    assert "--ttl" not in args  # lmstudio_ttl_seconds(model=) refuses it
    assert keep_alive.lmstudio_ttl_seconds(model=FOREIGN) is None
    assert keep_alive.lmstudio_ttl_seconds(model="qwen-a") == 300  # control: the guard is by name only
    commands: list[list[str]] = []

    def run(argv, **kwargs):
        import subprocess

        commands.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(lmstudio_context.subprocess, "run", run)
    monkeypatch.setattr(lmstudio_context.shutil, "which", lambda name: "/bin/lms")
    settings = settings_with(False, backend="lmstudio", host="127.0.0.1", port=1234)
    assert await lmstudio_context.grow_local_instance(settings, 65536, FOREIGN) is None
    assert commands == []  # not even `lms ps`: the name guard runs before any command


async def test_repin_skips_the_studio_model_by_name_even_when_the_ledger_and_ps_list_it(monkeypatch, tmp_path):
    import json
    import subprocess

    from app.inference import lmstudio_context
    from tests.test_keep_warm_idle_unload import write_settings

    write_settings(tmp_path, keep_warm=True)
    LOADED.record(LMSTUDIO, FOREIGN)
    commands: list[list[str]] = []

    def run(argv, **kwargs):
        args = [str(a) for a in argv]
        commands.append(args)
        row = {"identifier": FOREIGN, "modelKey": FOREIGN, "status": "idle", "queued": 0, "contextLength": 8192,
               "maxContextLength": 8192, "ttlMs": 300000}
        return subprocess.CompletedProcess(argv, 0, json.dumps([row]), "")

    monkeypatch.setattr(lmstudio_context.subprocess, "run", run)
    monkeypatch.setattr(lmstudio_context.shutil, "which", lambda name: "/bin/lms")
    settings = settings_with(True, backend="lmstudio", host="127.0.0.1", port=1234)
    assert await lmstudio_context.repin_local_instances(settings, lease=MANAGER._request_lease) == []
    assert [c for c in commands if c[1] in {"unload", "load"}] == []
