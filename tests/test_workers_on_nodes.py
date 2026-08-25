from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Node, NodeWorker
from app.db.session import SessionLocal
from app.main import app
from app.swarm.nodes import register_localhost_node
from app.swarm.workers import bind_workers_to_node, worker_catalog
from app.workers.browser import BrowserUseBackend
from app.workers.code import OpenHandsBackend
from app.workers.computer import CuaBackend, UFOBackend
from app.workers.interpreter import OpenInterpreterBackend


@pytest.fixture
def local_node_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    return jarvis_env


async def test_worker_catalog_includes_known_adapters():
    catalog = {item["id"]: item for item in worker_catalog()}
    assert catalog["browser-use"]["name"] == BrowserUseBackend.name
    assert catalog["openhands"]["name"] == OpenHandsBackend.name
    assert catalog["ufo"]["name"] == UFOBackend.name
    assert catalog["cua"]["name"] == CuaBackend.name
    assert catalog["open-interpreter"]["name"] == OpenInterpreterBackend.name
    assert catalog["cursor-acp"]["name"] == "Cursor ACP"
    assert catalog["local-llm"]["kind"] == "inference"
    assert catalog["local-jarvis-coding"]["kind"] == "coding"


async def test_workers_bind_to_localhost_node(local_node_env):
    node = await register_localhost_node()
    workers = await bind_workers_to_node(node.id)

    assert workers
    assert all(item["node_id"] == node.id for item in workers)
    assert all({"id", "name", "kind", "status", "node_id"} <= set(item) for item in workers)
    assert "browser-use" in {item["id"] for item in workers}
    assert "local-llm" in {item["id"] for item in workers}


async def test_restart_does_not_duplicate_worker_bindings(local_node_env):
    node = await register_localhost_node()
    first = await bind_workers_to_node(node.id)
    second = await bind_workers_to_node(node.id)

    async with SessionLocal() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(NodeWorker).where(NodeWorker.node_id == node.id)
            )
        ).scalar_one()

    assert count == len(first)
    assert len(second) == len(first)
    assert {item["id"] for item in first} == {item["id"] for item in second}


async def test_node_and_worker_tables_remain_distinct(local_node_env):
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)

    assert Node.__tablename__ == "nodes"
    assert NodeWorker.__tablename__ == "node_workers"
    assert Node.__tablename__ != NodeWorker.__tablename__
    assert "worker" not in node.__class__.__name__.lower()


async def test_swarm_nodes_api_includes_workers(local_node_env):
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
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
    assert isinstance(item["hardware"], dict)
    assert isinstance(item["resources"], dict)
    assert "cpu_cores" in item["resources"]
    assert isinstance(item["workers"], list)
    assert item["workers"]
    assert all(worker["node_id"] == node.id for worker in item["workers"])

    detail = client.get(f"/api/swarm/nodes/{node.id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == node.id
    assert isinstance(detail_body["workers"], list)
    assert detail_body["workers"]

    missing = client.get("/api/swarm/nodes/does-not-exist")
    assert missing.status_code == 404


async def test_worker_adapter_class_names_unchanged():
    assert BrowserUseBackend.__name__ == "BrowserUseBackend"
    assert OpenHandsBackend.__name__ == "OpenHandsBackend"
    assert UFOBackend.__name__ == "UFOBackend"
    assert CuaBackend.__name__ == "CuaBackend"
    assert OpenInterpreterBackend.__name__ == "OpenInterpreterBackend"
