from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Node, NodeRolePolicy, SwarmRole
from app.db.session import SessionLocal
from app.main import app
from app.swarm.nodes import register_localhost_node
from app.swarm.roles import (
    ROLE_LEADER,
    ROLE_ORCHESTRATOR,
    ROLE_POLICIES,
    get_node_role_policies,
    get_swarm_roles,
    set_node_role_policy,
)


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_all_five_policy_levels_accepted_and_persisted(local_node_env):
    node = await register_localhost_node()

    for level in ROLE_POLICIES:
        updated = await set_node_role_policy(node.id, ROLE_ORCHESTRATOR, level)
        assert updated["policy"] == level

        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(NodeRolePolicy).where(
                        NodeRolePolicy.node_id == node.id,
                        NodeRolePolicy.role == ROLE_ORCHESTRATOR,
                    )
                )
            ).scalar_one()
        assert row.policy == level


async def test_unknown_policy_level_rejected(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    response = client.put(
        f"/api/swarm/nodes/{node.id}/role-policies/{ROLE_ORCHESTRATOR}",
        json={"policy": "BANANA"},
    )
    assert response.status_code == 400


async def test_default_localhost_policies_are_forced(local_node_env):
    node = await register_localhost_node()
    policies = await get_node_role_policies(node.id)

    by_role = {item["role"]: item["policy"] for item in policies}
    assert by_role[ROLE_ORCHESTRATOR] == "FORCED"
    assert by_role[ROLE_LEADER] == "FORCED"


async def test_disabled_prevents_role_holder_forced_restores(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    disabled = client.put(
        f"/api/swarm/nodes/{node.id}/role-policies/{ROLE_ORCHESTRATOR}",
        json={"policy": "DISABLED"},
    )
    assert disabled.status_code == 200

    roles = await get_swarm_roles()
    assert roles[ROLE_ORCHESTRATOR] is None

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()
    assert ROLE_ORCHESTRATOR not in json.loads(row.roles_json)

    restored = client.put(
        f"/api/swarm/nodes/{node.id}/role-policies/{ROLE_ORCHESTRATOR}",
        json={"policy": "FORCED"},
    )
    assert restored.status_code == 200

    roles = await get_swarm_roles()
    assert roles[ROLE_ORCHESTRATOR]["node_id"] == node.id
    assert roles[ROLE_ORCHESTRATOR]["assignment"] == "FORCED"


async def test_avoid_is_not_disabled_on_one_node_swarm(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    response = client.put(
        f"/api/swarm/nodes/{node.id}/role-policies/{ROLE_LEADER}",
        json={"policy": "AVOID"},
    )
    assert response.status_code == 200

    roles = await get_swarm_roles()
    assert roles[ROLE_LEADER] is not None
    assert roles[ROLE_LEADER]["node_id"] == node.id
    assert roles[ROLE_LEADER]["assignment"] == "AVOID"


async def test_policies_survive_register_localhost_node(local_node_env):
    node = await register_localhost_node()
    await set_node_role_policy(node.id, ROLE_ORCHESTRATOR, "PREFERRED")
    await set_node_role_policy(node.id, ROLE_LEADER, "AUTO")

    await register_localhost_node()

    policies = await get_node_role_policies(node.id)
    by_role = {item["role"]: item["policy"] for item in policies}
    assert by_role[ROLE_ORCHESTRATOR] == "PREFERRED"
    assert by_role[ROLE_LEADER] == "AUTO"


async def test_swarm_roles_api_keeps_required_fields(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    response = client.get("/api/swarm/roles")
    assert response.status_code == 200
    body = response.json()

    for role_name in (ROLE_ORCHESTRATOR, ROLE_LEADER):
        item = body[role_name]
        assert set(item.keys()) >= {"role", "node_id", "hostname", "assignment"}
        assert item["role"] == role_name
        assert item["node_id"] == node.id


async def test_orchestrator_and_leader_remain_distinct_records(local_node_env):
    await register_localhost_node()

    async with SessionLocal() as session:
        records = (await session.execute(select(SwarmRole).order_by(SwarmRole.role.asc()))).scalars().all()

    assert len(records) == 2
    assert {record.role for record in records} == {ROLE_ORCHESTRATOR, ROLE_LEADER}


async def test_node_class_stays_senior_worker(local_node_env):
    node = await register_localhost_node()

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()

    assert row.node_class == "senior_worker"


async def test_unknown_node_returns_404(local_node_env):
    client = TestClient(app)
    response = client.get("/api/swarm/nodes/does-not-exist/role-policies")
    assert response.status_code == 404

    put_response = client.put(
        "/api/swarm/nodes/does-not-exist/role-policies/orchestrator",
        json={"policy": "AUTO"},
    )
    assert put_response.status_code == 404


async def test_get_role_policies_endpoint(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    response = client.get(f"/api/swarm/nodes/{node.id}/role-policies")
    assert response.status_code == 200
    body = response.json()
    assert body["node_id"] == node.id
    assert len(body["policies"]) == 2
