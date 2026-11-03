"""RFC-0242 "Reconciliation with #690": the contract closers, one named test per row (and the guard coverage)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.agent.loop import AGENT
from app.config import AppSettings
from app.inference import keep_alive, keep_warm_release
from app.inference.idle_unload import IDLE_UNLOAD, IdleUnload
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
