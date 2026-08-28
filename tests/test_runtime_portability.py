from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.portability import (
    SchedulerError,
    acquire_runtime_lease,
    create_agent_profile,
    deserialize_portable_state,
    get_agent_profile,
    list_audit_events,
    migrate_agent,
    release_runtime_lease,
    resume_agent,
    serialize_portable_state,
    suspend_agent,
    PortableAgentState,
    check_runtime_compatibility,
)
from app.inference.runtime_profiles import (
    RuntimeProfile,
    create_runtime_profile,
    reset_runtime_profiles,
)
from app.main import app


@pytest.fixture
def runtime_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    reset_runtime_profiles()
    return jarvis_env["tmp"]


@pytest.fixture
def scripted_profiles(runtime_store):
    local = create_runtime_profile(
        name="scripted-local",
        label="Scripted Local",
        model="Qwen3.5-9B",
        provider="local-llama",
        endpoint="127.0.0.1:8088",
        capability_tags=["llm_inference", "text", "tool:filesystem", "tool:terminal"],
        is_local=True,
    )
    remote = create_runtime_profile(
        name="scripted-remote",
        label="Scripted Remote",
        model="gpt-4o-mini",
        provider="openai-compat",
        endpoint="https://api.example.com/v1",
        capability_tags=["llm_inference", "text", "tool:browser", "tool:filesystem"],
        is_local=False,
    )
    return {"local": local, "remote": remote}


@pytest.mark.asyncio
async def test_agent_id_stable_across_runtime_changes(jarvis_env, scripted_profiles):
    created = await create_agent_profile(
        name="researcher",
        memory={"notes": "alpha"},
        policy={"autonomy": "trusted"},
        skill_refs=["skill-1"],
        goals=[{"id": "g1", "title": "Summarize docs"}],
        task_state={"stage": "acting", "step": 2},
        required_capabilities=["llm_inference", "text"],
        required_tools=["filesystem"],
    )
    agent_id = created["id"]

    lease_a = await acquire_runtime_lease(
        agent_id,
        runtime_profile_id=scripted_profiles["local"].id,
        node_id="node-a",
    )
    assert lease_a["agent_id"] == agent_id
    assert lease_a["model"] == "Qwen3.5-9B"
    assert lease_a["endpoint"] == "127.0.0.1:8088"

    migrated = await migrate_agent(
        agent_id,
        target_runtime_profile_id=scripted_profiles["remote"].id,
        node_id="node-b",
    )
    assert migrated["id"] == agent_id
    assert migrated["lease"]["model"] == "gpt-4o-mini"
    assert migrated["lease"]["endpoint"] == "https://api.example.com/v1"
    assert migrated["previous_lease"]["id"] == lease_a["id"]

    profile = await get_agent_profile(agent_id)
    assert profile["id"] == agent_id
    assert profile["state"]["memory"] == {"notes": "alpha"}
    assert profile["state"]["policy"] == {"autonomy": "trusted"}
    assert profile["state"]["skill_refs"] == ["skill-1"]
    assert profile["state"]["goals"] == [{"id": "g1", "title": "Summarize docs"}]
    assert profile["state"]["task_state"] == {"stage": "acting", "step": 2}


def test_portable_state_roundtrip():
    state = PortableAgentState(
        memory={"k": "v"},
        policy={"mode": "trusted"},
        skill_refs=["s1"],
        goals=[{"goal": "finish"}],
        task_state={"status": "running"},
        provenance=[{"event": "created"}],
        required_tools=["filesystem"],
        required_capabilities=["llm_inference"],
    )
    restored = deserialize_portable_state(serialize_portable_state(state))
    assert restored.as_dict() == state.as_dict()


def test_incompatible_runtime_raises_scheduler_error(scripted_profiles):
    state = PortableAgentState(
        required_capabilities=["llm_inference", "vision"],
        required_tools=["filesystem"],
    )
    runtime = RuntimeProfile(
        id="tiny",
        name="tiny",
        label="Tiny",
        model="small",
        provider="local-llama",
        endpoint="127.0.0.1:9000",
        context_limit=4096,
        quantization="Q4",
        privacy_class="local-only",
        cost_ceiling_usd=0.0,
        capability_tags=("llm_inference", "text", "tool:filesystem"),
    )
    with pytest.raises(SchedulerError, match="vision"):
        check_runtime_compatibility(state, runtime)

    state_tools = PortableAgentState(required_tools=["browser"])
    with pytest.raises(SchedulerError, match="browser"):
        check_runtime_compatibility(state_tools, runtime)


