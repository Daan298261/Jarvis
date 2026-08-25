from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Node, ResourceLease
from app.db.session import SessionLocal
from app.main import app
from app.swarm.budgets import get_node_budget
from app.swarm.capabilities import register_localhost_capabilities
from app.swarm.nodes import register_localhost_node
from app.swarm.placement import place_work
from app.swarm.roles import ROLE_ORCHESTRATOR
from app.swarm.workers import bind_workers_to_node


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def _setup_local_node():
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    await register_localhost_capabilities(node.id)
    return node


async def test_default_empty_requirements_places_on_localhost(local_node_env):
    node = await _setup_local_node()
    result = await place_work({"capabilities": []})

    assert result["accepted"] is True
    assert result["node_id"] == node.id
    assert result["hostname"]
    assert result["worker"]["node_id"] == node.id
    assert "id" in result["worker"]
    assert result["reason"] == "placed on localhost"
    assert "lease" not in result


async def test_missing_capability_rejected(local_node_env):
    node = await _setup_local_node()
    result = await place_work({"capabilities": ["totally_fake_capability"]})

    assert result["accepted"] is False
    assert result["code"] == "missing_capability"
    assert "totally_fake_capability" in result["reason"]


async def test_disabled_orchestrator_role_rejected(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    disabled = client.put(
        f"/api/swarm/nodes/{node.id}/role-policies/{ROLE_ORCHESTRATOR}",
        json={"policy": "DISABLED"},
    )
    assert disabled.status_code == 200

    result = await place_work({"capabilities": [], "role": ROLE_ORCHESTRATOR})
    assert result["accepted"] is False
    assert result["code"] == "role_disabled"


async def test_hard_cap_rejects_oversized_claim_without_lease(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()
        row.resources_json = (
            '{"cpu_threads": 10, "ram_total_gb": 64, "disk_total_gb": 500, "vram_total_mib": 16384}'
        )
        await session.commit()

    put = client.put(
        f"/api/swarm/nodes/{node.id}/budget",
        json={
            "preset": "custom",
            "global_percent": 50,
            "limits": {"cpu": {"percent": 50, "cap": "HARD"}},
        },
    )
    assert put.status_code == 200

    result = await place_work(
        {
            "capabilities": [],
            "claim": {"cpu_threads": 6},
            "ttl_seconds": 60,
        }
    )
    assert result["accepted"] is False
    assert result["code"] == "hard_cap"

    async with SessionLocal() as session:
        active = (
            await session.execute(
                select(ResourceLease).where(
                    ResourceLease.node_id == node.id,
                    ResourceLease.status == "active",
                )
            )
        ).scalars().all()
    assert active == []


async def test_matching_capability_accepted(local_node_env):
    node = await _setup_local_node()

    for capability_id in ("filesystem", "tool_execution"):
        result = await place_work({"capabilities": [capability_id]})
        assert result["accepted"] is True
        assert result["node_id"] == node.id
        assert result["worker"]["node_id"] == node.id


async def test_accept_with_claim_acquires_lease(local_node_env):
    node = await _setup_local_node()
    budget_before = await get_node_budget(node.id)
    remaining_before = budget_before["remaining"]["cpu"]

    result = await place_work(
        {
            "capabilities": [],
            "claim": {"cpu_threads": 1},
            "ttl_seconds": 120,
        }
    )
    assert result["accepted"] is True
    assert result["lease"]["status"] == "active"
    assert result["lease"]["claim"]["cpu_threads"] == 1

    budget_after = await get_node_budget(node.id)
    assert budget_after["remaining"]["cpu"] == remaining_before - 1


async def test_budget_and_role_policy_routes_still_ok(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    budget = client.get(f"/api/swarm/nodes/{node.id}/budget")
    assert budget.status_code == 200

    policies = client.get(f"/api/swarm/nodes/{node.id}/role-policies")
    assert policies.status_code == 200
    assert isinstance(policies.json()["policies"], list)


async def test_node_class_still_senior_worker(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    listed = client.get("/api/swarm/nodes")
    assert listed.status_code == 200
    item = listed.json()["nodes"][0]
    assert item["id"] == node.id
    assert item["class"] == "senior_worker"


async def test_placement_http_accept_and_reject(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    accepted = client.post("/api/swarm/placement", json={"capabilities": []})
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True

    rejected = client.post(
        "/api/swarm/placement",
        json={"capabilities": ["nonexistent_capability_id"]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "missing_capability"

    invalid = client.post("/api/swarm/placement", json={"capabilities": "not-a-list"})
    assert invalid.status_code in (400, 422)
