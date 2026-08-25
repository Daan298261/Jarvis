from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Node, NodeBudget, ResourceLease
from app.db.session import SessionLocal
from app.main import app
from app.swarm.budgets import (
    acquire_lease,
    get_node_budget,
    list_node_leases,
)
from app.swarm.nodes import register_localhost_node
from app.swarm.roles import ROLE_LEADER, ROLE_ORCHESTRATOR


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_default_budget_created_for_localhost(local_node_env):
    node = await register_localhost_node()
    budget = await get_node_budget(node.id)

    assert budget is not None
    assert budget["preset"] == "balanced"
    assert budget["global_percent"] == 50
    assert budget["mode"] == "static"
    assert budget["limits"] == {}
    assert "effective" in budget
    assert "remaining" in budget

    async with SessionLocal() as session:
        row = (await session.execute(select(NodeBudget).where(NodeBudget.node_id == node.id))).scalar_one()
    assert row.preset == "balanced"
    assert row.global_percent == 50


async def test_put_budget_persists_and_reregister_does_not_overwrite(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    response = client.put(
        f"/api/swarm/nodes/{node.id}/budget",
        json={
            "preset": "custom",
            "global_percent": 35,
            "limits": {"cpu": {"percent": 40, "cap": "HARD"}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["preset"] == "custom"
    assert body["global_percent"] == 35
    assert body["limits"]["cpu"]["percent"] == 40
    assert body["limits"]["cpu"]["cap"] == "HARD"

    await register_localhost_node()

    budget = await get_node_budget(node.id)
    assert budget["preset"] == "custom"
    assert budget["global_percent"] == 35
    assert budget["limits"]["cpu"]["cap"] == "HARD"


async def test_global_percent_validation(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    for invalid in (-1, 101):
        response = client.put(
            f"/api/swarm/nodes/{node.id}/budget",
            json={"preset": "custom", "global_percent": invalid},
        )
        assert response.status_code == 400

    non_numeric = client.put(
        f"/api/swarm/nodes/{node.id}/budget",
        json={"preset": "custom", "global_percent": "abc"},
    )
    assert non_numeric.status_code in (400, 422)

    invalid_preset = client.put(
        f"/api/swarm/nodes/{node.id}/budget",
        json={"preset": "banana", "global_percent": 50},
    )
    assert invalid_preset.status_code == 400


async def test_hard_cap_blocks_oversized_lease(local_node_env):
    node = await register_localhost_node()
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

    blocked = client.post(
        f"/api/swarm/nodes/{node.id}/leases",
        json={"claim": {"cpu_threads": 6}, "ttl_seconds": 60},
    )
    assert blocked.status_code == 400
    assert "HARD cap" in blocked.json()["detail"]

    allowed = client.post(
        f"/api/swarm/nodes/{node.id}/leases",
        json={"claim": {"cpu_threads": 4}, "ttl_seconds": 60},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "active"


async def test_soft_cap_allows_oversized_lease(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()
        row.resources_json = '{"cpu_threads": 10, "ram_total_gb": 64}'
        await session.commit()

    put = client.put(
        f"/api/swarm/nodes/{node.id}/budget",
        json={
            "preset": "custom",
            "global_percent": 50,
            "limits": {"cpu": {"percent": 50, "cap": "SOFT"}},
        },
    )
    assert put.status_code == 200

    oversized = client.post(
        f"/api/swarm/nodes/{node.id}/leases",
        json={"claim": {"cpu_threads": 8}, "ttl_seconds": 60},
    )
    assert oversized.status_code == 200
    assert oversized.json()["status"] == "active"


async def test_expired_lease_no_longer_counts(local_node_env, monkeypatch):
    node = await register_localhost_node()
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.swarm.budgets._utcnow", lambda: fixed_now)

    lease = await acquire_lease(
        node.id,
        {"ram_gb": 4},
        ttl_seconds=60,
        now=fixed_now,
    )
    assert lease["status"] == "active"

    budget_before = await get_node_budget(node.id)
    assert budget_before["remaining"]["ram"] < budget_before["effective"]["ram"]

    later = fixed_now + timedelta(seconds=120)
    monkeypatch.setattr("app.swarm.budgets._utcnow", lambda: later)

    leases = await list_node_leases(node.id)
    expired = next(item for item in leases if item["id"] == lease["id"])
    assert expired["status"] == "expired"

    budget_after = await get_node_budget(node.id)
    assert budget_after["remaining"]["ram"] == budget_after["effective"]["ram"]


async def test_release_removes_claim(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    created = client.post(
        f"/api/swarm/nodes/{node.id}/leases",
        json={"claim": {"ram_gb": 6}, "ttl_seconds": 300},
    )
    assert created.status_code == 200
    lease_id = created.json()["id"]

    before = await get_node_budget(node.id)
    assert before["remaining"]["ram"] == before["effective"]["ram"] - 6

    released = client.delete(f"/api/swarm/nodes/{node.id}/leases/{lease_id}")
    assert released.status_code == 200
    assert released.json()["status"] == "released"

    after = await get_node_budget(node.id)
    assert after["remaining"]["ram"] == after["effective"]["ram"]


async def test_existing_role_endpoints_still_work(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    roles = client.get("/api/swarm/roles")
    assert roles.status_code == 200
    body = roles.json()
    for role_name in (ROLE_ORCHESTRATOR, ROLE_LEADER):
        item = body[role_name]
        assert set(item.keys()) >= {"role", "node_id", "hostname", "assignment"}
        assert item["node_id"] == node.id

    policies = client.get(f"/api/swarm/nodes/{node.id}/role-policies")
    assert policies.status_code == 200
    assert policies.json()["node_id"] == node.id
    assert len(policies.json()["policies"]) == 2


async def test_node_class_stays_senior_worker(local_node_env):
    node = await register_localhost_node()

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()

    assert row.node_class == "senior_worker"


async def test_unknown_node_returns_404(local_node_env):
    client = TestClient(app)

    assert client.get("/api/swarm/nodes/missing/budget").status_code == 404
    assert client.put("/api/swarm/nodes/missing/budget", json={"preset": "balanced"}).status_code == 404
    assert client.get("/api/swarm/nodes/missing/leases").status_code == 404
    assert client.post("/api/swarm/nodes/missing/leases", json={"claim": {"cpu_threads": 1}}).status_code == 404
    assert client.delete("/api/swarm/nodes/missing/leases/lease-1").status_code == 404


async def test_get_budget_and_list_leases_endpoints(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    budget = client.get(f"/api/swarm/nodes/{node.id}/budget")
    assert budget.status_code == 200
    assert budget.json()["node_id"] == node.id

    created = client.post(
        f"/api/swarm/nodes/{node.id}/leases",
        json={"claim": {"disk_gb": 1}, "ttl_seconds": 120},
    )
    assert created.status_code == 200

    listed = client.get(f"/api/swarm/nodes/{node.id}/leases")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["node_id"] == node.id
    assert len(payload["leases"]) == 1
    assert payload["leases"][0]["claim"]["disk_gb"] == 1

    async with SessionLocal() as session:
        count = (await session.execute(select(ResourceLease).where(ResourceLease.node_id == node.id))).scalars().all()
    assert len(count) == 1
