from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.coding.routing import workers_snapshot
from app.config import load_settings
from app.db.models import Node, WorkerReport
from app.db.session import SessionLocal
from app.main import app
from app.swarm.nodes import identity_path, load_or_create_local_node_id, register_localhost_node


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_node_is_not_a_worker(local_node_env):
    assert Node.__tablename__ == "nodes"
    assert WorkerReport.__tablename__ == "worker_reports"
    assert Node.__tablename__ != WorkerReport.__tablename__

    node = await register_localhost_node()
    assert "worker" not in node.__class__.__name__.lower()

    workers = workers_snapshot(load_settings())
    worker_ids = {item["id"] for item in workers}
    assert node.id not in worker_ids


async def test_localhost_registers_once(local_node_env):
    first = await register_localhost_node()
    second = await register_localhost_node()

    async with SessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(Node))).scalar_one()

    assert count == 1
    assert first.id == second.id
    assert second.host_alias == "localhost"
    assert second.address == "127.0.0.1"
    assert second.is_local is True
    assert json.loads(second.roles_json) == ["orchestrator", "leader"]


async def test_second_startup_updates_not_duplicates(local_node_env):
    first = await register_localhost_node()
    first_id = first.id
    first_seen = first.last_seen_at

    updated = await register_localhost_node()

    async with SessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(Node))).scalar_one()
        row = (await session.execute(select(Node).where(Node.id == first_id))).scalar_one()

    assert count == 1
    assert updated.id == first_id
    assert row.status == "online"
    assert row.last_seen_at is not None
    if first_seen is not None:
        assert row.last_seen_at >= first_seen
    assert row.hardware_json
    assert json.loads(row.hardware_json)


async def test_stable_node_id_persists_across_identity_reload(local_node_env):
    first_id = load_or_create_local_node_id()
    await register_localhost_node()
    reloaded_id = load_or_create_local_node_id()
    assert reloaded_id == first_id
    assert identity_path().exists()


async def test_list_and_get_nodes(local_node_env):
    node = await register_localhost_node()
    client = TestClient(app)

    listed = client.get("/api/swarm/nodes")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["nodes"]) == 1
    item = body["nodes"][0]
    assert item["id"] == node.id
    assert item["host_alias"] == "localhost"
    assert item["status"] == "online"
    assert item["class"] == "senior_worker"
    assert item["roles"] == ["orchestrator", "leader"]
    assert isinstance(item["hardware"], dict)
    assert isinstance(item["resources"], dict)
    assert "cpu_cores" in item["resources"]

    detail = client.get(f"/api/swarm/nodes/{node.id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == node.id

    missing = client.get("/api/swarm/nodes/does-not-exist")
    assert missing.status_code == 404
