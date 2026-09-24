"""RFC-0174 Agent Rooms portal API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.rooms import reset_registry


@pytest.fixture(autouse=True)
def _clean_rooms():
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def client(jarvis_env, allow_loopback_api):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_index_lists_rooms_and_anzu_specialist_roster(client):
    response = client.get("/api/agent-rooms")
    assert response.status_code == 200
    body = response.json()
    assert body["rooms"] == []
    ids = [row["id"] for row in body["roster"]]
    assert "anzu" not in ids
    assert "enki" in ids
    assert "nabu" in ids
    assert "eir" in ids
    assert len(ids) == 12
    enki = next(row for row in body["roster"] if row["id"] == "enki")
    assert enki["label"] == "Enki"
    assert enki["phrase"]


def test_create_get_messages_handoff_blackboard_audit_synthesize(client):
    created = client.post(
        "/api/agent-rooms",
        json={
            "goal": "Plan and implement auth",
            "specialists": ["Mestor", "eagir"],
            "cost_mode": "balanced",
            "privacy_mode": "local_only",
            "supervisor_model": "qwen-local",
            "specialist_models": {"mestor": "planner-9b"},
        },
    )
    assert created.status_code == 200, created.text
    room = created.json()
    assert room["status"] == "open"
    assert room["goal"] == "Plan and implement auth"
    roles = {p["agent_id"]: p for p in room["participants"]}
    assert roles["anzu"]["role"] == "supervisor"
    assert roles["anzu"]["model"] == "qwen-local"
    assert roles["mestor"]["model"] == "planner-9b"
    assert "aegir" in roles
    assert "eagir" not in roles
    assert len(room["task_graph"]["tasks"]) == 2

    room_id = room["id"]
    fetched = client.get(f"/api/agent-rooms/{room_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == room_id

    task_id = room["task_graph"]["tasks"][0]["id"]
    posted = client.post(
        f"/api/agent-rooms/{room_id}/messages",
        json={
            "kind": "REQUEST",
            "from_agent": "anzu",
            "to_agent": "mestor",
            "body": "<think>secret plan</think>@mestor draft the plan",
            "rationale": "<think>hidden</think>needs a plan",
            "task_id": task_id,
        },
    )
    assert posted.status_code == 200, posted.text
    message = posted.json()
    assert "secret" not in message["body"].lower()
    assert "think" not in message["body"].lower()
    assert "draft the plan" in message["body"]
    assert "hidden" not in message["rationale"]
    assert message["kind"] == "REQUEST"

    handed = client.post(
        f"/api/agent-rooms/{room_id}/handoff",
        json={
            "from_agent": "mestor",
            "to_agent": "aegir",
            "body": "plan ready — please implement",
            "task_id": task_id,
            "rationale": "mestor finished planning",
        },
    )
    assert handed.status_code == 200, handed.text
    handoff = handed.json()
    assert handoff["kind"] == "HANDOFF"
    assert handoff["rationale"] == "mestor finished planning"
    assert handoff["to_agent"] == "aegir"

    board = client.post(
        f"/api/agent-rooms/{room_id}/blackboard",
        json={
            "kind": "artifact",
            "key": "plan.md",
            "content": "<think>nope</think>auth plan",
            "author": "mestor",
        },
    )
    assert board.status_code == 200, board.text
    assert board.json()["content"] == "auth plan"

    snapshot = client.get(f"/api/agent-rooms/{room_id}/blackboard")
    assert snapshot.status_code == 200
    assert snapshot.json()["counts"]["artifacts"] == 1

    audit = client.get(f"/api/agent-rooms/{room_id}/audit")
    assert audit.status_code == 200
    replay = audit.json()
    assert replay["event_count"] >= 1
    assert replay["handoffs"]
    assert replay["handoffs"][-1]["rationale"] == "mestor finished planning"
    blob = str(replay).lower()
    assert "secret plan" not in blob
    assert "chain_of_thought" not in blob

    listed = client.get("/api/agent-rooms")
    assert any(item["id"] == room_id for item in listed.json()["rooms"])

    synthesis = client.post(f"/api/agent-rooms/{room_id}/synthesize")
    assert synthesis.status_code == 200, synthesis.text
    body = synthesis.json()
    assert body["synthesis"]["cited_artifact_ids"]
    assert "plan.md" in body["synthesis"]["summary"]
    assert "mestor" in body["synthesis"]["cited_agents"]
    assert body["room"]["status"] == "terminated"
    assert body["room"]["synthesis"]["rationale"]

    messages = client.get(f"/api/agent-rooms/{room_id}/messages")
    assert messages.status_code == 200
    kinds = [item["kind"] for item in messages.json()["messages"]]
    assert "HANDOFF" in kinds
    assert "FINAL" in kinds


def test_unknown_specialist_missing_room_and_terminated_are_hard_errors(client):
    unknown = client.post(
        "/api/agent-rooms",
        json={"goal": "Ship it", "specialists": ["not-a-persona"]},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "unknown_specialist"

    missing = client.get("/api/agent-rooms/does-not-exist")
    assert missing.status_code == 404
    assert "does-not-exist" in missing.json()["detail"]

    created = client.post(
        "/api/agent-rooms",
        json={"goal": "Close this", "specialists": ["enki"]},
    )
    assert created.status_code == 200
    room_id = created.json()["id"]
    closed = client.post(
        f"/api/agent-rooms/{room_id}/terminate",
        json={"reason": "owner stopped the room"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "terminated"

    rejected = client.post(
        f"/api/agent-rooms/{room_id}/messages",
        json={"kind": "REQUEST", "from_agent": "anzu", "body": "@enki continue"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "room_terminated"


def test_blackboard_bound_and_bad_cost_mode_fail_loudly(client):
    created = client.post(
        "/api/agent-rooms",
        json={"goal": "Bound the board", "specialists": ["nabu"]},
    )
    room_id = created.json()["id"]
    huge = client.post(
        f"/api/agent-rooms/{room_id}/blackboard",
        json={"kind": "fact", "key": "overflow", "content": "x" * 5000, "author": "nabu"},
    )
    assert huge.status_code == 400
    assert huge.json()["detail"]["code"] == "blackboard_bound"

    bad_mode = client.post(
        "/api/agent-rooms",
        json={"goal": "Bad budget", "specialists": ["enki"], "cost_mode": "unlimited"},
    )
    assert bad_mode.status_code == 400
    assert "cost_mode" in bad_mode.json()["detail"]["message"]