@pytest.mark.asyncio
async def test_suspend_resume_preserves_state(jarvis_env, scripted_profiles):
    created = await create_agent_profile(
        name="coder",
        memory={"context": "persist"},
        task_state={"checkpoint": 3},
    )
    agent_id = created["id"]
    lease = await acquire_runtime_lease(
        agent_id,
        runtime_profile_id=scripted_profiles["local"].id,
    )
    await release_runtime_lease(lease["id"])
    await suspend_agent(agent_id)

    resumed = await resume_agent(
        agent_id,
        runtime_profile_id=scripted_profiles["remote"].id,
        node_id="node-c",
    )
    assert resumed["id"] == agent_id
    assert resumed["state"]["memory"] == {"context": "persist"}
    assert resumed["state"]["task_state"] == {"checkpoint": 3}
    assert resumed["lease"]["runtime_profile_id"] == scripted_profiles["remote"].id
    assert any(item.get("event") == "resumed" for item in resumed["state"]["provenance"])


@pytest.mark.asyncio
async def test_audit_log_preserves_executor_history(jarvis_env, scripted_profiles):
    created = await create_agent_profile(name="audited")
    agent_id = created["id"]
    await acquire_runtime_lease(agent_id, runtime_profile_id=scripted_profiles["local"].id, node_id="n1")
    await migrate_agent(
        agent_id,
        target_runtime_profile_id=scripted_profiles["remote"].id,
        node_id="n2",
    )

    events = await list_audit_events(agent_id=agent_id, limit=50)
    kinds = [event["event"] for event in events]
    assert "created" in kinds
    assert "lease_acquired" in kinds
    assert "migrated" in kinds
    assert "lease_released" in kinds

    models = {event["model"] for event in events if event["model"]}
    assert "Qwen3.5-9B" in models
    assert "gpt-4o-mini" in models
    nodes = {event["node_id"] for event in events if event["node_id"]}
    assert {"n1", "n2"}.issubset(nodes)


@pytest.mark.asyncio
async def test_dispatch_rejects_incompatible_runtime(jarvis_env, scripted_profiles):
    created = await create_agent_profile(
        name="vision-agent",
        required_capabilities=["vision"],
    )
    with pytest.raises(SchedulerError):
        await acquire_runtime_lease(
            created["id"],
            runtime_profile_id=scripted_profiles["local"].id,
        )


def test_api_moves_agent_between_scripted_profiles(jarvis_env, runtime_store, scripted_profiles):
    client = TestClient(app)

    created = client.post(
        "/api/agent-portability",
        json={
            "name": "api-agent",
            "memory": {"thread": "main"},
            "policy": {"privacy": "internal"},
            "task_state": {"cursor": 1},
            "required_capabilities": ["llm_inference"],
            "required_tools": ["filesystem"],
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    lease = client.post(
        f"/api/agent-portability/{agent_id}/lease",
        json={
            "runtime_profile_id": scripted_profiles["local"].id,
            "node_id": "desktop-1",
        },
    )
    assert lease.status_code == 200
    assert lease.json()["agent_id"] == agent_id

    migrated = client.post(
        f"/api/agent-portability/{agent_id}/migrate",
        json={
            "target_runtime_profile_id": scripted_profiles["remote"].id,
            "node_id": "cloud-1",
        },
    )
    assert migrated.status_code == 200
    body = migrated.json()
    assert body["id"] == agent_id
    assert body["state"]["memory"] == {"thread": "main"}
    assert body["lease"]["runtime_profile_id"] == scripted_profiles["remote"].id

    audit = client.get(f"/api/agent-portability/audit?agent_id={agent_id}").json()
    assert any(event["event"] == "migrated" for event in audit["events"])


def test_api_incompatible_runtime_returns_409(jarvis_env, runtime_store, scripted_profiles):
    client = TestClient(app)
    created = client.post(
        "/api/agent-portability",
        json={
            "name": "blocked",
            "required_tools": ["browser"],
        },
    )
    agent_id = created.json()["id"]
    response = client.post(
        f"/api/agent-portability/{agent_id}/lease",
        json={"runtime_profile_id": scripted_profiles["local"].id},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "missing_tools"


def test_serialized_state_has_no_runtime_objects():
    state = PortableAgentState(memory={"x": 1})
    blob = serialize_portable_state(state)
    payload = json.loads(blob)
    assert set(payload.keys()) == {
        "version",
        "memory",
        "policy",
        "skill_refs",
        "goals",
        "task_state",
        "provenance",
        "required_tools",
        "required_capabilities",
    }
    assert "RuntimeProfile" not in blob
