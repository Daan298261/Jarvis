from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import NodeCapability, NodeWorker, SwarmRole
from app.db.session import SessionLocal
from app.main import app
from app.swarm.capabilities import detect_localhost_capabilities, register_localhost_capabilities
from app.swarm.nodes import register_localhost_node
from app.swarm.roles import ROLE_LEADER, ROLE_ORCHESTRATOR
from app.swarm.workers import bind_workers_to_node
from app.tools.capabilities import capability_snapshot, optional_workers


def test_browser_use_worker_reflects_install_state():
    workers = {item["id"]: item for item in optional_workers()}
    for key in ("ufo", "cua", "open-interpreter", "openhands", "browser-use"):
        assert workers[key]["available"] is False or workers[key]["status"] == "ready"
        assert workers[key]["status"] in {"missing", "ready", "not_integrated"}
    assert workers["browser-use"]["status"] in {"missing", "ready"}
    assert workers["openhands"]["status"] in {"missing", "ready"}
    if workers["browser-use"]["status"] == "missing":
        assert workers["browser-use"]["available"] is False
    if workers["openhands"]["status"] == "missing":
        assert workers["openhands"]["available"] is False


def test_capability_snapshot_includes_native_filesystem():
    snap = capability_snapshot()
    native = {item["id"]: item for item in snap["native"]}
    assert native["filesystem"]["available"] is True
    assert native["git"]["available"] is True
    assert native["office"]["status"] in {"ready", "unavailable"}
    assert len(snap["all"]) == len(snap["native"]) + len(snap["optional_workers"])
    policy = snap["professional_analysis"]
    assert policy["analyze_sensitive_material"] is True
    assert policy["operational_authorization_separate"] is True


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_capabilities_are_distinct_from_roles_and_workers(local_node_env):
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    capabilities = await register_localhost_capabilities(node.id)

    async with SessionLocal() as session:
        role_count = (await session.execute(select(func.count()).select_from(SwarmRole))).scalar_one()
        worker_count = (
            await session.execute(
                select(func.count()).select_from(NodeWorker).where(NodeWorker.node_id == node.id)
            )
        ).scalar_one()
        capability_count = (
            await session.execute(
                select(func.count()).select_from(NodeCapability).where(NodeCapability.node_id == node.id)
            )
        ).scalar_one()

    assert NodeCapability.__tablename__ == "node_capabilities"
    assert NodeCapability.__tablename__ != SwarmRole.__tablename__
    assert NodeCapability.__tablename__ != NodeWorker.__tablename__
    assert role_count == 2
    assert worker_count > 0
    assert capability_count == len(capabilities)
    assert capabilities


async def test_localhost_capabilities_are_detected_and_bound(local_node_env):
    node = await register_localhost_node()
    capabilities = await register_localhost_capabilities(node.id)

    detected = {item["id"]: item for item in detect_localhost_capabilities()}
    bound = {item["id"]: item for item in capabilities}

    assert bound
    assert all(item["node_id"] == node.id for item in capabilities)
    assert all({"id", "name", "status", "detail", "node_id"} <= set(item) for item in capabilities)
    assert "filesystem" in bound
    assert "tool_execution" in bound
    assert bound["filesystem"]["status"] == detected["filesystem"]["status"]


async def test_restart_does_not_duplicate_capability_bindings(local_node_env):
    node = await register_localhost_node()
    first = await register_localhost_capabilities(node.id)
    second = await register_localhost_capabilities(node.id)

    async with SessionLocal() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(NodeCapability).where(NodeCapability.node_id == node.id)
            )
        ).scalar_one()

    assert count == len(first)
    assert len(second) == len(first)
    assert {item["id"] for item in first} == {item["id"] for item in second}


async def test_capability_ids_are_not_role_names(local_node_env):
    await register_localhost_node()
    detected_ids = {item["id"] for item in detect_localhost_capabilities()}

    assert ROLE_ORCHESTRATOR not in detected_ids
    assert ROLE_LEADER not in detected_ids
    assert "orchestrator" not in detected_ids
    assert "leader" not in detected_ids


async def test_swarm_capabilities_api_matches_bound_records(local_node_env):
    node = await register_localhost_node()
    bound = await register_localhost_capabilities(node.id)
    client = TestClient(app)

    response = client.get("/api/swarm/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["capabilities"], list)
    assert body["capabilities"]
    assert all(item["node_id"] == node.id for item in body["capabilities"])
    assert {item["id"] for item in body["capabilities"]} == {item["id"] for item in bound}


async def test_swarm_nodes_api_includes_capabilities(local_node_env):
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    await register_localhost_capabilities(node.id)
    client = TestClient(app)

    listed = client.get("/api/swarm/nodes")
    assert listed.status_code == 200
    item = listed.json()["nodes"][0]
    assert item["class"] == "senior_worker"
    assert isinstance(item["capabilities"], list)
    assert item["capabilities"]
    assert all(cap["node_id"] == node.id for cap in item["capabilities"])

    detail = client.get(f"/api/swarm/nodes/{node.id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["class"] == "senior_worker"
    assert isinstance(detail_body["capabilities"], list)
    assert detail_body["capabilities"]
