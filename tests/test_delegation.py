from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.delegation import (
    clamp_autonomy,
    clamp_privacy_class,
    MANAGER,
)
from app.agent.loop import AGENT
from app.db.models import TaskEvent
from app.db.session import SessionLocal
from app.main import app


async def _create_parent_task(jarvis_env, autonomy: str = "trusted", prompt: str = "Parent task") -> str:
    task = await AGENT.create_task(prompt, autonomy=autonomy)
    if task.id in AGENT._tasks:
        AGENT._tasks[task.id].cancel()
        try:
            await AGENT._tasks[task.id]
        except asyncio.CancelledError:
            pass
    return task.id


@pytest.mark.asyncio
async def test_spawn_child_and_parent_receives_events(jarvis_env):
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    response = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={
            "task": "Summarize the notes file",
            "context": {"task_prompt": "Parent task", "task_class": ""},
            "tools": ["filesystem", "python"],
            "budget": {"max_tool_calls": 5},
            "result_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
            "autonomy": "autonomous",
            "privacy_class": "internal",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["parent_task_id"] == parent_id
    assert body["status"] == "pending"
    assert body["autonomy"] == "trusted"
    assert body["tools"] == ["filesystem", "python"]
    assert body["budget"] == {"max_tool_calls": 5}

    events = client.get(f"/api/delegation/parents/{parent_id}/events").json()
    assert any(event["kind"] == "spawned" for event in events)

    complete = client.post(
        f"/api/delegation/workers/{body['id']}/complete",
        json={"result": {"summary": "done"}},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"
    assert complete.json()["result"] == {"summary": "done"}

    events = client.get(f"/api/delegation/parents/{parent_id}/events").json()
    assert any(event["kind"] == "result" for event in events)

    async with SessionLocal() as session:
        task_events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == parent_id))
        ).scalars().all()
    assert any(row.kind == "delegation.result" for row in task_events)


def test_authority_inheritance_clamps_autonomy_and_tools(jarvis_env):
    async def _run():
        parent_id = await _create_parent_task(jarvis_env, autonomy="trusted")
        client = TestClient(app)

        child = client.post(
            f"/api/delegation/parents/{parent_id}/children",
            json={
                "task": "Run bounded work",
                "tools": ["filesystem"],
                "autonomy": "autonomous",
                "privacy_class": "public",
            },
        ).json()
        assert child["autonomy"] == "trusted"
        assert child["privacy_class"] == "internal"

        denied = client.post(
            f"/api/delegation/parents/{parent_id}/children",
            json={
                "task": "Try git",
                "tools": ["git"],
                "parent_worker_id": child["id"],
            },
        )
        assert denied.status_code == 400
        assert denied.json()["detail"]["code"] == "tool_not_allowed"

        denied_context = client.post(
            f"/api/delegation/parents/{parent_id}/children",
            json={
                "task": "Bad context",
                "context": {"secret": "nope"},
                "parent_worker_id": child["id"],
            },
        )
        assert denied_context.status_code == 400
        assert denied_context.json()["detail"]["code"] == "context_not_allowed"

    asyncio.get_event_loop().run_until_complete(_run())


def test_authority_helpers():
    assert clamp_autonomy("autonomous", "trusted") == "trusted"
    assert clamp_autonomy("interactive", "autonomous") == "interactive"
    assert clamp_privacy_class("public", "internal") == "internal"
    assert clamp_privacy_class("confidential", "internal") == "confidential"


@pytest.mark.asyncio
async def test_nested_delegation_depth_limit(jarvis_env, monkeypatch):
    monkeypatch.setattr(MANAGER, "max_depth", lambda: 2)
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    child = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Child level 1"},
    ).json()
    assert child["depth"] == 1

    grandchild = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Child level 2", "parent_worker_id": child["id"]},
    ).json()
    assert grandchild["depth"] == 2

    blocked = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Too deep", "parent_worker_id": grandchild["id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "max_depth_exceeded"


@pytest.mark.asyncio
async def test_fan_out_limit(jarvis_env, monkeypatch):
    monkeypatch.setattr(MANAGER, "max_fan_out", lambda: 2)
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    first = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "First child"},
    )
    second = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Second child"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    third = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Third child"},
    )
    assert third.status_code == 409
    assert third.json()["detail"]["code"] == "max_fan_out_exceeded"


@pytest.mark.asyncio
async def test_child_expires_and_releases_resources(jarvis_env):
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    worker = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Short task", "ttl_seconds": 1},
    ).json()

    await MANAGER.start_worker(worker["id"])
    assert worker["id"] in MANAGER._running

    await asyncio.sleep(1.2)
    expired = await MANAGER.expire_stale_workers(parent_id)
    assert expired >= 1

    refreshed = client.get(f"/api/delegation/workers/{worker['id']}").json()
    assert refreshed["status"] == "expired"
    assert worker["id"] not in MANAGER._running
    assert worker["id"] not in MANAGER._timers

    events = client.get(f"/api/delegation/parents/{parent_id}/events").json()
    assert any(event["kind"] == "expired" for event in events)


@pytest.mark.asyncio
async def test_fail_worker_emits_failure_event(jarvis_env):
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    worker = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Will fail"},
    ).json()

    failed = client.post(
        f"/api/delegation/workers/{worker['id']}/fail",
        json={"error": "tool timeout"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"] == "tool timeout"

    events = client.get(f"/api/delegation/parents/{parent_id}/events").json()
    assert any(event["kind"] == "failure" for event in events)


@pytest.mark.asyncio
async def test_list_children_filters_by_parent_worker(jarvis_env):
    parent_id = await _create_parent_task(jarvis_env)
    client = TestClient(app)

    root_child = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Root child"},
    ).json()
    nested = client.post(
        f"/api/delegation/parents/{parent_id}/children",
        json={"task": "Nested child", "parent_worker_id": root_child["id"]},
    ).json()

    root_children = client.get(f"/api/delegation/parents/{parent_id}/children").json()
    assert len(root_children) == 1
    assert root_children[0]["id"] == root_child["id"]

    nested_children = client.get(
        f"/api/delegation/parents/{parent_id}/children",
        params={"parent_worker_id": root_child["id"]},
    ).json()
    assert len(nested_children) == 1
    assert nested_children[0]["id"] == nested["id"]
