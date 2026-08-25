from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Node, SwarmRole
from app.db.session import SessionLocal
from app.main import app
from app.swarm.nodes import register_localhost_node
from app.swarm.roles import ROLE_LEADER, ROLE_ORCHESTRATOR, get_swarm_roles


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_orchestrator_and_leader_are_distinct_role_records(local_node_env):
    node = await register_localhost_node()

    async with SessionLocal() as session:
        records = (await session.execute(select(SwarmRole).order_by(SwarmRole.role.asc()))).scalars().all()

    assert len(records) == 2
    role_names = {record.role for record in records}
    assert role_names == {ROLE_ORCHESTRATOR, ROLE_LEADER}
    assert ROLE_ORCHESTRATOR != ROLE_LEADER
    for record in records:
        assert record.node_id == node.id
        assert record.assignment == "FORCED"


async def test_localhost_may_hold_both_roles(local_node_env):
    node = await register_localhost_node()
    roles = await get_swarm_roles()

    assert roles[ROLE_ORCHESTRATOR]["node_id"] == node.id
    assert roles[ROLE_LEADER]["node_id"] == node.id
    assert roles[ROLE_ORCHESTRATOR]["role"] == ROLE_ORCHESTRATOR
    assert roles[ROLE_LEADER]["role"] == ROLE_LEADER


async def test_swarm_roles_api_matches_nodes_api(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    roles_response = client.get("/api/swarm/roles")
    nodes_response = client.get("/api/swarm/nodes")
    assert roles_response.status_code == 200
    assert nodes_response.status_code == 200

    roles_body = roles_response.json()
    nodes_body = nodes_response.json()
    node_item = nodes_body["nodes"][0]

    assert roles_body[ROLE_ORCHESTRATOR]["node_id"] == node.id
    assert roles_body[ROLE_LEADER]["node_id"] == node.id
    assert roles_body[ROLE_ORCHESTRATOR]["hostname"] == node_item["hostname"]
    assert roles_body[ROLE_LEADER]["hostname"] == node_item["hostname"]
    assert set(node_item["roles"]) == {ROLE_ORCHESTRATOR, ROLE_LEADER}
    assert node_item["class"] != ROLE_LEADER


async def test_node_class_is_not_leader_role(local_node_env):
    node = await register_localhost_node()

    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node.id))).scalar_one()

    assert row.node_class == "senior_worker"
    assert json.loads(row.roles_json) == [ROLE_ORCHESTRATOR, ROLE_LEADER]
