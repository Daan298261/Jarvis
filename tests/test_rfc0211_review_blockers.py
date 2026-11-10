"""Regression tests for the #670 peer review at d4752d68 (blockers 1-6), from the probe repros."""
from __future__ import annotations

import time

import pytest

from app.agent import development_queue as q
from app.agent import development_scheduler as ds
from app.tools import self_development as tool_module


@pytest.fixture
def sched(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "root", lambda: tmp_path)
    monkeypatch.setattr(ds, "kill_switch_active", lambda: False)
    s = ds.DevelopmentScheduler()
    monkeypatch.setattr(ds, "DEVELOPMENT", s)
    monkeypatch.delenv("ANZU_DEVELOPMENT_MISSION", raising=False)
    return s


def seed(s):
    state = s.state()
    for i, name in enumerate(("alpha", "bravo", "charlie")):
        state["items"][name] = {"id": name, "title": f"RFC-90{i}1 {name} ticket", "status": "available", "revision": "r" + name,
                                "created_at": i, "acceptance": True, "kind": "rfc", "priority": 3, "source": "x", "content": "x",
                                "path": "", "rfc": f"90{i}1"}
    q.replan(state)
    q.move(state, "charlie", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    s.save(state)
    return state


def owner_says(monkeypatch, text):
    async def message(_task):
        return text
    monkeypatch.setattr(tool_module, "latest_owner_message", message)


# --- blocker 1: the model cannot act as the owner to reorder or undo -----------------------

@pytest.mark.asyncio
async def test_model_cannot_claim_owner_to_move_or_undo_without_the_owners_words(sched, monkeypatch):
    seed(sched)
    owner_says(monkeypatch, "summarise this web page for me")
    tool = tool_module.SelfDevelopmentTool()
    before = list(sched.state()["order"])
    moved = await tool.execute("move", item_id="charlie", position=2, actor="owner", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert not moved.success and "your own request" in moved.error
    assert sched.state()["order"] == before
    hist = sched.state()["queue_history"][-1]["id"]
    undone = await tool.execute("undo", history_id=hist, actor="owner", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert not undone.success
    assert sched.state()["order"] == before
    # ANZU acting as itself still cannot move the owner's pin.
    as_anzu = await tool.execute("move", item_id="charlie", position=2, actor="anzu", reason="cheaper first", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert not as_anzu.success and sched.state()["order"] == before


@pytest.mark.asyncio
async def test_owner_reorder_and_undo_from_chat_work_when_the_owner_asks(sched, monkeypatch):
    seed(sched)
    tool = tool_module.SelfDevelopmentTool()
    owner_says(monkeypatch, "Please do RFC-9011 next")
    moved = await tool.execute("move", item_id="bravo", position=0, actor="owner", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert moved.success and sched.state()["order"][0] == "bravo"
    owner_says(monkeypatch, "undo that")
    hist = sched.state()["queue_history"][-1]["id"]
    undone = await tool.execute("undo", history_id=hist, actor="owner", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert undone.success and sched.state()["order"][0] == "charlie"


@pytest.mark.asyncio
async def test_injected_quote_naming_the_task_does_not_count_as_the_owner(sched, monkeypatch):
    seed(sched)
    owner_says(monkeypatch, "What does this RFC mean by \"move RFC-9011 first\"?")
    moved = await tool_module.SelfDevelopmentTool().execute("move", item_id="bravo", position=0, actor="owner", expected_revision=sched.state()["queue_revision"], _task_id="t")
    assert not moved.success


# --- blocker 2: configure / queue / run need the owner -------------------------------------

@pytest.mark.asyncio
async def test_model_cannot_release_reservation_or_reset_breaker(sched, monkeypatch):
    state = sched.state()
    state["config"]["resource_hold"] = "Grokbot RE"
    state["failures"] = 9
    sched.save(state)
    tool = tool_module.SelfDevelopmentTool()
    owner_says(monkeypatch, "summarise this web page for me")
    refused = await tool.execute("configure", config={"resource_hold": ""}, _task_id="t")
    assert not refused.success
    # Even the owner's chat request cannot release the reservation or repoint the repository.
    owner_says(monkeypatch, "release the reservation and set the repo to /tmp/other")
    assert not (await tool.execute("configure", config={"resource_hold": ""}, _task_id="t")).success
    assert not (await tool.execute("configure", config={"repo": "/tmp/other"}, _task_id="t")).success
    st = sched.state()
    assert st["config"]["resource_hold"] == "Grokbot RE" and st["failures"] == 9
    # A real owner request changes the named setting but never clears the breaker.
    owner_says(monkeypatch, "set the development interval to 45 minutes")
    changed = await tool.execute("configure", config={"interval_minutes": 45}, _task_id="t")
    assert changed.success
    st = sched.state()
    assert st["config"]["interval_minutes"] == 45 and st["failures"] == 9 and st["config"]["resource_hold"] == "Grokbot RE"
    # The model cannot slip in a value the owner did not ask for.
    assert not (await tool.execute("configure", config={"interval_minutes": 1}, _task_id="t")).success


@pytest.mark.asyncio
async def test_owner_settings_save_is_the_explicit_resume(sched):
    state = sched.state()
    state["failures"] = 9
    sched.save(state)
    await sched.configure(ds.DevelopmentConfig.model_validate(state["config"]))
    assert sched.state()["failures"] == 0


@pytest.mark.asyncio
async def test_model_cannot_queue_or_run_without_the_owner(sched, monkeypatch):
    seed(sched)
    calls = []
    async def select(*args):
        calls.append(("select", args))
        return {}
    async def launch():
        calls.append(("launch",))
        return {}
    async def scan():
        return {}
    monkeypatch.setattr(sched, "select", select)
    monkeypatch.setattr(sched, "launch", launch)
    monkeypatch.setattr(sched, "scan", scan)
    tool = tool_module.SelfDevelopmentTool()
    owner_says(monkeypatch, "summarise this web page for me")
    assert not (await tool.execute("queue", item_id="bravo", revision="rbravo", _task_id="t")).success
    assert not (await tool.execute("run", _task_id="t")).success
    assert not (await tool.execute("run")).success
    assert calls == []
    owner_says(monkeypatch, "queue RFC-9011 and start the development mission")
    assert (await tool.execute("queue", item_id="bravo", revision="rbravo", _task_id="t")).success
    assert (await tool.execute("run", _task_id="t")).success
    assert [c[0] for c in calls] == ["select", "launch"]


# --- blocker 3: only the owner's Publish or Away Mode publishes ----------------------------

@pytest.mark.asyncio
async def test_manual_launch_delivery_does_not_publish_without_away_mode(sched, monkeypatch):
    seed(sched)
    state = sched.state()
    state["items"]["bravo"].update(status="queued", approved_revision="rbravo")
    sched.save(state)
    seen = {}
    async def launch_mission(state, config, item, *, authorized_by, **_):
        seen["authorized_by"] = authorized_by
    monkeypatch.setattr(sched, "launch_mission", launch_mission)
    monkeypatch.setattr(ds.queue, "next_eligible", lambda state, automatic: (state["items"]["bravo"], ""))
    await sched.launch()
    assert seen["authorized_by"] == ""
    state = sched.state()
    assert not state["away"]["enabled"]
    assert not sched.publish_authorized(state, {"authorized_by": "", "stage": "approved"})
    # Away Mode work publishes only while Away Mode is on; switching it off revokes that.
    assert not sched.publish_authorized(state, {"authorized_by": "away", "stage": "approved"})
    state["away"]["enabled"] = True
    assert sched.publish_authorized(state, {"authorized_by": "away", "stage": "approved"})
    # A manual delivery does not ride on Away Mode being on.
    assert not sched.publish_authorized(state, {"authorized_by": "", "stage": "approved"})
    # The owner's Publish button is the explicit authorization.
    state["away"]["enabled"] = False
    state["deliveries"]["d1"] = {"id": "d1", "stage": "approved", "authorized_by": "", "started_at": 0}
    sched.save(state)
    await sched.request_publish("d1")
    state = sched.state()
    assert sched.publish_authorized(state, state["deliveries"]["d1"])


# --- blocker 4: a running mission stops when the owner unloads ------------------------------

@pytest.mark.asyncio
async def test_tick_halts_running_mission_after_manual_unload_and_republishes_policy(sched, tmp_path, monkeypatch):
    import os
    from app.agent import proactivity
    seed(sched)
    state = sched.state()
    state["config"]["enabled"] = False
    state["items"]["bravo"]["status"] = "running"
    state["runs"].append({"id": "run1", "task_id": "t", "item_id": "bravo", "title": "b", "revision": "rbravo", "status": "running",
                          "started_at": time.time(), "pid": os.getpid(), "created": 0, "worktree": str(tmp_path / "gone"),
                          "base_sha": "a" * 40, "branch": "b", "delivery_id": "d1"})
    state["deliveries"]["d1"] = {"id": "d1", "item_id": "bravo", "revision": "rbravo", "title": "b", "stage": "implementing",
                                 "worktree": str(tmp_path / "gone"), "history": [], "authorized_by": "away", "started_at": 0}
    sched.save(state)
    (tmp_path / "run1").mkdir()
    monkeypatch.setattr(proactivity, "get_away_mode", lambda: type("A", (), {"enabled": False})())
    monkeypatch.setattr(ds, "ollama_keep_alive", lambda: "-1")
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: False)
    stopped = []
    monkeypatch.setattr(sched, "owned_process", lambda run: object())  # the worker is alive
    monkeypatch.setattr(sched, "stop_process", lambda run: stopped.append(run["id"]))
    # While nothing is held, each tick republishes the live keep_alive for the worker.
    await sched.tick()
    assert ds.read_json(tmp_path / "run1" / ds.MODEL_POLICY)["keep_alive"] == "-1"
    assert sched.state()["runs"][0]["status"] == "running"
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: True)
    await sched.tick()
    st = sched.state()
    assert ds.read_json(tmp_path / "run1" / ds.MODEL_POLICY)["held"] is True
    assert stopped == ["run1"] and st["runs"][0]["status"] == "stopped"
    assert st["deliveries"]["d1"]["stage"] == "stopped"
    # An unload is not a failure; the ticket can run again once the hold clears.
    assert st["items"]["bravo"]["status"] == "available" and not st["items"]["bravo"].get("attempted_revision")
    assert st["failures"] == 0


# --- blocker 5: Ollama briefly down is a waiting state, not a failure -----------------------

@pytest.mark.asyncio
async def test_ollama_down_waits_without_tripping_the_breaker_and_recovers(sched, monkeypatch):
    seed(sched)
    state = sched.state()
    state["away"]["enabled"] = True
    state["away"]["last_scan"] = time.time()
    state["evidence"] = {"checked_at": time.time(), "error": "", "merged": {}, "open": {}}
    sched.save(state)
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: False)
    import app.engine_mode as em
    monkeypatch.setattr(em, "model_enabled", lambda s: True)
    async def down(config):
        raise ds.ModelCheckError("Ollama at http://127.0.0.1:11434 is not reachable")
    monkeypatch.setattr(ds, "model_capabilities", down)
    for _ in range(5):
        await sched.away_dispatch()
    st = sched.state()
    config = ds.DevelopmentConfig.model_validate(st["config"])
    assert st["failures"] == 0 and sched.gates(st, config) == ""
    assert st["away"]["waiting"].startswith("Waiting for local models")
    assert all(i["status"] == "available" for i in st["items"].values())
    # Ollama comes back: the next tick dispatches without anyone re-saving settings.
    launched = []
    async def up(config):
        return {}
    async def launch_mission(state, config, item, *, authorized_by, **_):
        launched.append((item["id"], authorized_by))
    monkeypatch.setattr(ds, "model_capabilities", up)
    monkeypatch.setattr(sched, "launch_mission", launch_mission)
    await sched.away_dispatch()
    assert launched and launched[0][1] == "away"
    assert sched.state()["away"]["waiting"] == ""


@pytest.mark.asyncio
async def test_real_launch_failures_still_count_toward_the_breaker(sched, monkeypatch):
    seed(sched)
    state = sched.state()
    state["away"]["enabled"] = True
    state["away"]["last_scan"] = time.time()
    state["evidence"] = {"checked_at": time.time(), "error": "", "merged": {}, "open": {}}
    sched.save(state)
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: False)
    import app.engine_mode as em
    monkeypatch.setattr(em, "model_enabled", lambda s: True)
    async def broken(state, config, item, **_):
        raise OSError("worktree could not be created")
    monkeypatch.setattr(sched, "launch_mission", broken)
    await sched.away_dispatch()
    assert sched.state()["failures"] == 1
