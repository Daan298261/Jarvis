from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.models import Node, NodeWorker
from app.db.session import SessionLocal
from app.inference.manager import MANAGER
from app.main import app
from app.swarm.capabilities import register_localhost_capabilities
from app.swarm.nodes import register_localhost_node
from app.swarm.placement import place_work
from app.swarm.warm_state import (
    DATA_LOCALITY_BONUS,
    LOCAL_NODE_BONUS,
    COLD_WORKER_PENALTY,
    RELOAD_PENALTY,
    WARM_MODEL_BONUS,
    WARM_WORKER_BONUS,
    localhost_warm_state,
    model_is_warm,
    path_is_local,
    score_node,
)
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


def test_path_is_local_under_allowed_root(tmp_path):
    nested = tmp_path / "docs" / "readme.md"
    nested.parent.mkdir()
    nested.write_text("hi", encoding="utf-8")
    assert path_is_local(str(nested), [str(tmp_path)]) is True
    assert path_is_local("/etc/passwd", [str(tmp_path)]) is False


def test_model_is_warm_matches_profile_and_local_llm_alias():
    warm = {
        "loaded": True,
        "profile": "balanced",
        "model_id": "qwen",
        "family": "qwen3.5",
        "model_path": "/models/Qwen3.5-9B-Q8_0.gguf",
        "quant": "Q8_0",
    }
    assert model_is_warm("balanced", warm) is True
    assert model_is_warm("local-llm", warm) is True
    assert model_is_warm("qwen3.5", warm) is True
    assert model_is_warm("expert", warm) is False
    assert model_is_warm("balanced", {**warm, "loaded": False}) is False


def test_score_prefers_warm_model_and_penalizes_reload():
    node = {"id": "local", "is_local": True, "workers": []}
    MANAGER.state.loaded = True
    MANAGER.state.profile = "balanced"
    warm = localhost_warm_state()
    warm_hit = score_node(node, {"model": "balanced"}, warm=warm)
    reload_hit = score_node(node, {"model": "expert"}, warm=warm)
    assert warm_hit["signals"]["warm_model"] is True
    assert reload_hit["signals"]["would_reload_model"] is True
    assert warm_hit["score"] - reload_hit["score"] == WARM_MODEL_BONUS + RELOAD_PENALTY


async def test_placement_includes_score_and_locality_signals(local_node_env):
    node = await _setup_local_node()
    MANAGER.state.loaded = True
    MANAGER.state.profile = "balanced"
    local_file = Path(local_node_env["tmp"]) / "notes.txt"
    local_file.write_text("x", encoding="utf-8")

    result = await place_work(
        {
            "capabilities": [],
            "model": "balanced",
            "paths": [str(local_file)],
        }
    )
    assert result["accepted"] is True
    assert result["node_id"] == node.id
    assert result["signals"]["warm_model"] is True
    assert result["signals"]["data_locality"] is True
    assert result["signals"]["matched_paths"] == [str(local_file)]
    assert result["score"] >= LOCAL_NODE_BONUS + WARM_MODEL_BONUS + DATA_LOCALITY_BONUS - COLD_WORKER_PENALTY
    assert result["candidates"][0]["selected"] is True


async def test_remote_path_does_not_get_locality_bonus(local_node_env):
    await _setup_local_node()
    result = await place_work(
        {
            "capabilities": [],
            "paths": ["/definitely/not/allowed/secret.bin"],
        }
    )
    assert result["accepted"] is True
    assert result["signals"]["data_locality"] is False
    assert result["signals"]["unmatched_paths"]


async def test_scoring_picks_warm_local_over_cold_remote(local_node_env):
    local = await _setup_local_node()
    async with SessionLocal() as session:
        session.add(
            Node(
                id="remote-cold",
                hostname="other-box",
                status="online",
                node_class="junior_worker",
                is_local=False,
                host_alias="other",
                address="10.0.0.9",
            )
        )
        session.add(
            NodeWorker(
                node_id="remote-cold",
                worker_id="filesystem",
                name="Filesystem",
                kind="worker",
                status="missing",
            )
        )
        await session.commit()

    result = await place_work({"capabilities": [], "worker_id": "filesystem"})
    assert result["accepted"] is True
    assert result["node_id"] == local.id
    assert result["signals"]["warm_worker"] is True
    assert result["score"] >= LOCAL_NODE_BONUS + WARM_WORKER_BONUS
    node_ids = {item["node_id"] for item in result["candidates"]}
    assert local.id in node_ids
    assert "remote-cold" in node_ids
    winner = next(item for item in result["candidates"] if item["selected"])
    assert winner["node_id"] == local.id
    remote = next(item for item in result["candidates"] if item["node_id"] == "remote-cold")
    assert winner["score"] >= remote["score"]


async def test_warm_state_on_node_and_snapshot_api(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)
    detail = client.get(f"/api/swarm/nodes/{node.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["warm_state"]["data_roots"]
    assert isinstance(body["warm_state"]["loaded"], bool)

    overview = client.get("/api/swarm")
    assert overview.status_code == 200
    assert "warm_state" in overview.json()

    placed = client.post(
        "/api/swarm/placement",
        json={"capabilities": [], "model": "balanced", "paths": [str(local_node_env["tmp"])]},
    )
    assert placed.status_code == 200
    payload = placed.json()
    assert payload["accepted"] is True
    assert "score" in payload
    assert "signals" in payload
