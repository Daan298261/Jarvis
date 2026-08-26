from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.swarm.nodes import register_localhost_node


@pytest.fixture
def setup_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.setup_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.diagnostics.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.diagnostics.logs_dir", lambda: jarvis_env["tmp"] / "logs")
    (jarvis_env["tmp"] / "logs").mkdir(exist_ok=True)
    return jarvis_env


async def test_setup_status_and_state_roundtrip(setup_env):
    await register_localhost_node()
    client = TestClient(app)
    status = client.get("/api/setup/status")
    assert status.status_code == 200
    body = status.json()
    assert body["needs_setup"] is True
    assert "welcome" in body["steps"]

    put = client.put("/api/setup/state", json={"current_step": "resources", "resource_preset": "dynamic", "global_percent": 40})
    assert put.status_code == 200
    assert put.json()["state"]["resource_preset"] == "dynamic"
    assert put.json()["state"]["global_percent"] == 40

    adv = client.post("/api/setup/advance", json={"step": "welcome", "next_step": "system"})
    assert adv.status_code == 200
    assert "welcome" in adv.json()["state"]["completed_steps"]

    rec = client.get("/api/setup/recommend")
    assert rec.status_code == 200
    assert "recommended_class" in rec.json()


async def test_setup_apply_and_diagnostics(setup_env):
    await register_localhost_node()
    client = TestClient(app)
    client.put(
        "/api/setup/state",
        json={
            "resource_preset": "dynamic",
            "global_percent": 50,
            "role_policies": {"orchestrator": "FORCED", "leader": "PREFERRED"},
            "inference_choice": "later",
        },
    )
    applied = client.post("/api/setup/apply")
    assert applied.status_code == 200
    assert applied.json()["ok"] is True

    diag = client.get("/api/diagnostics")
    assert diag.status_code == 200
    payload = diag.json()
    assert "node_id" in payload
    assert "data_directory" in payload
    assert "api_key" not in payload
    assert payload.get("auth_token") in (None, "[redacted]") or "auth_token" not in payload

    text = client.get("/api/diagnostics/text")
    assert text.status_code == 200
    assert "node_id:" in text.json()["text"]
