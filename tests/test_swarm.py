from fastapi.testclient import TestClient

from app.main import app
from app.swarm import swarm_snapshot
from app.swarm.nodes import ensure_local_node, local_node_id
from app.swarm.workers import software_workers_on_nodes
from app.tools.capabilities import optional_workers


async def test_localhost_has_stable_node_identity(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    node = await ensure_local_node()
    assert node["is_local"] is True
    assert node["status"] == "online"
    assert node["node_class"] == "leader"
    assert "leader" in node["roles"]
    assert "orchestrator" in node["roles"]
    assert node["id"] == local_node_id()
    assert node["hostname"]
    again = await ensure_local_node()
    assert again["id"] == node["id"]
    assert (jarvis_env["tmp"] / "node_id").read_text(encoding="utf-8").strip() == node["id"]


async def test_software_workers_are_services_on_the_local_node(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    node = await ensure_local_node()
    workers = software_workers_on_nodes([node])
    by_id = {item["id"]: item for item in workers}
    assert "local-jarvis-coding" in by_id
    assert by_id["local-jarvis-coding"]["node_id"] == node["id"]
    assert by_id["local-jarvis-coding"]["service"] is True
    assert by_id["local-jarvis-coding"]["eligible_node_ids"] == [node["id"]]
    assert "browser-use" in by_id
    assert by_id["browser-use"]["status"] in {"missing", "ready"}
    assert "cursor-acp" in by_id
    assert all(item["id"] != node["id"] for item in workers)


async def test_orchestrator_is_not_the_leader_role(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    snap = await swarm_snapshot()
    assert snap["mode"] == "one-node"
    assert snap["orchestrator"]["role"] == "orchestrator"
    assert snap["orchestrator"]["kind"] == "control_plane"
    assert snap["leader"]["role"] == "leader"
    assert snap["orchestrator"]["role"] != snap["leader"]["role"]
    assert snap["orchestrator"]["node_id"] == snap["leader"]["node_id"]
    assert snap["orchestrator"]["colocated_with_leader"] is True
    assert len(snap["nodes"]) == 1
    assert snap["nodes"][0]["is_local"] is True


def test_optional_worker_catalog_has_no_stale_stubs():
    workers = {item["id"]: item for item in optional_workers()}
    assert set(workers) == {"browser-use", "ufo", "cua", "open-interpreter", "openhands"}
    for item in workers.values():
        assert item["status"] in {"missing", "ready"}


def test_swarm_api_returns_nodes_and_workers():
    client = TestClient(app)
    res = client.get("/api/swarm")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "one-node"
    assert "nodes" in body and "workers" in body
    assert body["orchestrator"]["kind"] == "control_plane"
    assert body["leader"]["role"] == "leader"
    assert body["orchestrator"]["role"] != body["leader"]["role"]
    assert any(node.get("is_local") for node in body["nodes"])
    assert any(worker.get("id") == "local-jarvis-coding" for worker in body["workers"])
