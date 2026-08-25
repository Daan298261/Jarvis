from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.swarm.nodes import register_localhost_node
from app.swarm.snapshot import swarm_snapshot
from app.swarm.workers import bind_workers_to_node


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_snapshot_keeps_orchestrator_and_leader_distinct(local_node_env):
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    snap = await swarm_snapshot()
    assert snap["mode"] == "one-node"
    assert snap["orchestrator"]["role"] == "orchestrator"
    assert snap["orchestrator"]["kind"] == "control_plane"
    assert snap["leader"]["role"] == "leader"
    assert snap["orchestrator"]["node_id"] == node.id
    assert snap["leader"]["node_id"] == node.id
    assert snap["orchestrator"]["colocated_with_leader"] is True
    assert any(item["id"] == node.id for item in snap["nodes"])
    assert snap["workers"]


def test_swarm_overview_is_additive(local_node_env):
    client = TestClient(app)
    overview = client.get("/api/swarm")
    assert overview.status_code == 200
    body = overview.json()
    assert "orchestrator" in body
    assert "leader" in body
    nodes = client.get("/api/swarm/nodes")
    assert nodes.status_code == 200
    assert "nodes" in nodes.json()
    roles = client.get("/api/swarm/roles")
    assert roles.status_code == 200
    assert "orchestrator" in roles.json()
    assert "leader" in roles.json()
