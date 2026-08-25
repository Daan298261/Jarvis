from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.inference.manager import MANAGER
from app.main import app
from app.swarm.capabilities import register_localhost_capabilities
from app.swarm.nodes import register_localhost_node
from app.swarm.placement import place_work
from app.swarm.scoring import probe_node_warm_state, score_candidate
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


def _inference_worker(*, worker_id: str = "local-llm", status: str = "ready", node_id: str) -> dict:
    return {
        "id": worker_id,
        "name": "Local LLM",
        "kind": "inference",
        "status": status,
        "node_id": node_id,
    }


def _fake_node_dict(
    *,
    node_id: str,
    is_local: bool,
    workers: list[dict],
    capabilities: list[dict] | None = None,
    data_paths_present: list[str] | None = None,
) -> dict:
    payload = {
        "id": node_id,
        "hostname": f"node-{node_id[:8]}",
        "status": "online",
        "class": "senior_worker",
        "roles": [],
        "address": "127.0.0.1" if is_local else "10.0.0.2",
        "host_alias": "localhost" if is_local else "",
        "is_local": is_local,
        "hardware": {},
        "resources": {},
        "workers": workers,
        "capabilities": capabilities or [],
    }
    if data_paths_present is not None:
        payload["data_paths_present"] = data_paths_present
    return payload


async def test_warm_local_llm_scores_higher_than_cold_inference_worker(local_node_env, monkeypatch):
    local_id = str(uuid.uuid4())
    remote_id = str(uuid.uuid4())

    warm_node = _fake_node_dict(
        node_id=local_id,
        is_local=True,
        workers=[_inference_worker(node_id=local_id, status="not_loaded")],
    )
    cold_node = _fake_node_dict(
        node_id=remote_id,
        is_local=False,
        workers=[_inference_worker(node_id=remote_id, status="not_loaded")],
    )

    MANAGER.state.loaded = True
    MANAGER.state.alias = "Qwen3.5-27B"

    async def fake_list_nodes():
        return [cold_node, warm_node]

    monkeypatch.setattr("app.swarm.placement.list_nodes", fake_list_nodes)

    result = await place_work({"capabilities": [], "worker_kind": "inference"})
    assert result["accepted"] is True
    assert result["node_id"] == local_id
    assert result["worker"]["id"] == "local-llm"
    assert result["score"]["warm_bonus"] > 0
    assert "warm worker local-llm" in result["score"]["reasons"]


async def test_data_paths_on_localhost_beat_candidate_without_paths(local_node_env, monkeypatch):
    local_id = str(uuid.uuid4())
    remote_id = str(uuid.uuid4())
    data_file = local_node_env["tmp"] / "dataset.bin"
    data_file.write_text("payload", encoding="utf-8")

    local_node = _fake_node_dict(
        node_id=local_id,
        is_local=True,
        workers=[_inference_worker(node_id=local_id, status="ready")],
    )
    remote_node = _fake_node_dict(
        node_id=remote_id,
        is_local=False,
        workers=[_inference_worker(node_id=remote_id, status="ready")],
        data_paths_present=[],
    )

    MANAGER.state.loaded = False

    async def fake_list_nodes():
        return [remote_node, local_node]

    monkeypatch.setattr("app.swarm.placement.list_nodes", fake_list_nodes)

    result = await place_work(
        {
            "capabilities": [],
            "worker_kind": "inference",
            "data_paths": [str(data_file)],
        }
    )
    assert result["accepted"] is True
    assert result["node_id"] == local_id
    assert result["score"]["locality_bonus"] > 0
    assert any("local data" in reason for reason in result["score"]["reasons"])


async def test_missing_capability_still_rejects_before_scoring(local_node_env):
    await _setup_local_node()
    result = await place_work({"capabilities": ["totally_fake_capability"]})
    assert result["accepted"] is False
    assert result["code"] == "missing_capability"


async def test_single_eligible_worker_includes_score(local_node_env):
    node = await _setup_local_node()
    MANAGER.state.loaded = True

    result = await place_work({"capabilities": [], "worker_kind": "inference"})
    assert result["accepted"] is True
    assert result["node_id"] == node.id
    assert "score" in result
    assert isinstance(result["score"]["total"], int)


async def test_placement_empty_capabilities_still_200(local_node_env):
    await _setup_local_node()
    client = TestClient(app)

    response = client.post("/api/swarm/placement", json={"capabilities": []})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert "score" in body


async def test_intelligence_still_200_without_node_id(local_node_env):
    await _setup_local_node()
    client = TestClient(app)

    response = client.post(
        "/api/swarm/intelligence",
        json={"prompt": "summarize this research paper"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "node_id" not in body
    assert body["worker_kind"] == "inference"


async def test_warm_state_endpoint_reports_loaded_models(local_node_env):
    node = await _setup_local_node()
    MANAGER.state.loaded = True
    MANAGER.state.alias = "Qwen3.5-27B"
    client = TestClient(app)

    response = client.get(f"/api/swarm/nodes/{node.id}/warm-state")
    assert response.status_code == 200
    body = response.json()
    assert body["node_id"] == node.id
    assert "local-llm" in body["warm_workers"]
    assert body["loaded_models"]


def test_score_candidate_warm_bonus_independent_of_locality():
    node = _fake_node_dict(
        node_id="node-a",
        is_local=False,
        workers=[_inference_worker(node_id="node-a", status="ready")],
        data_paths_present=["/data/a"],
    )
    worker = node["workers"][0]
    warm_state = probe_node_warm_state(node)

    warm_only = score_candidate(
        node,
        worker,
        {"worker_kind": "inference"},
        warm_state,
    )
    locality_only = score_candidate(
        node,
        worker,
        {"worker_kind": "coding", "data_paths": ["/data/a"]},
        warm_state,
    )

    assert warm_only["warm_bonus"] > 0
    assert warm_only["locality_bonus"] == 0
    assert locality_only["warm_bonus"] == 0
    assert locality_only["locality_bonus"] > 0
