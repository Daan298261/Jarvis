from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.swarm.capabilities import list_node_capabilities, register_localhost_capabilities
from app.swarm.intelligence import dispatch_work, select_intelligence
from app.swarm.nodes import register_localhost_node
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


def test_intelligence_payload_has_no_node_id():
    result = select_intelligence("organize files on my desktop")
    assert "node_id" not in result
    assert result["task_class"]
    assert isinstance(result["capabilities"], list)
    assert result["worker_kind"]


def test_coding_prompt_selects_coding_worker_and_capability():
    result = select_intelligence("refactor this repository and fix the unit test")
    assert result["worker_kind"] == "coding"
    assert "coding" in result["capabilities"]


def test_browser_prompt_selects_browser_capability():
    result = select_intelligence("open the website and login with playwright")
    assert "browser" in result["capabilities"]


def test_select_intelligence_twice_does_not_call_placement(monkeypatch):
    place_mock = AsyncMock()
    monkeypatch.setattr("app.swarm.intelligence.place_work", place_mock)

    first = select_intelligence("rename files in the folder")
    second = select_intelligence("rename files in the folder")
    assert first == second
    place_mock.assert_not_called()


async def test_dispatch_filesystem_prompt_places_on_localhost(local_node_env):
    node = await _setup_local_node()
    result = await dispatch_work("copy files and organize the directory")

    assert result["placement"]["accepted"] is True
    assert result["placement"]["node_id"] == node.id
    assert result["intelligence"]["task_class"] == "filesystem"
    node_caps = {cap["id"] for cap in await list_node_capabilities(node.id)}
    assert set(result["intelligence"]["capabilities"]).issubset(node_caps)


async def test_dispatch_returns_intelligence_when_placement_rejected(local_node_env, monkeypatch):
    await _setup_local_node()

    def fake_select(_prompt: str, **kwargs):
        return {
            "task_class": "test",
            "worker_kind": "worker",
            "capabilities": ["totally_fake_capability"],
        }

    monkeypatch.setattr("app.swarm.intelligence.select_intelligence", fake_select)

    result = await dispatch_work("anything")
    assert result["intelligence"]["capabilities"] == ["totally_fake_capability"]
    assert result["placement"]["accepted"] is False
    assert result["placement"]["code"] == "missing_capability"


async def test_dispatch_http_returns_409_with_intelligence(local_node_env, monkeypatch):
    await _setup_local_node()
    client = TestClient(app)

    def fake_select(_prompt: str, **kwargs):
        return {
            "task_class": "test",
            "worker_kind": "worker",
            "capabilities": ["totally_fake_capability"],
        }

    monkeypatch.setattr("app.swarm.intelligence.select_intelligence", fake_select)

    response = client.post("/api/swarm/dispatch", json={"prompt": "anything"})
    assert response.status_code == 409
    body = response.json()
    assert body["intelligence"]["capabilities"] == ["totally_fake_capability"]
    assert body["placement"]["accepted"] is False


async def test_dispatch_http_success(local_node_env):
    node = await _setup_local_node()
    client = TestClient(app)

    response = client.post(
        "/api/swarm/dispatch",
        json={"prompt": "organize files in the desktop folder"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["placement"]["accepted"] is True
    assert body["placement"]["node_id"] == node.id
    assert "filesystem" in body["intelligence"]["capabilities"]


def test_intelligence_http_endpoint():
    client = TestClient(app)
    response = client.post(
        "/api/swarm/intelligence",
        json={"prompt": "debug pytest in the repository"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "node_id" not in body
    assert body["worker_kind"] == "coding"
    assert "coding" in body["capabilities"]


async def test_placement_contract_smoke_unchanged(local_node_env):
    await _setup_local_node()
    client = TestClient(app)

    response = client.post("/api/swarm/placement", json={"capabilities": []})
    assert response.status_code == 200
    assert response.json()["accepted"] is True
